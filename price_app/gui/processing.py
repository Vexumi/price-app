# -*- coding: utf-8 -*-
"""Экран 2 «Обработка»: фоновый прогон папки через конвейер (Экран 1 из
плана держит очередь магазинов, этот поток обрабатывает один пак за раз,
не блокируя интерфейс)."""
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .. import excel_io as X
from .. import pipeline as PL


class ProcessingThread(QThread):
    progress = Signal(int, int, str)          # обработано, всего, имя файла
    finished_run = Signal(int, list)           # id пака, результаты process_photo
    failed = Signal(int, str)                  # id пака, текст ошибки

    def __init__(self, ctx, shop_run, photos):
        super().__init__()
        self.ctx = ctx
        self.shop_run = shop_run
        self.photos = photos

    def run(self):
        try:
            self.ctx.ensure_engines()
        except Exception as e:
            self.failed.emit(self.shop_run["id"], f"Не удалось загрузить модель распознавания:\n{e}")
            return

        chain = self.shop_run["chain"]
        candidates = self.ctx.candidates_for(chain)
        results = []
        for i, photo in enumerate(self.photos, 1):
            try:
                r = PL.process_photo(photo, chain, candidates, self.ctx.store,
                                      self.shop_run["shop_name"], self.ctx.engine,
                                      self.ctx.refine_engine)
            except Exception as e:
                r = {"photo": str(photo), "price": None, "discount": False, "row": None,
                     "product": None, "status": "на проверку", "why": f"ошибка обработки: {e}",
                     "candidates": [], "text": "", "price_bbox": None, "img_w": None, "img_h": None}
            results.append(r)
            if r["status"] == "авто":
                self.ctx.store.cache_put(chain, X.norm(r["text"]), r["row"])
            self.progress.emit(i, len(self.photos), Path(photo).name)
        self.finished_run.emit(self.shop_run["id"], results)
