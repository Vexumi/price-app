# -*- coding: utf-8 -*-
"""Прогон OCR по папке. Кадр увеличивается вдвое: без этого мелкие
надстрочные копейки читаются неверно (99 превращается в 66)."""
import sys, json, time, pathlib
import numpy as np
from PIL import Image
from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType

SCALE = 1        # детектору даём разрешение через limit_side_len, а не ресайзом

src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
eng = RapidOCR(params={"Rec.lang_type": LangRec.ESLAV,
                       "Rec.ocr_version": OCRVersion.PPOCRV5,
                       "Rec.model_type": ModelType.MOBILE,
                       # 1600 вместо 736: иначе детектор ужимает кадр и теряет
                       # надстрочные копейки; 1.2 вместо 1.6 - меньше слипания
                       "Det.limit_side_len": 1600,
                       "Det.unclip_ratio": 1.2})

files = sorted([p for p in src.iterdir()
                if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
out, times = {}, []
for i, p in enumerate(files, 1):
    im = Image.open(p).convert("RGB")
    w, h = im.size
    im = im.resize((w * SCALE, h * SCALE), Image.LANCZOS)
    t = time.time(); res = eng(np.array(im)); dt = time.time() - t
    times.append(dt)
    blocks = []
    if res.txts:
        for box, txt, sc in zip(res.boxes, res.txts, res.scores):
            xs = [q[0] / SCALE for q in box]; ys = [q[1] / SCALE for q in box]
            blocks.append({"text": txt, "conf": float(sc),
                           "x0": float(min(xs)), "x1": float(max(xs)),
                           "y0": float(min(ys)), "y1": float(max(ys)),
                           "h": float(max(ys) - min(ys))})
    out[p.name] = {"w": w, "h": h, "blocks": blocks}
    print(f"[{i:2}/{len(files)}] {dt:5.2f}c {len(blocks):2}бл  {p.name}", flush=True)

dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n{len(files)} фото | среднее {sum(times)/len(times):.2f}c | сумма {sum(times):.1f}c")
