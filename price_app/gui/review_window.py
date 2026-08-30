# -*- coding: utf-8 -*-
"""Экран 3 «Конвейер проверки» - основной экран работы.

Показываются только спорные фото (см. store.REVIEW_STATUSES) - то, что
распозналось уверенно («авто»), проходит мимо и сразу готово к записи.
Работа рассчитана на клавиатуру: Enter подтверждает, 1-5 выбирают
кандидата, Ctrl+Z отменяет последнее подтверждение (без неё ритм
Enter-Enter-Enter рано или поздно уедет в Excel молча - см. план).
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                QPushButton, QLineEdit, QListWidget, QListWidgetItem,
                                QCheckBox, QMessageBox, QSplitter)

from .photo_view import PhotoView
from .new_item_dialog import NewItemDialog


class ReviewWindow(QMainWindow):
    def __init__(self, ctx, shop_run_id, on_closed=None, on_go_summary=None):
        super().__init__()
        self.ctx = ctx
        self.shop_run_id = shop_run_id
        self.shop_run = ctx.store.shop_run_get(shop_run_id)
        self._on_closed = on_closed
        self._on_go_summary = on_go_summary

        self.items = ctx.store.photo_items_for_review(shop_run_id)
        self.pos = 0
        self.undo_stack = []   # [(item_id, снятый_с_очереди_на_позиции), ...]
        self._transitioning = False

        self.setWindowTitle(f"Проверка · {self.shop_run['chain']} · {self.shop_run['shop_name']}")
        self.resize(980, 620)
        self._build_ui()
        self._render()

    # --- сборка интерфейса -------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.progress_label = QLabel()
        root.addWidget(self.progress_label)

        split = QSplitter()
        root.addWidget(split, 1)

        self.photo = PhotoView()
        split.addWidget(self.photo)

        right = QWidget()
        rv = QVBoxLayout(right)

        rv.addWidget(QLabel("Цена:"))
        price_row = QHBoxLayout()
        self.price_edit = QLineEdit()
        self.discount_check = QCheckBox("Акция (жёлтым)")
        price_row.addWidget(self.price_edit)
        price_row.addWidget(self.discount_check)
        rv.addLayout(price_row)

        self.why_label = QLabel()
        self.why_label.setWordWrap(True)
        self.why_label.setStyleSheet("color:#a55;")
        rv.addWidget(self.why_label)

        rv.addWidget(QLabel("Товар (Enter подтверждает выбранный, 1-5 - выбрать):"))
        self.candidates_list = QListWidget()
        rv.addWidget(self.candidates_list, 1)

        self.ocr_label = QLabel()
        self.ocr_label.setWordWrap(True)
        self.ocr_label.setStyleSheet("color:#666; font-size:11px;")
        rv.addWidget(self.ocr_label)

        confirm_btn = QPushButton("✓ Да, верно  (Enter)")
        confirm_btn.clicked.connect(self._confirm)
        rv.addWidget(confirm_btn)

        row2 = QHBoxLayout()
        no_match_btn = QPushButton("Нет в списке")
        no_match_btn.clicked.connect(self._no_match)
        skip_btn = QPushButton("Отложить")
        skip_btn.clicked.connect(self._skip)
        row2.addWidget(no_match_btn)
        row2.addWidget(skip_btn)
        rv.addLayout(row2)

        nav_row = QHBoxLayout()
        prev_btn = QPushButton("← Предыдущее")
        prev_btn.clicked.connect(lambda: self._navigate(-1))
        next_btn = QPushButton("Следующее →")
        next_btn.clicked.connect(lambda: self._navigate(1))
        nav_row.addWidget(prev_btn)
        nav_row.addWidget(next_btn)
        rv.addLayout(nav_row)

        undo_btn = QPushButton("Ctrl+Z — отменить предыдущее")
        undo_btn.clicked.connect(self._undo)
        rv.addWidget(undo_btn)

        split.addWidget(right)
        split.setSizes([560, 400])

        # Enter подтверждает всегда - в поле цены он не нужен ни для чего
        # своего, конфликта нет. Esc закрывает окно (прогресс сохранён).
        QShortcut(QKeySequence(Qt.Key.Key_Return), self, activated=self._confirm)
        QShortcut(QKeySequence(Qt.Key.Key_Enter), self, activated=self._confirm)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)

        # Цифры 1-5, стрелки и Ctrl+Z привязаны к списку кандидатов
        # (WidgetShortcut), а не ко всему окну - иначе они перехватывали
        # бы ввод в поле цены (нельзя было бы набрать цифру рукой или
        # подвигать курсор стрелками при правке).
        for n in range(1, 6):
            sc = QShortcut(QKeySequence(str(n)), self.candidates_list)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(lambda n=n: self._select_candidate(n - 1))
        left_sc = QShortcut(QKeySequence(Qt.Key.Key_Left), self.candidates_list)
        left_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        left_sc.activated.connect(lambda: self._navigate(-1))
        right_sc = QShortcut(QKeySequence(Qt.Key.Key_Right), self.candidates_list)
        right_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        right_sc.activated.connect(lambda: self._navigate(1))
        undo_sc = QShortcut(QKeySequence("Ctrl+Z"), self.candidates_list)
        undo_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        undo_sc.activated.connect(self._undo)
        # Тот же Ctrl+Z ещё и глобально в окне - QLineEdit сам обрабатывает
        # Ctrl+Z как отмену правки текста, поэтому в поле цены остаётся
        # родное поведение, а кнопка "Ctrl+Z" всегда работает как запасной
        # путь независимо от фокуса.

    # --- отрисовка текущего элемента ---------------------------------------

    def _current(self):
        if 0 <= self.pos < len(self.items):
            return self.items[self.pos]
        return None

    def _render(self):
        item = self._current()
        if item is None:
            self._render_done()
            return

        left = len(self.items) - self.pos
        self.progress_label.setText(f"Осталось {left} из {len(self.items)}          "
                                     f"{self.shop_run['chain']} · {self.shop_run['shop_name']}")
        self.photo.set_photo(item["photo"], item["price_bbox"], item["img_w"], item["img_h"])
        self.price_edit.setText(f'{item["price"]:.2f}' if item["price"] is not None else "")
        self.discount_check.setChecked(bool(item["discount"]))
        self.why_label.setText(f'{item["status"]}: {item["why"]}' if item["why"] else item["status"])
        self.ocr_label.setText(f'OCR: «{item["text"]}»')

        self.candidates_list.clear()
        for i, (score, row, prod, mass) in enumerate(item["candidates"][:5], 1):
            mass_s = f"{mass} г" if mass else "?"
            self.candidates_list.addItem(QListWidgetItem(f"{i}  {score:5.1f}  {prod}  ({mass_s})"))
        if item["row"] is not None:
            for i, (score, row, prod, mass) in enumerate(item["candidates"][:5]):
                if row == item["row"]:
                    self.candidates_list.setCurrentRow(i)
                    break
            else:
                self.candidates_list.setCurrentRow(0) if item["candidates"] else None
        elif item["candidates"]:
            self.candidates_list.setCurrentRow(0)

        if item["price"] is None:
            self.price_edit.setFocus()
        else:
            self.candidates_list.setFocus()

    def _render_done(self):
        central = QWidget()
        v = QVBoxLayout(central)
        v.addStretch(1)
        label = QLabel("Все фото проверены!")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size:18px;")
        v.addWidget(label)
        go_btn = QPushButton("Перейти к итогу магазина →")
        go_btn.clicked.connect(self._go_summary)
        v.addWidget(go_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        v.addStretch(1)
        self.setCentralWidget(central)

    # --- выбранная строка кандидата -----------------------------------------

    def _selected_candidate(self):
        item = self._current()
        i = self.candidates_list.currentRow()
        if item and 0 <= i < len(item["candidates"]):
            _, row, prod, _ = item["candidates"][i]
            return row, prod
        return None, None

    def _select_candidate(self, idx):
        if 0 <= idx < self.candidates_list.count():
            self.candidates_list.setCurrentRow(idx)

    # --- действия -------------------------------------------------------------

    def _parse_price(self):
        txt = self.price_edit.text().strip().replace(",", ".")
        if not txt:
            return None
        try:
            return round(float(txt), 2)
        except ValueError:
            return None

    def _confirm(self):
        item = self._current()
        if item is None:
            return
        price = self._parse_price()
        if price is None:
            QMessageBox.warning(self, "Нет цены", "Укажите цену перед подтверждением.")
            self.price_edit.setFocus()
            return
        row, product = self._selected_candidate()
        if row is None:
            QMessageBox.warning(self, "Нет товара", 'Выберите товар из списка или нажмите «Нет в списке».')
            return
        discount = self.discount_check.isChecked()

        self.ctx.store.photo_item_set(item["id"], "подтверждено", price=price, row=row, discount=discount)
        if item["text"]:
            self.ctx.store.cache_put(self.shop_run["chain"], self._norm_text(item["text"]), row)

        self._consume_current(item["id"])

    def _no_match(self):
        item = self._current()
        if item is None:
            return
        dlg = NewItemDialog(self.ctx, self.shop_run["chain"], item, self)
        if dlg.exec() and dlg.result_data:
            row, product = dlg.result_data["row"], dlg.result_data["product"]
            item["row"], item["product"] = row, product
            item["candidates"] = [(100, row, product, None)] + item["candidates"]
            self._render()

    def _skip(self):
        item = self._current()
        if item is None:
            return
        self.ctx.store.photo_item_set(item["id"], "отложено")
        self._consume_current(item["id"])

    def _consume_current(self, item_id):
        self.undo_stack.append((item_id, self.pos))
        del self.items[self.pos]
        if self.pos >= len(self.items):
            self.pos = max(0, len(self.items) - 1)
        self._render()

    def _undo(self):
        if not self.undo_stack:
            return
        item_id, pos = self.undo_stack.pop()
        item = self.ctx.store.photo_item_get(item_id)
        # Возвращаем элемент к состоянию «на проверку», отменяя решение
        # человека - точный исходный статус (нужен товар/нужна цена/...)
        # запоминать не обязательно: попадание обратно в общий список
        # проверки достаточно, дальше решает человек ещё раз.
        from ..store import REVIEW_STATUSES
        restored_status = item["status"] if item["status"] in REVIEW_STATUSES else "на проверку"
        self.ctx.store.photo_item_set(item_id, restored_status)
        item = self.ctx.store.photo_item_get(item_id)
        self.items.insert(pos, item)
        self.pos = pos
        self._render()

    def _navigate(self, delta):
        new_pos = self.pos + delta
        if 0 <= new_pos < len(self.items):
            self.pos = new_pos
            self._render()

    @staticmethod
    def _norm_text(text):
        # Тот же fingerprint, что использует pipeline.process_photo
        # (fp = M.norm(text)) - иначе подтверждённое здесь не найдётся
        # кэшем на следующем фото с тем же товаром.
        from .. import match as M
        return M.norm(text)

    def _go_summary(self):
        # Флаг нужен, чтобы closeEvent ниже не вызвал _on_closed поверх
        # уже открытого SummaryWindow - иначе он тут же затирает в
        # MainWindow._open_children свежую ссылку на SummaryWindow, и окно
        # итога остаётся без единого владельца (рискует быть собранным GC).
        self._transitioning = True
        if self._on_go_summary:
            self._on_go_summary(self.shop_run_id)
        self.close()

    def closeEvent(self, event):
        if self._on_closed and not self._transitioning:
            self._on_closed(self.shop_run_id)
        super().closeEvent(event)
