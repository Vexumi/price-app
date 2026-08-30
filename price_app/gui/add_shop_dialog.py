# -*- coding: utf-8 -*-
"""Диалог «Добавить магазин»: папка + сеть + название + адрес + дата.

Название и адрес запоминаются в store.shops - при вводе начала названия
уже встречавшегося магазина адрес и сеть подставляются сами (100+
магазинов в городе, набирать заново каждый раз мучительно - см. план).
"""
import datetime

from pathlib import Path

from PIL import Image, ExifTags
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QComboBox, QDateEdit,
                                QPushButton, QHBoxLayout, QVBoxLayout, QFileDialog,
                                QCompleter, QLabel, QMessageBox)

from .. import excel_io as X
from ..run import list_photos

_DATE_TAG = next((k for k, v in ExifTags.TAGS.items() if v == "DateTimeOriginal"), 36867)


def _exif_date(folder):
    """Дата съёмки из EXIF первых фото папки - см. план: один замер может
    идти несколько дней, дата должна браться из самой папки, а не задаваться
    одна на всё приложение."""
    for photo in list_photos(folder)[:5]:
        try:
            exif = Image.open(photo).getexif()
            raw = exif.get(_DATE_TAG)
            if raw:
                return datetime.datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").date()
        except Exception:
            continue
    return None


class AddShopDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.result_data = None
        self.setWindowTitle("Добавить магазин")
        self.resize(440, 280)

        self.folder_edit = QLineEdit()
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(browse)

        self.chain_combo = QComboBox()
        self.chain_combo.setEditable(True)
        self.chain_combo.addItems(ctx.chains)

        self.shop_edit = QLineEdit()
        names = [s["name"] for s in ctx.store.shop_suggestions()]
        self.shop_edit.setCompleter(QCompleter(names))
        self.shop_edit.editingFinished.connect(self._autofill_from_history)

        self.address_edit = QLineEdit()

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())

        self.count_label = QLabel("фото: —")

        form = QFormLayout()
        form.addRow("Папка:", folder_row)
        form.addRow("Сеть:", self.chain_combo)
        form.addRow("Магазин:", self.shop_edit)
        form.addRow("Адрес:", self.address_edit)
        form.addRow("Дата:", self.date_edit)
        form.addRow("", self.count_label)

        ok = QPushButton("Добавить")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(btns)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Папка с фото магазина")
        if not d:
            return
        self.folder_edit.setText(d)
        photos = list_photos(d)
        self.count_label.setText(f"фото: {len(photos)}")
        guess = X.guess_chain(Path(d).name, self.ctx.chains)
        if guess:
            self.chain_combo.setCurrentText(guess)
        exif_date = _exif_date(d)
        if exif_date:
            self.date_edit.setDate(QDate(exif_date.year, exif_date.month, exif_date.day))

    def _autofill_from_history(self):
        name = self.shop_edit.text().strip()
        if not name or self.address_edit.text():
            return
        match = next((s for s in self.ctx.store.shop_suggestions(name) if s["name"] == name), None)
        if match:
            self.address_edit.setText(match["address"])
            if match["chain"] in self.ctx.chains:
                self.chain_combo.setCurrentText(match["chain"])

    def _accept(self):
        folder = self.folder_edit.text().strip()
        chain = X.norm(self.chain_combo.currentText().strip())
        shop = self.shop_edit.text().strip()
        address = self.address_edit.text().strip()

        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(self, "Проверьте поля", "Укажите папку с фото.")
            return
        if not list_photos(folder):
            QMessageBox.warning(self, "Проверьте поля", "В папке нет фото (.png/.jpg/.jpeg).")
            return
        if chain not in self.ctx.chains:
            guess = X.guess_chain(chain, self.ctx.chains)
            hint = f"\nПохоже на «{guess}»?" if guess else ""
            QMessageBox.warning(self, "Проверьте поля", f"Сети «{chain}» нет в таблице.{hint}")
            return
        if not shop:
            QMessageBox.warning(self, "Проверьте поля", "Укажите название магазина.")
            return

        self.result_data = {
            "folder": folder, "chain": chain, "shop_name": shop, "address": address,
            "the_date": self.date_edit.date().toPython(),
        }
        self.accept()
