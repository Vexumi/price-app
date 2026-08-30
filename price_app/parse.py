# -*- coding: utf-8 -*-
"""Разбор OCR-блоков одного фото ценника.

Собирает числовые блоки в цельные цены (крупное целое + копейки часто
приходят раздельными блоками), выбирает нужный ценник, когда в кадре
несколько, и определяет, акционная ли цена.
"""
import re

RE_DATE = re.compile(r"^\d{2}[.,]\d{2}[.,]\d{4}$")        # 13.01.2026 - дата печати
RE_INT = re.compile(r"^\d{1,5}$")   # до 5: склеенная цена бывает вида 11498
RE_DEC = re.compile(r"^(\d{1,4})[.,](\d{2})$")   # 119.98 / 24,99 - копейки всегда 2 цифры, 1 - признак повреждённого чтения
RE_ORG = re.compile(r"[О0O]{2,3}\s*[\"'«]?\s*[КKСC]А?[МM]", re.I)
RE_BARCODE = re.compile(r"^\d{9,14}$")                    # штрихкод / артикул

PRICE_MIN, PRICE_MAX = 5.0, 500.0
CENTER_FRAC = 0.70        # доля ширины кадра для отбора ТЕКСТА названия


def _is_noise(t):
    t = t.strip()
    return bool(RE_DATE.match(t) or RE_ORG.search(t) or RE_BARCODE.match(t)
                or t in ("шт", ",", "□", "1 шт.", "1 WT.", "1WT."))


def in_center(b, img_w):
    """Центр блока попадает в центральную зону кадра (для текста названия).

    Снимающий наводит камеру на нужный ценник, поэтому его название
    почти всегда в центре. Для цены эта зона не используется - выгодная
    цена изредка печатается ближе к краю кадра, и её нельзя терять.
    """
    m = img_w * (1 - CENTER_FRAC) / 2
    cx = (b["x0"] + b["x1"]) / 2
    return m <= cx <= img_w - m


def _num(b):
    """Текст числового блока, очищенный от шума детектора.

    Два типичных дефекта:
    - оторвавшаяся пунктуация: 21,99 приходит как «21.» и «.99»;
    - мусорный хвост на месте нечитаемой копейки: «39.g» - берём то,
      что распознано надёжно (целую часть), а копейки ищет соседний блок.
    """
    t = b["text"].strip()
    if re.match(r"^[.,]?\d+[.,]?$", t):
        return t.strip(".,")
    m = re.match(r"^(\d{1,4})[.,][^\d]", t)
    if m:
        return m.group(1)
    return t


def _glued(txt):
    """Число, где копейки слиплись с рублями: 39,99 -> "3999"."""
    if len(txt) == 4:
        return float(f"{txt[:2]}.{txt[2:]}"), "склейка NN,NN"
    if len(txt) == 5:
        return float(f"{txt[:3]}.{txt[3:]}"), "склейка NNN,NN"
    return float(txt), "только целое"


def price_groups(blocks):
    """Собрать числовые блоки в цельные цены.

    Одна цена - это либо один блок («119.98»), либо пара: крупное целое
    и копейки меньшим кеглем правее и выше нижнего края целого. Каждая
    такая пара схлопывается в одну запись со своей геометрией, чтобы
    дальше работать с ценами, а не с обрывками OCR.
    """
    nums = [b for b in blocks
            if (RE_INT.match(_num(b)) or RE_DEC.match(_num(b)))
            and not RE_DATE.match(_num(b))]
    used, groups = set(), []

    for b in nums:                                  # одноблочные NN.NN
        if id(b) in used:
            continue
        m = RE_DEC.match(_num(b))
        if m:
            val = float(f"{m.group(1)}.{m.group(2):0<2}")
            groups.append(_mk_group(val, b, b, "одним блоком"))
            used.add(id(b))

    rest = sorted((b for b in nums if id(b) not in used), key=lambda b: -b["h"])
    for big in rest:                                 # крупное целое (+копейки)
        if id(big) in used:
            continue
        kop = next((k for k in rest if id(k) not in used and k is not big
                    and len(_num(k)) == 2
                    and k["h"] < big["h"] * 0.8
                    and k["x0"] >= big["x1"] - big["h"] * 0.4
                    and abs(k["y0"] - big["y0"]) < big["h"] * 0.7), None)
        if kop:
            val = float(f"{_num(big)}.{_num(kop)}")
            g = _mk_group(val, big, kop, "целое+копейки")
            g["kop_block"] = kop
            groups.append(g)
            used.add(id(big)); used.add(id(kop))
        else:
            val, why = _glued(_num(big))
            groups.append(_mk_group(val, big, big, why))
            used.add(id(big))

    groups.sort(key=lambda g: g["y"])
    return groups


