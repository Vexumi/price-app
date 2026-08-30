# -*- coding: utf-8 -*-
"""Полный конвейер одного фото: OCR -> цена (с уточнением копеек) ->
товар -> решение «писать самим / на подтверждение».

Логика извлечения цены здесь, а не в parse.py, потому что ей нужен
доступ к самому изображению (для уточняющего прохода) и к движку OCR -
а parse.py работает только с уже готовыми блоками распознавания и не
знает ни про файлы, ни про движок. bench/-скрипты замера точности
импортируют extract_price_refined отсюда же, чтобы логика не
разъезжалась по двум местам.
"""
import numpy as np
from PIL import Image, ImageOps
from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType

from . import parse as P
from . import match as M
from .refine import refine_kopecks

PRICE_SANITY_RATIO = 3   # цена отличается от прошлой в 3+ раза - подозрительно


def make_engine():
    """Основной движок: детектор + распознаватель.

    ВАЖНО: RapidOCR.__call__(use_det=False, ...) не действует разово -
    он мутирует self.use_det НАВСЕГДА (см. update_params в main.py),
    поэтому движок для уточняющего прохода (extract_price_refined)
    должен быть ОТДЕЛЬНЫМ экземпляром - иначе после первого же
    уточнения детектор отключается для всех следующих фото."""
    return RapidOCR(params={
        "Rec.lang_type": LangRec.ESLAV, "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
        "Det.limit_side_len": 1600, "Det.unclip_ratio": 1.2,
    })


def make_refine_engine():
    """Отдельный движок для refine_kopecks - см. предупреждение в make_engine."""
    return make_engine()


def run_ocr(image_path, engine):
    """EXIF-поворот + распознавание. У PNG-примеров EXIF нет, но подруга
    снимает на Android - там он есть, и без поворота OCR читает боком."""
    im = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    res = engine(np.array(im))
    blocks = []
    if res.txts:
        for box, txt, sc in zip(res.boxes, res.txts, res.scores):
            xs = [p[0] for p in box]; ys = [p[1] for p in box]
            blocks.append({"text": txt, "conf": float(sc),
                           "x0": float(min(xs)), "x1": float(max(xs)),
                           "y0": float(min(ys)), "y1": float(max(ys)),
                           "h": float(max(ys) - min(ys))})
    return {"w": im.width, "h": im.height, "blocks": blocks}


def extract_price_refined(rec, image_path, refine_engine):
    """Как parse.extract_price, но с уточнением копеек крупным планом.

    Если обычное и уточняющее прочтения разошлись - не гадаем, какое
    верно, отправляем на проверку (см. случай с G6 в бенчмарке: слепое
    предпочтение уточнённого чтения один раз заменило верный ответ
    неверным).

    Возвращает (цена, скидка, причина, bbox) - bbox (или None) нужен GUI,
    чтобы обвести рамкой на фото то место, откуда взята цена."""
    blocks = rec["blocks"]
    groups = P.price_groups(blocks)
    if not groups:
        return None, False, "цифр не найдено", None

    one = P.per_one_item(blocks, groups)
    if one is not None:
        return one, False, "цена за 1 шт", None

    max_h = max(g["h"] for g in groups)
    cx_img = rec.get("w", 1280) / 2
    pool = [g for g in groups if g["h"] >= max_h * 0.55]
    anchor = min(pool, key=lambda g: abs(g["x"] - cx_img))
    discount = any(g is not anchor and g["h"] < anchor["h"] * 0.75
                   and abs(g["y"] - anchor["y"]) < anchor["h"] * 2 for g in groups)
    bbox = {"x0": anchor["x0"], "y0": anchor["y0"], "x1": anchor["x1"], "y1": anchor["y1"]}

    if anchor.get("kop_block"):
        original = anchor["kop_block"]["text"].strip().strip(".,'\"")
        refined = refine_kopecks(image_path, anchor["kop_block"], refine_engine)
        if refined and refined != original:
            return None, discount, f"прочтения разошлись: {original} vs {refined}", bbox

    if anchor["why"] == "только целое":
        return None, discount, "копейки не найдены - на проверку", bbox

    price = anchor["val"]
    if not (P.PRICE_MIN <= price <= P.PRICE_MAX):
        return None, discount, f"вне диапазона: {price}", bbox
    return price, discount, anchor["why"], bbox


def product_text(rec):
    """Текст названия для матчинга: центральная зона кадра, без цифр."""
    center = [b for b in rec["blocks"] if P.in_center(b, rec.get("w", 1280))]
    useful = [b for b in center if not P._is_noise(b["text"])]
    words = [b["text"].strip() for b in sorted(useful, key=lambda b: b["y0"])
             if not P.RE_INT.match(P._num(b)) and not P.RE_DEC.match(P._num(b))]
    return " ".join(words)


def process_photo(image_path, chain, candidates, store, shop_name, engine, refine_engine):
    """Полный разбор одного фото ценника.

    candidates: [(row, product, manuf, brand, mass), ...] для этой сети.
    store: price_app.store.Store - кэш и история цен магазина.
    engine/refine_engine - два РАЗНЫХ экземпляра RapidOCR, см. make_engine.
    """
    rec = run_ocr(image_path, engine)
    out = {"photo": str(image_path), "price": None, "discount": False,
           "row": None, "product": None, "status": "на проверку",
           "why": "", "candidates": [], "text": "", "price_bbox": None,
           "img_w": rec.get("w"), "img_h": rec.get("h")}

    okay, why_not = P.looks_like_pricetag(rec["blocks"], rec.get("h", 960))
    if not okay:
        out["why"] = f"не ценник: {why_not}"
        return out

    price, discount, why, bbox = extract_price_refined(rec, image_path, refine_engine)
    out["price"], out["discount"], out["why"], out["price_bbox"] = price, discount, why, bbox
    text = product_text(rec)
    out["text"] = text

    fp = M.norm(text)
    cached_row = store.cache_get(chain, fp) if fp else None
    if cached_row:
        out["row"] = cached_row
        out["product"] = next((p for r, p, *_ in candidates if r == cached_row), None)
        out["candidates"] = [(100, cached_row, out["product"], None)]
    else:
        ranked = M.find(text, candidates)
        out["candidates"] = ranked
        best, _ = M.decide(ranked)
        if best:
            out["row"], out["product"] = best[1], best[2]

    if price is not None and out["row"] is not None:
        history = store.price_history(chain, out["row"], shop_name)
        if history and history[0]["price"] > 0:
            ratio = price / history[0]["price"]
            if ratio > PRICE_SANITY_RATIO or ratio < 1 / PRICE_SANITY_RATIO:
                out["status"] = "подозрительная цена"
                out["why"] = (f"было {history[0]['price']:.2f} у этого магазина, "
                              f"сейчас {price:.2f} - проверь")
                return out

    if price is not None and out["row"] is not None:
        out["status"] = "авто"
    elif price is not None:
        out["status"] = "нужен товар"
    elif out["row"] is not None:
        out["status"] = "нужна цена"
    return out
