# -*- coding: utf-8 -*-
"""Разрешение конфликта: два (или больше) магазина одной сети за одну
дату дали разные цены на один товар (см. план, раздел «Конфликты ловятся
на уровне ячейки»). Выбор всегда за человеком - тихого решения нет."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                QGroupBox, QWidget)

from .photo_view import PhotoView


class ConflictDialog(QDialog):
    def __init__(self, conflict, product_name, parent=None):
        """conflict: {"chain","row","entries":[{"shop_name","price","photo"}, ...]}."""
        super().__init__(parent)
        self.conflict = conflict
        self.chosen_shop = None
        self.setWindowTitle(f"Конфликт: {product_name} · {conflict['chain']}")
        self.resize(760, 420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Строка {conflict['row']} · «{product_name}» - "
                                 f"разные цены за одну дату:"))

        row = QHBoxLayout()
        for entry in conflict["entries"]:
            box = QGroupBox(entry["shop_name"])
            v = QVBoxLayout(box)
            photo = PhotoView()
            if entry.get("photo"):
                photo.set_photo(entry["photo"])
            photo.setMinimumSize(260, 200)
            v.addWidget(photo)
            v.addWidget(QLabel(f'{entry["price"]:.2f} ₽'))
            pick = QPushButton(f'Оставить «{entry["shop_name"]}»')
            pick.clicked.connect(lambda _, s=entry["shop_name"]: self._pick(s))
            v.addWidget(pick)
            row.addWidget(box)
        layout.addLayout(row)

    def _pick(self, shop_name):
        self.chosen_shop = shop_name
        self.accept()