def _mk_group(val, b0, b1, why):
    return {"val": val, "h": b0["h"],
            "y": (b0["y0"] + b1["y1"]) / 2, "x": (b0["x0"] + b1["x1"]) / 2,
            "why": why,
            "x0": min(b0["x0"], b1["x0"]), "x1": max(b0["x1"], b1["x1"]),
            "y0": min(b0["y0"], b1["y0"]), "y1": max(b0["y1"], b1["y1"])}


def per_one_item(blocks, groups):
    """Ценники с градацией «за 1 шт / от 2 шт / от 3 шт».

    Магазин печатает крупнее самую выгодную цену (от 3 шт), но в срез
    идёт цена за одну штуку - правило из CLAUDE.md. Метка и её цена не
    всегда выровнены по одной высоте (метка сама по себе многострочная
    и может visually сидеть между двумя ценовыми строками), поэтому
    сопоставляем не по вертикальному перекрытию, а по порядковому месту
    сверху вниз: i-я по счёту метка соответствует i-й по счёту цене.
    """
    marks = sorted((b for b in blocks if re.search(r"\b(за|от)\s*\d\s*шт", b["text"], re.I)),
                   key=lambda b: b["y0"])
    if len(marks) < 2 or len(groups) < 2:
        return None
    idx = next((i for i, b in enumerate(marks)
                if re.search(r"\b(за|от)\s*1\s*шт", b["text"], re.I)), None)
    if idx is None or idx >= len(groups):
        return None
    g = groups[idx]
    if g["why"] == "только целое":
        return None
    return g["val"]


def extract_price(blocks, img_w):
    """Выбрать нужную цену среди всех найденных на фото.

    В кадр иногда попадают обрывки соседних ценников, а нужная цена не
    всегда идеально по центру. Якорь - самая крупная из цен, что лежат
    достаточно близко к максимальной высоте (не мельче половины неё),
    а среди них - ближайшая к центру кадра: так снимающий кадрирует то,
    что фотографирует.
    """
    groups = price_groups(blocks)
    if not groups:
        return None, False, "цифр не найдено"

    one = per_one_item(blocks, groups)
    if one is not None:
        return one, False, "цена за 1 шт"

    max_h = max(g["h"] for g in groups)
    cx_img = img_w / 2
    pool = [g for g in groups if g["h"] >= max_h * 0.55]
    anchor = min(pool, key=lambda g: abs(g["x"] - cx_img))

    # зачёркнутая старая цена: мельче основной и рядом по вертикали
    discount = any(g is not anchor and g["h"] < anchor["h"] * 0.75
                   and abs(g["y"] - anchor["y"]) < anchor["h"] * 2 for g in groups)

    if anchor["why"] == "только целое":
        # Копейки не нашлись вообще ни как отдельный блок, ни как склейка.
        # На этих ценниках голая круглая цена практически не встречается
        # (везде «,99» / «,98») - скорее детектор не увидел мелкий текст,
        # чем товар и правда стоит ровно 55 рублей. Писать такое молча
        # нельзя - лучше на проверку, чем «55,00» вместо «55,99».
        return None, discount, "копейки не найдены - на проверку"
    return anchor["val"], discount, anchor["why"]


def looks_like_pricetag(blocks, img_h):
    """Отсев фото, которые вообще не являются ценниками.

    В выборке нашёлся снимок экрана телефона с картой такси - система
    приняла номер машины за цену. Надёжный признак: на ценнике цена
    печатается заметно крупнее подписей, а на постороннем снимке текст
    везде примерно одного размера или крупнее чисел.
    """
    if not blocks:
        return False, "пусто"
    nums = [b for b in blocks if RE_INT.match(_num(b)) or RE_DEC.match(_num(b))]
    if not nums:
        return False, "чисел не видно"
    txt = [b for b in blocks if b not in nums]
    if txt:
        med = sorted(b["h"] for b in txt)[len(txt) // 2]
        if max(b["h"] for b in nums) < med * 1.2:
            return False, "цена не крупнее текста - похоже, это не ценник"
    return True, ""


def parse_photo(rec):
    """Полный разбор одного фото: {'w','h','blocks'} -> результат."""
    img_w = rec.get("w", 1280)
    blocks = rec["blocks"]
    okay, why_not = looks_like_pricetag(blocks, rec.get("h", 960))
    if not okay:
        return {"price": None, "discount": False, "why": f"не ценник: {why_not}",
                "text": "", "tag": False}

    price, discount, why = extract_price(blocks, img_w)
    if price is not None and not (PRICE_MIN <= price <= PRICE_MAX):
        price, why = None, f"вне диапазона: {price}"

    center = [b for b in blocks if in_center(b, img_w)]
    useful = [b for b in center if not _is_noise(b["text"])]
    words = [b["text"].strip() for b in sorted(useful, key=lambda b: b["y0"])
             if not RE_INT.match(_num(b)) and not RE_DEC.match(_num(b))]
    return {"price": price, "discount": discount, "why": why,
            "text": " ".join(words), "tag": True}
