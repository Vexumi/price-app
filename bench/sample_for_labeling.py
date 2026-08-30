# -*- coding: utf-8 -*-
"""Взять случайную выборку фото для ручной разметки эталона.

328 фото размечать все вручную долго и не нужно - случайная выборка
даёт статистически честную оценку при разумном объёме ручной работы.
"""
import json, random, sys

SEED = 42          # фиксируем, чтобы выборка повторялась одинаково
N = 40

raw = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "out/ocr_328.json",
                     encoding="utf-8"))
names = sorted(raw.keys())
random.Random(SEED).shuffle(names)
sample = sorted(names[:N])
for n in sample:
    print(n)
