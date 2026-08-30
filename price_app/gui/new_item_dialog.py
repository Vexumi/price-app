# -*- coding: utf-8 -*-
"""Диалог «Нет в списке»: два способа закрыть товар, которого не нашёл
автоматический матчинг.

- «Найти вручную» - для случая, когда товар в таблице есть, а OCR или
  fuzzy-порог просто промахнулись.
- «Завести новый товар» - для настоящей новинки; перед сохранением ищет
  похожие строки и предупреждает, чтобы не плодить дубли (см. план,
  find_similar_products)."""
from PySide6.QtWidgets import (QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
                                QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                                QFormLayout, QMessageBox)

from .. import excel_io as X
from .. import match as M


class NewItemDialog(QDialog):
    def __init__(self, ctx, chain, item, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.chain = chain
        self.item = item
        self.result_data = None
        self.setWindowTitle("Нет в списке")
        self.resize(480, 420)

        tabs = QTabWidget()
        tabs.addTab(self._build_search_tab(), "Найти вручную")
        tabs.addTab(self._build_new_tab(), "Завести новый товар")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

    # --- вкладка «Найти вручную» -----------------------------------------

    def _build_search_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        self.search_edit = QLineEdit(self.item.get("text", "") or "")
        self.search_list = QListWidget()
        self._search_rows = []
        self.search_edit.textChanged.connect(self._do_search)

        pick_btn = QPushButton("Выбрать эту строку")
        pick_btn.clicked.connect(self._pick_search)

        v.addWidget(self.search_edit)
        v.addWidget(self.search_list, 1)
        v.addWidget(pick_btn)
        self._do_search(self.search_edit.text())
        return w

    def _do_search(self, text):
        self.search_list.clear()
        self._search_rows = X.find_similar_products(
            self.ctx.ws, self.ctx.header_row, self.ctx.cols, self.chain, text, threshold=55)
        for score, row, prod, mass in self._search_rows[:30]:
            self.search_list.addItem(QListWidgetItem(f"{score:5.1f}  [{row}]  {prod}  ({mass} г)"))

    def _pick_search(self):
        i = self.search_list.currentRow()
        if i < 0 or i >= len(self._search_rows):
            QMessageBox.information(self, "Нет выбора", "Выберите строку в списке.")
            return
        _, row, prod, _ = self._search_rows[i]
        self.result_data = {"row": row, "product": prod}
        self.accept()

    # --- вкладка «Завести новый товар» ------------------------------------

    def _build_new_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        guess_mass = M.mass_of(self.item.get("text", "") or "") or ""
        self.f_manuf = QLineEdit()
        self.f_brand = QLineEdit()
        self.f_type = QLineEdit()
        self.f_stm = QLineEdit()
        self.f_product = QLineEdit(self.item.get("text", "") or "")
        self.f_group = QLineEdit()
        self.f_mass = QLineEdit(str(guess_mass))

        form = QFormLayout()
        form.addRow("Производитель:", self.f_manuf)
        form.addRow("Торговая марка:", self.f_brand)
        form.addRow("ТИП:", self.f_type)
        form.addRow("СТМ:", self.f_stm)
        form.addRow("Продукт:", self.f_product)
        form.addRow("Группа:", self.f_group)
        form.addRow("Масса (г):", self.f_mass)

        add_btn = QPushButton("Завести и выбрать")
        add_btn.clicked.connect(self._add_new)

        v.addLayout(form)
        v.addWidget(add_btn)
        v.addStretch(1)
        return w

    def _add_new(self):
        product = self.f_product.text().strip()
        if not product:
            QMessageBox.warning(self, "Проверьте поля", "Укажите название продукта.")
            return
        try:
            mass = int(self.f_mass.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Проверьте поля", "Масса должна быть числом (граммы).")
            return

        similar = X.find_similar_products(self.ctx.ws, self.ctx.header_row, self.ctx.cols,
                                           self.chain, product, threshold=80)
        if similar:
            score, row, prod, m = similar[0]
            reply = QMessageBox.question(
                self, "Похоже, уже есть",
                f"Похожая строка уже есть в таблице:\n«{prod}» ({m} г), строка {row}, "
                f"схожесть {score:.0f}.\n\nВсё равно завести новую?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        row = X.add_product_row(
            self.ctx.ws, self.ctx.header_row, self.ctx.cols,
            chain=self.chain, manuf=self.f_manuf.text().strip(),
            brand=self.f_brand.text().strip(), type_=self.f_type.text().strip(),
            stm=self.f_stm.text().strip(), product=product,
            group_=self.f_group.text().strip(), mass=mass)
        self.ctx.wb.save(self.ctx.table_path)

        self.result_data = {"row": row, "product": product}
        self.accept()
