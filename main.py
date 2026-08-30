# -*- coding: utf-8 -*-
"""Точка входа для PyInstaller.

Для разработки достаточно `python -m price_app.gui` - этот файл нужен
только потому, что PyInstaller собирает exe из файла-скрипта, а не из
модуля."""
from price_app.gui.__main__ import main

if __name__ == "__main__":
    main()
