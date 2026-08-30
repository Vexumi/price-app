# -*- coding: utf-8 -*-
"""Общее состояние GUI-сессии: открытая таблица, движки OCR, журнал.

Один экземпляр на приложение - создаётся в main_window при выборе файла
таблицы и переживает переключение между экранами.
"""
from pathlib import Path

from .. import excel_io as X
from .. import pipeline as PL
from ..store import Store

DB_NAME = "price_app.db"


class AppContext:
    def __init__(self, table_path):
        self.table_path = str(table_path)
        self.reload_table()
        db_path = str(Path(self.table_path).resolve().parent / DB_NAME)
        self.store = Store(db_path)
        self.engine = None
        self.refine_engine = None

    def reload_table(self):
        self.wb, self.ws, self.header_row, self.cols = X.load_table(self.table_path)
        self.chains = X.list_chains(self.ws, self.header_row, self.cols)

    def ensure_engines(self):
        """Ленивая загрузка движков OCR - занимает десятки секунд, нужна
        один раз за сессию (при первом «Обработать всё»), а не при каждом
        запуске приложения. ВАЖНО: engine и refine_engine должны оставаться
        РАЗНЫМИ экземплярами RapidOCR на всё время жизни приложения - см.
        предупреждение в pipeline.make_engine про мутацию self.use_det."""
        if self.engine is None:
            self.engine = PL.make_engine()
            self.refine_engine = PL.make_refine_engine()

    def candidates_for(self, chain):
        return X.build_candidates(self.ws, self.header_row, self.cols, chain)
