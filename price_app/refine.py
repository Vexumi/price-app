# -*- coding: utf-8 -*-
"""Уточняющий проход OCR: перечитать копейки крупным планом.

Мелкий надстрочный шрифт копеек иногда распознаётся неверно (99 -> 66)
при обычном разрешении - это ограничение движка на мелком тексте, а не
ошибка логики разбора. Локальная вырезка вокруг самого блока копеек,
увеличенная так, чтобы его высота стала ~280px, читается надёжнее.
"""
import numpy as np
from PIL import Image


def refine_kopecks(image_path, kop_block, engine):
    """Перечитать копейки для найденной цены крупным планом.

    kop_block: геометрия ИМЕННО блока копеек (не всей цены) - его
    исходная высота обычно мала (40-90px), поэтому увеличиваем сильно.
    Возвращает две цифры строкой или None, если не удалось.
    """
    im = Image.open(image_path).convert("RGB")
    h = kop_block["h"]
    pad_x, pad_y = h * 0.6, h * 0.6
    box = (max(0, int(kop_block["x0"] - pad_x)), max(0, int(kop_block["y0"] - pad_y)),
           min(im.width, int(kop_block["x1"] + pad_x)), min(im.height, int(kop_block["y1"] + pad_y)))
    crop = im.crop(box)
    if crop.width < 3 or crop.height < 3:
        return None
    k = max(1, round(280 / crop.height))
    crop = crop.resize((crop.width * k, crop.height * k), Image.LANCZOS)

    # use_det=False: не искать текстовую область заново, а прочитать всю
    # вырезку как одну строку. Тесный кроп читаем человеку, но детектор
    # на нём иногда не находит область текста вовсе - а распознаватель
    # без него читает уверенно.
    res = engine(np.array(crop), use_det=False, use_cls=False)
    if not res.txts:
        return None
    t = "".join(ch for ch in res.txts[0] if ch.isdigit())
    return t[-2:] if len(t) >= 2 else None
