# -*- coding: utf-8 -*-
"""Показ фото ценника с рамкой поверх найденной цены.

Рамка рисуется бесплатно - координаты уже приходят из OCR (см.
pipeline.extract_price_refined -> price_bbox), просто масштабируются под
размер виджета.
"""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget


class PhotoView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 280)
        self._pixmap = None
        self._bbox = None
        self._img_size = None

    def set_photo(self, path, bbox=None, img_w=None, img_h=None):
        self._pixmap = QPixmap(str(path))
        self._bbox = bbox
        if self._pixmap.isNull():
            self._img_size = None
        else:
            self._img_size = (img_w or self._pixmap.width(), img_h or self._pixmap.height())
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#202020"))
        if self._pixmap is None or self._pixmap.isNull():
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "нет фото")
            return

        scaled = self._pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
        ox = (self.width() - scaled.width()) / 2
        oy = (self.height() - scaled.height()) / 2
        p.drawPixmap(int(ox), int(oy), scaled)

        if self._bbox and self._img_size and self._img_size[0]:
            sx = scaled.width() / self._img_size[0]
            sy = scaled.height() / self._img_size[1]
            r = QRectF(ox + self._bbox["x0"] * sx, oy + self._bbox["y0"] * sy,
                       (self._bbox["x1"] - self._bbox["x0"]) * sx,
                       (self._bbox["y1"] - self._bbox["y0"]) * sy)
            p.setPen(QPen(QColor("#ff3b30"), 3))
            p.drawRect(r)
