# -*- coding: utf-8 -*-
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from price_app.parse import parse_photo

raw = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "out/ocr_tuned.json", encoding="utf-8"))
ok = notag = 0
for name, rec in sorted(raw.items(), key=lambda kv: kv[0]):
    r = parse_photo(rec)
    p = f"{r['price']:7.2f}" if r["price"] is not None else "   ---"
    if r["price"] is not None: ok += 1
    if not r["tag"]: notag += 1
    print(f"{p} {'АКЦ' if r['discount'] else '   '} | {name[14:-4]:>5} | {r['why']:<24} | {r['text'][:46]}")
print(f"\nцена: {ok}/{len(raw)} | отсеяно как «не ценник»: {notag}")
