# -*- coding: utf-8 -*-
"""python -m price_app.gui [путь_к_таблице.xlsx]

Без аргумента ищет "итоговый ценовой срез(АВГУСТ).xlsx" в текущей папке,
иначе просит выбрать файл."""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

DEFAULT_TABLE = "итоговый ценовой срез(АВГУСТ).xlsx"


def _pick_table(app):
    if len(sys.argv) > 1:
        return sys.argv[1]
    if Path(DEFAULT_TABLE).exists():
        return DEFAULT_TABLE
    path, _ = QFileDialog.getOpenFileName(None, "Выбрать таблицу ценового среза", "", "Excel (*.xlsx)")
    return path or None


def main():
    app = QApplication(sys.argv)
    table_path = _pick_table(app)
    if not table_path:
        return

    from .main_window import MainWindow
    try:
        window = MainWindow(table_path)
    except SystemExit as e:
        QMessageBox.critical(None, "Не получилось открыть таблицу", str(e))
        return
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
