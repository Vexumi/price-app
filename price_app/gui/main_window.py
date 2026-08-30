# -*- coding: utf-8 -*-
"""Экран 1 «Замер» - список магазинов (паков) в работе, запуск обработки.

Обработка не блокирует проверку: как только один магазин посчитался,
по нему можно открывать конвейер, пока остальные ещё в очереди (см. план).
"""
from pathlib import Path

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
                                QMessageBox, QHeaderView, QProgressBar)

from .. import excel_io as X
from ..run import list_photos
from .context import AppContext
from .add_shop_dialog import AddShopDialog
from .processing import ProcessingThread
from .review_window import ReviewWindow
from .summary_window import SummaryWindow

STATUS_LABELS = {
    "очередь": "○ в очереди",
    "обработка": "● обрабатывается",
    "проверка": "● на проверке",
    "готово": "✓ готово",
}


class MainWindow(QMainWindow):
    def __init__(self, table_path):
        super().__init__()
        self.setWindowTitle("Ценовой срез")
        self.resize(860, 520)

        self.ctx = AppContext(table_path)
        self._queue = []
        self._current_thread = None
        self._open_children = {}   # shop_run_id -> открытое окно проверки/итога
        self._runs_by_row = []

        self._build_ui()
        self._refresh_table()

    # --- сборка интерфейса --------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        file_row = QHBoxLayout()
        self.file_label = QLabel()
        self._update_file_label()
        change_btn = QPushButton("Изменить…")
        change_btn.clicked.connect(self._change_table)
        new_month_btn = QPushButton("Создать новый месяц")
        new_month_btn.clicked.connect(self._new_month)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(change_btn)
        file_row.addWidget(new_month_btn)
        layout.addLayout(file_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Сеть", "Магазин", "Дата", "Фото", "Статус"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self.table)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Добавить")
        add_btn.clicked.connect(self._add_shop)
        open_btn = QPushButton("Открыть")
        open_btn.clicked.connect(self._open_selected)
        self.process_btn = QPushButton("Обработать всё")
        self.process_btn.clicked.connect(self._process_all)
        btn_row.addWidget(add_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(self.process_btn)
        layout.addLayout(btn_row)

        self.statusBar()

    # --- файл таблицы -----------------------------------------------------

    def _update_file_label(self):
        self.file_label.setText(f"Файл: {Path(self.ctx.table_path).name}")

    def _change_table(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать таблицу", "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            self.ctx = AppContext(path)
        except SystemExit as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return
        self._update_file_label()
        self._refresh_table()

    def _new_month(self):
        dst, _ = QFileDialog.getSaveFileName(self, "Файл нового месяца", "", "Excel (*.xlsx)")
        if not dst:
            return
        try:
            X.new_month(self.ctx.table_path, dst)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не получилось создать новый месяц:\n{e}")
            return
        reply = QMessageBox.question(self, "Готово", "Новый месяц создан. Открыть его?")
        if reply == QMessageBox.StandardButton.Yes:
            self.ctx = AppContext(dst)
            self._update_file_label()
            self._refresh_table()

    # --- список магазинов ---------------------------------------------------

    def _refresh_table(self):
        runs = self.ctx.store.shop_run_list()
        self._runs_by_row = runs
        self.table.setRowCount(len(runs))
        for i, r in enumerate(runs):
            n_photos = sum(r["counts"].values())
            addr = f'{r["shop_name"]} · {r["address"]}' if r["address"] else r["shop_name"]
            self.table.setItem(i, 0, QTableWidgetItem(r["chain"]))
            self.table.setItem(i, 1, QTableWidgetItem(addr))
            self.table.setItem(i, 2, QTableWidgetItem(r["the_date"]))
            self.table.setItem(i, 3, QTableWidgetItem(str(n_photos) if n_photos else "—"))
            self.table.setItem(i, 4, QTableWidgetItem(STATUS_LABELS.get(r["status"], r["status"])))

    def _add_shop(self):
        dlg = AddShopDialog(self.ctx, self)
        if dlg.exec() and dlg.result_data:
            d = dlg.result_data
            self.ctx.store.shop_run_create(d["folder"], d["chain"], d["shop_name"],
                                            d["address"], d["the_date"], self.ctx.table_path)
            self.ctx.store.shop_remember(d["shop_name"], d["chain"], d["address"])
            self._refresh_table()

    # --- обработка ------------------------------------------------------------

    def _process_all(self):
        runs = [r for r in self.ctx.store.shop_run_list() if r["status"] == "очередь"]
        if not runs:
            QMessageBox.information(self, "Обработка", "Нет магазинов в очереди.")
            return
        self._queue = [r["id"] for r in runs]
        self.process_btn.setEnabled(False)
        self.progress.setVisible(True)
        self._start_next()

    def _start_next(self):
        if not self._queue:
            self.progress.setVisible(False)
            self.process_btn.setEnabled(True)
            self.statusBar().showMessage("Обработка завершена", 5000)
            self._refresh_table()
            return
        shop_run_id = self._queue.pop(0)
        shop_run = self.ctx.store.shop_run_get(shop_run_id)
        self.ctx.store.shop_run_set_status(shop_run_id, "обработка")
        self._refresh_table()

        photos = list_photos(shop_run["folder"])
        self.progress.setRange(0, max(len(photos), 1))
        self.progress.setValue(0)
        self.statusBar().showMessage(f"Загружаю модель распознавания… ({shop_run['shop_name']})")

        self._current_thread = ProcessingThread(self.ctx, shop_run, photos)
        self._current_thread.progress.connect(self._on_progress)
        self._current_thread.finished_run.connect(self._on_run_finished)
        self._current_thread.failed.connect(self._on_run_failed)
        self._current_thread.start()

    def _on_progress(self, done, total, name):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.statusBar().showMessage(f"{done}/{total}  {name}")

    def _on_run_finished(self, shop_run_id, results):
        self.ctx.store.photo_items_bulk_insert(shop_run_id, results)
        self.ctx.store.shop_run_set_status(shop_run_id, "проверка")
        self._refresh_table()
        self._start_next()

    def _on_run_failed(self, shop_run_id, message):
        QMessageBox.critical(self, "Ошибка обработки", message)
        self.ctx.store.shop_run_set_status(shop_run_id, "очередь")
        self._refresh_table()
        self._start_next()

    # --- открыть проверку / итог ------------------------------------------

    def _open_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._runs_by_row):
            return
        run = self._runs_by_row[row]
        if run["status"] in ("очередь", "обработка"):
            QMessageBox.information(self, "Ещё не готово", "Этот магазин ещё не обработан.")
            return
        self._open_run(run["id"])

    def _open_run(self, shop_run_id):
        existing = self._open_children.get(shop_run_id)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        review_left = self.ctx.store.photo_items_for_review(shop_run_id)
        if review_left:
            win = ReviewWindow(self.ctx, shop_run_id, on_closed=self._on_child_closed,
                                on_go_summary=self._open_summary)
        else:
            win = SummaryWindow(self.ctx, shop_run_id, on_closed=self._on_child_closed)
        self._open_children[shop_run_id] = win
        win.show()

    def _open_summary(self, shop_run_id):
        self._open_children.pop(shop_run_id, None)
        win = SummaryWindow(self.ctx, shop_run_id, on_closed=self._on_child_closed)
        self._open_children[shop_run_id] = win
        win.show()

    def _on_child_closed(self, shop_run_id):
        self._open_children.pop(shop_run_id, None)
        self._refresh_table()
