# -*- coding: utf-8 -*-
"""Сравнение выдачи парсера с ручным эталоном."""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from price_app.parse import parse_photo

raw = json.load(open("out/ocr_tuned.json", encoding="utf-8"))
et = json.load(open("bench/etalon.json", encoding="utf-8"))

price_ok = disc_ok = refused = wrong = 0
print(f"{'фото':>6} | {'эталон':>8} | {'парсер':>8} | итог")
print("-" * 64)
for name, e in et.items():
    r = parse_photo(raw[name])
    got, want = r["price"], e["price"]
    if want is None:                       # не ценник: правильный ответ - отказ
        good = got is None
        verd = "верно отказался" if good else "МУСОР ПРОПУЩЕН"
    elif got is None:
        good = False; verd = "отказ (на проверку)"; refused += 1
    else:
        good = abs(got - want) < 0.005
        verd = "верно" if good else "НЕВЕРНО"
        if not good: wrong += 1
    if good and want is not None: price_ok += 1
    if got is not None and want is not None and r["discount"] == e["disc"]: disc_ok += 1
    g = f"{got:8.2f}" if got is not None else "     ---"
    w = f"{want:8.2f}" if want is not None else "     ---"
    print(f"{name[14:-4]or'PNG':>6} | {w} | {g} | {verd:<20} {e['note']}")

n = len([1 for v in et.values() if v["price"] is not None])
print("-" * 64)
print(f"цена верна:            {price_ok}/{n}  ({100*price_ok/n:.0f}%)")
print(f"неверная цена:         {wrong}/{n}   <- опаснее всего")
print(f"честный отказ:         {refused}/{n}")
print(f"акция определена:      {disc_ok}/{n}")
