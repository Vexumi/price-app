# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-сборка. Собирается ТОЛЬКО на Windows (windows-latest в
GitHub Actions, см. .github/workflows/build-windows.yml) - PyInstaller
не умеет кросс-компилировать exe с macOS/Linux.

Внутреннее имя приложения латиницей (PriceApp) - чтобы не ловить сюрпризы
кодировки путей у самого PyInstaller/Inno Setup; дружелюбное русское имя
"Ценовой срез" пользователь видит в Inno Setup и в ярлыке (см. setup.iss).
"""
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = []
binaries = []
hiddenimports = []

# rapidocr хранит модели (models/*.onnx) и конфиги (*.yaml) как файлы
# пакета, а не как код - PyInstaller их не подхватывает автоматически.
datas += collect_data_files('rapidocr')

# Только бинарники onnxruntime (.dll грузятся динамически, не через обычный
# import - обычный анализ зависимостей их иногда пропускает). Пакет уже
# несёт свой pyinstaller-hooks-contrib хук для python-модулей - его
# достаточно, поэтому НЕ используем collect_all: он тянет за собой ещё и
# необязательные подмодули onnxruntime (transformers/quantization), а те -
# torch и scipy (300+ МБ лишнего в установщике), которые в рантайме
# конвейера ни разу не используются - RapidOCR ходит только в
# InferenceSession).
binaries += collect_dynamic_libs('onnxruntime')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Защита от раздувания установщика: ни один из этих пакетов не
    # используется в price_app, но torch/scipy оказались установлены в
    # окружении как чей-то необязательный экстра и без explicit excludes
    # PyInstaller их всё равно утаскивает в сборку через хуки onnxruntime.
    excludes=['torch', 'scipy', 'tensorboard', 'matplotlib'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PriceApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True временно помогает при отладке падений на чистой машине -
    # тогда видно traceback вместо молчаливого закрытия окна.
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PriceApp',
)
