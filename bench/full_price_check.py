# -*- coding: utf-8 -*-
"""Полная проверка цены: разбор + уточняющий проход копеек, если найден
отдельный блок. Используется поверх сырых OCR-данных и оригинальных фото."""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType
import price_app.parse as P
from price_app.refine import refine_kopecks

_engine = None
def engine():
    global _engine
    if _engine is None:
        _engine = RapidOCR(params={"Rec.lang_type": LangRec.ESLAV, "Rec.ocr_version": OCRVersion.PPOCRV5,
                                   "Rec.model_type": ModelType.MOBILE,
                                   "Det.limit_side_len": 1600, "Det.unclip_ratio": 1.2})
    return _engine


def parse_with_refine(rec, image_path):
    """Как parse_photo, но с уточнением копеек крупным планом."""
    img_w = rec.get("w", 1280)
    blocks = rec["blocks"]
    okay, why_not = P.looks_like_pricetag(blocks, rec.get("h", 960))
    if not okay:
        return {"price": None, "discount": False, "why": f"не ценник: {why_not}", "tag": False}

    groups = P.price_groups(blocks)
    if not groups:
        return {"price": None, "discount": False, "why": "цифр не найдено", "tag": True}

    one = P.per_one_item(blocks, groups)
    if one is not None:
        return {"price": one, "discount": False, "why": "цена за 1 шт", "tag": True}

    max_h = max(g["h"] for g in groups)
    cx_img = img_w / 2
    pool = [g for g in groups if g["h"] >= max_h * 0.55]
    anchor = min(pool, key=lambda g: abs(g["x"] - cx_img))
    discount = any(g is not anchor and g["h"] < anchor["h"] * 0.75
                   and abs(g["y"] - anchor["y"]) < anchor["h"] * 2 for g in groups)

    if anchor.get("kop_block"):
        original_kop = anchor["kop_block"]["text"].strip().strip(".,'\"")
        refined = refine_kopecks(image_path, anchor["kop_block"], engine())
        if refined and refined != original_kop:
            # Два независимых прочтения одного места разошлись - нельзя
            # угадывать, какое верное. Ошибиться молча хуже, чем спросить.
            return {"price": None, "discount": discount,
                    "why": f"прочтения разошлись: {original_kop} vs {refined}", "tag": True}

    if anchor["why"] == "только целое":
        return {"price": None, "discount": discount, "why": "копейки не найдены - на проверку", "tag": True}

    price = anchor["val"]
    if not (P.PRICE_MIN <= price <= P.PRICE_MAX):
        return {"price": None, "discount": discount, "why": f"вне диапазона: {price}", "tag": True}
    return {"price": price, "discount": discount, "why": anchor["why"], "tag": True}


if __name__ == "__main__":
    json_path, etalon_path, photos_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    raw = json.load(open(json_path, encoding="utf-8"))
    et = json.load(open(etalon_path, encoding="utf-8"))
    ok = wrong = refused = 0
    for name, e in et.items():
        want = e.get("price") if isinstance(e, dict) else e
        path = str(pathlib.Path(photos_dir) / name)
        r = parse_with_refine(raw[name], path)
        got = r["price"]
        if want is None:
            verd = "верно отказался" if got is None else f"МУСОР {got}"
            ok += got is None; wrong += got is not None
        elif got is None:
            verd = "отказ"; refused += 1
        elif abs(got - want) < 0.005:
            verd = "верно"; ok += 1
        else:
            verd = "НЕВЕРНО"; wrong += 1
        g = f"{got:7.2f}" if got is not None else "   ---"
        w = f"{want:7.2f}" if want is not None else "   ---"
        note = e.get("note", "") if isinstance(e, dict) else ""
        print(f"{name[14:-4] or 'PNG':>5} | {w} | {g} | {verd:<16} | {r['why']:<28} | {note}")
    n = len(et)
    print(f"\nверно {ok}/{n} ({100*ok//n}%) | НЕВЕРНО {wrong} | отказ {refused}")
