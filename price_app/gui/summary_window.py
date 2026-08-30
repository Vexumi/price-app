# -*- coding: utf-8 -*-
"""Экран 4 «Итог по магазину»: сводка + запись в Excel.

Кнопка записи недоступна, пока есть неразобранные конфликты (см. план).
Повторное открытие после записи безопасно - photo_items_pending_journal
не даёт задвоить журнал, а write_prices просто перезапишет те же ячейки.
"""
import datetime

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                QPushButton, QMessageBox)

from .. import excel_io as X
from .conflict_dialog import ConflictDialog


class SummaryWindow(QMainWindow):
    def __init__(self, ctx, shop_run_id, on_closed=None):
        super().__init__()
        self.ctx = ctx
        self.shop_run_id = shop_run_id
        self.shop_run = ctx.store.shop_run_get(shop_run_id)
        self._on_closed = on_closed

        self.setWindowTitle(f"Итог · {self.shop_run['chain']} · {self.shop_run['shop_name']}")
        self.resize(420, 320)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        self.v = QVBoxLayout(central)
        self.title_label = QLabel()
        self.v.addWidget(self.title_label)
        self.counts_label = QLabel()
        self.counts_label.setWordWrap(True)
        self.v.addWidget(self.counts_label)

        conflicts_row = QHBoxLayout()
        self.conflicts_label = QLabel()
        self.resolve_btn = QPushButton("Разобрать")
        self.resolve_btn.clicked.connect(self._resolve_conflicts)
        conflicts_row.addWidget(self.conflicts_label, 1)
        conflicts_row.addWidget(self.resolve_btn)
        self.v.addLayout(conflicts_row)

        self.v.addStretch(1)
        self.write_btn = QPushButton("Записать в Excel")
        self.write_btn.clicked.connect(self._write)
        self.v.addWidget(self.write_btn)

    def _the_date(self):
        return datetime.date.fromisoformat(self.shop_run["the_date"])

    def _own_rows(self):
        items = self.ctx.store.photo_items_all(self.shop_run_id)
        from ..store import DONE_STATUSES
        return {i["row"] for i in items if i["status"] in DONE_STATUSES and i["row"] is not None}

    def _product_name(self, row):
        return str(self.ctx.ws.cell(row, self.ctx.cols["product"]).value or "")

    def _refresh(self):
        items = self.ctx.store.photo_items_all(self.shop_run_id)
        counts = {}
        for i in items:
            counts[i["status"]] = counts.get(i["status"], 0) + 1

        self.title_label.setText(f"{self.shop_run['chain']} · {self.shop_run['shop_name']} · "
                                  f"{self.shop_run['the_date']}")
        self.counts_label.setText(
            f"Обработано фото: {len(items)}\n"
            f"Автоматом: {counts.get('авто', 0)}\n"
            f"Подтверждено вручную: {counts.get('подтверждено', 0)}\n"
            f"Отложено: {counts.get('отложено', 0)}\n"
            f"Ждут проверки: {sum(v for k, v in counts.items() if k not in ('авто', 'подтверждено', 'отложено'))}"
        )

        conflicts = self._current_conflicts()
        if conflicts:
            self.conflicts_label.setText(f"Конфликтов цен: {len(conflicts)}")
            self.resolve_btn.setEnabled(True)
            self.write_btn.setEnabled(False)
        else:
            self.conflicts_label.setText("Конфликтов цен: 0")
            self.resolve_btn.setEnabled(False)
            self.write_btn.setEnabled(True)

    def _current_conflicts(self):
        own_rows = self._own_rows()
        all_conflicts = self.ctx.store.journal_conflicts(self._the_date(), self.shop_run["chain"])
        return [c for c in all_conflicts if c["row"] in own_rows]

    def _resolve_conflicts(self):
        for conflict in self._current_conflicts():
            dlg = ConflictDialog(conflict, self._product_name(conflict["row"]), self)
            if dlg.exec() and dlg.chosen_shop:
                self.ctx.store.journal_resolve_conflict(
                    self._the_date(), conflict["chain"], conflict["row"], dlg.chosen_shop)
        self._refresh()

    def _write(self):
        the_date = self._the_date()
        chain = self.shop_run["chain"]

        pending = self.ctx.store.photo_items_pending_journal(self.shop_run_id)
        for item in pending:
            if item["status"] == "подтверждено":
                price, row, discount = item["confirmed_price"], item["confirmed_row"], item["confirmed_discount"]
            else:
                price, row, discount = item["price"], item["row"], item["discount"]
            self.ctx.store.journal_add(the_date, chain, row, self.shop_run["shop_name"],
                                        price, discount, item["photo"])
            self.ctx.store.photo_item_mark_journaled(item["id"])
        self.ctx.store.shop_remember(self.shop_run["shop_name"], chain, self.shop_run["address"])

        conflicts = self._current_conflicts()
        if conflicts:
            QMessageBox.warning(self, "Есть конфликты",
                                 f"Сначала разберите конфликты ({len(conflicts)}) - запись не выполнена.")
            self._refresh()
            return

        ready = self.ctx.store.journal_for_write(the_date, chain)
        if not ready:
            QMessageBox.information(self, "Нечего записывать", "Нет готовых цен для записи.")
            return
        try:
            col, n = X.write_prices(self.ctx.wb, self.ctx.ws, self.ctx.header_row, self.ctx.cols,
                                     the_date, ready, self.ctx.table_path)
        except PermissionError:
            QMessageBox.critical(self, "Файл занят",
                                  "Не получилось сохранить - похоже, файл таблицы открыт в Excel. "
                                  "Закройте его и попробуйте снова.")
            return
        self.ctx.store.shop_run_set_status(self.shop_run_id, "готово")
        QMessageBox.information(self, "Записано", f"Записано {n} цен в столбец за {the_date:%d.%m.%Y}.")
        self._refresh()

    def closeEvent(self, event):
        if self._on_closed:
            self._on_closed(self.shop_run_id)
        super().closeEvent(event)
