# -*- coding: utf-8 -*-
"""Поиск строки таблицы по тексту ценника."""
import re
from rapidfuzz import fuzz

# «300 У Н Хлеб Двинский» -> «Хлеб Двинский»: в начале названия стоят
# служебная масса и коды типа (У/З/Д/Х - упакованный, замороженный и т.п.)
RE_PREFIX = re.compile(r"^\d{2,4}\s+[УЗДХ]\s+(?:Н\s+)?", re.I)
RE_MASS = re.compile(r"(\d{2,4})\s*(?:г|гр)\b", re.I)
RE_TRASH = re.compile(r"[^\w\s]", re.U)

# Юрлицо/бренд на ценнике -> сеть в таблице. OCR сильно коверкает эти
# строки («КАМЕЛОТ-Л», «KAMEJOT-A», «3денент-Трей»), поэтому сравнение
# нечёткое, а не по точному образцу.
ORG_TO_CHAIN = [
    ("камелот",        "ЯРЧЕ"),
    ("элемент трейд",  "МОНЕТКА"),
    ("пятерочка",      "ПЯТЕРОЧКА"),
    ("больше пятерочка", "ПЯТЕРОЧКА"),
    ("тандер",         "МАГНИТ (S)"),
    ("моя цена",       "МАГНИТ МОЯ ЦЕНА"),
    ("лента",          "ЛЕНТА (S)"),
    ("мария ра",       "МАРИЯ-РА"),
    ("ашан",           "АШАН"),
    ("окей",           "ОКЕЙ"),
    ("спар",           "SPAR"),
    ("метро",          "METRO"),
    ("быстроном",      "БЫСТРОНОМ"),
    ("чижик",          "ЧИЖИК"),
]


def as_int(v):
    """Масса из таблицы: там встречаются пустые ячейки и прочерки."""
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def norm(s):
    """Привести название к виду, пригодному для сравнения."""
    s = RE_PREFIX.sub("", str(s or ""))
    s = RE_TRASH.sub(" ", s.lower())
    return " ".join(s.split())


def mass_of(text):
    """Масса в граммах из текста ценника."""
    m = RE_MASS.findall(text or "")
    return int(m[0]) if m else None


def chain_of(text, cutoff=78):
    """Сеть по юрлицу или бренду, напечатанному на ценнике.

    В приложении сеть задаёт пользователь при добавлении папки магазина;
    это лишь подсказка, чтобы не выбирать вручную каждый раз.
    """
    low = RE_TRASH.sub(" ", (text or "").lower())
    low = " ".join(low.split())
    best, best_s = None, 0
    for key, chain in ORG_TO_CHAIN:
        s = fuzz.partial_ratio(key, low)
        if s > best_s:
            best, best_s = chain, s
    return best if best_s >= cutoff else None


def score(tag_text, cand_name):
    """Похожесть ценника и строки таблицы.

    token_set_ratio, потому что порядок слов не совпадает: на ценнике
    «с малиновой начинкой слойка 78г», в таблице «Слойка с малиновой
    начинкой».
    """
    return fuzz.token_set_ratio(norm(tag_text), norm(cand_name))


def find(tag_text, candidates, tag_mass=None, top=5):
    """Подобрать строки таблицы.

    candidates: [(row, product, manuf, brand, mass), ...]
    Возвращает список (балл, row, product, mass), лучшие сверху.
    """
    if tag_mass is None:
        tag_mass = mass_of(tag_text)

    pool = candidates
    if tag_mass:
        # Масса - самый сильный признак: она либо совпадает, либо это
        # другой товар. Допуск на случай, если OCR ошибся в одной цифре.
        exact = [c for c in candidates
                 if as_int(c[4]) is not None and abs(as_int(c[4]) - tag_mass) <= 2]
        if exact:
            pool = exact

    out = []
    for row, prod, manuf, brand, mass in pool:
        s = score(tag_text, prod)
        # торговая марка на ценнике печатается в скобках: «(Восход)»
        if brand and norm(brand) and norm(brand) in norm(tag_text):
            s += 6
        out.append((min(s, 100), row, prod, mass))
    out.sort(reverse=True)
    return out[:top]


def decide(ranked, auto=88, gap=6):
    """Записывать автоматически или отправить на подтверждение.

    Мало высокого балла: если второй кандидат почти так же похож,
    выбор между ними - угадывание. Так было с «Лепешки Mission grill
    Тортильи пш.оригин.», подходившим сразу к двум строкам.
    """
    if not ranked:
        return None, "кандидатов нет"
    best = ranked[0]
    if best[0] < auto:
        return None, f"низкая уверенность ({best[0]})"
    if len(ranked) > 1 and best[0] - ranked[1][0] < gap:
        return None, f"два похожих кандидата ({best[0]} и {ranked[1][0]})"
    return best, "уверенно"
