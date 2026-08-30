# -*- coding: utf-8 -*-
"""Работа с таблицей ценового среза.

load_table / build_candidates / get_or_create_date_col перенесены из
excel_tools.py без изменений логики - код рабочий. Остальное - новое:
список сетей из самой таблицы (вместо словаря, который не поспевал за
ней - см. ниже), запись цен, новый месяц, добавление товара.
"""
import datetime, copy, shutil
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import PatternFill
from rapidfuzz import fuzz

DISCOUNT_FILL = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

# Заголовки, которые ищем в строке-шапке. Обязательные - без них дальше
# работать нельзя; необязательные нужны только для add_product_row.
REQUIRED_HEADERS = {"Сеть": "chain", "Производитель": "manuf", "Продукт": "product"}
OPTIONAL_HEADERS = {
    "Торговая марка": "brand", "ТИП": "type_", "СТМ": "stm",
    "Группа": "group_", "Номенклатура ИТОГО:": "formula",
}


def norm(v):
    """Верхний регистр решает разнобой в таблице: 'Ярче'/'ЯРЧЕ'/'Ярче'
    и 'Пятерочка'/'ПяТЕРОЧКА'/'ПЯТЕРОЧКА' после .upper() совпадают -
    Python корректно обрабатывает кириллицу. Отдельная нормализация
    регистра не нужна, только последовательное применение этой функции
    везде, где сравниваются строки из таблицы."""
    return str(v).strip().upper() if v is not None else ""


def load_table(path):
    wb = load_workbook(path)
    ws = wb.active
    header_row = None
    for r in range(1, 15):
        for c in range(1, ws.max_column + 1):
            if str(ws.cell(r, c).value).strip() == "Сеть":
                header_row = r
                break
        if header_row:
            break
    if not header_row:
        raise SystemExit("Не нашёл строку-заголовок со столбцом 'Сеть'.")

    cols, last_date = {}, None
    scan_max = min(ws.max_column, 400)        # реальных столбцов немного; справа бывает «мусор»
    for c in range(1, scan_max + 1):
        h = ws.cell(header_row, c).value
        hs = str(h).strip() if h is not None else ""
        if hs in REQUIRED_HEADERS:
            cols[REQUIRED_HEADERS[hs]] = c
        elif hs in OPTIONAL_HEADERS:
            cols[OPTIONAL_HEADERS[hs]] = c
        elif hs.startswith("Масса"):
            cols["mass"] = c
        if isinstance(h, (datetime.datetime, datetime.date)):
            last_date = c
    cols["last_date"] = last_date
    for need in ("chain", "manuf", "product", "mass"):
        if need not in cols:
            raise SystemExit(f"Не нашёл столбец '{need}'.")
    return wb, ws, header_row, cols


def list_chains(ws, header_row, cols):
    """Все сети, реально встречающиеся в таблице - источник правды для
    выпадающего списка в приложении. Раньше их знал жёстко зашитый
    словарь FOLDER_TO_CHAIN, и он не поспевал за таблицей: SPAR (265
    строк), METRO (84), МАГНИТ (G) (180), ХОРОШИЙ ВЫБОР (228) были
    недоступны. Список из самой таблицы не может устареть."""
    seen = set()
    for r in range(header_row + 1, ws.max_row + 1):
        v = ws.cell(r, cols["chain"]).value
        if v:
            seen.add(norm(v))
    return sorted(seen)


def guess_chain(folder_name, known_chains):
    """Подсказка сети по имени папки - только для удобства заполнения
    поля по умолчанию. Источник истины - выпадающий список из таблицы,
    пользователь всегда может поправить."""
    if not known_chains or not folder_name:
        return None
    name = norm(folder_name)
    best = max(known_chains, key=lambda c: fuzz.ratio(name, c))
    return best if fuzz.ratio(name, best) >= 60 else None


def build_candidates(ws, header_row, cols, chain_canonical):
    out = []
    for r in range(header_row + 1, ws.max_row + 1):
        if norm(ws.cell(r, cols["chain"]).value) != chain_canonical:
            continue
        prod = ws.cell(r, cols["product"]).value
        if prod is None or str(prod).strip() == "":
            continue
        out.append((r, str(prod).strip(),
                    str(ws.cell(r, cols["manuf"]).value or "").strip(),
                    str(ws.cell(r, cols.get("brand", 0)).value or "").strip() if cols.get("brand") else "",
                    ws.cell(r, cols["mass"]).value))
    return out


def get_or_create_date_col(ws, header_row, cols, the_date):
    for c in range(1, min(ws.max_column, 400) + 1):
        h = ws.cell(header_row, c).value
        if isinstance(h, (datetime.datetime, datetime.date)):
            d = h.date() if isinstance(h, datetime.datetime) else h
            if d == the_date:
                return c
    new_col = (cols["last_date"] or cols["mass"]) + 1
    hdr = ws.cell(header_row, new_col,
                  datetime.datetime(the_date.year, the_date.month, the_date.day))
    if cols["last_date"]:
        src = ws.cell(header_row, cols["last_date"])
        hdr.font = copy.copy(src.font); hdr.fill = copy.copy(src.fill)
        hdr.border = copy.copy(src.border); hdr.alignment = copy.copy(src.alignment)
        hdr.number_format = src.number_format
        ws.column_dimensions[get_column_letter(new_col)].width = \
            ws.column_dimensions[get_column_letter(cols["last_date"])].width
    else:
        hdr.number_format = "DD.MM.YYYY"
    cols["last_date"] = new_col
    return new_col


def write_prices(wb, ws, header_row, cols, the_date, matches, table_path):
    """matches: [{"row":.., "price":.., "discount": bool}, ...].
    Пишет прямо в table_path - копий не создаёт (см. CLAUDE.md)."""
    col = get_or_create_date_col(ws, header_row, cols, the_date)
    n = 0
    for m in matches:
        cell = ws.cell(int(m["row"]), col, float(m["price"]))
        if m.get("discount"):
            cell.fill = DISCOUNT_FILL
        n += 1
    wb.save(table_path)
    return col, n


def _copy_cell(src_cell, dst_cell):
    dst_cell.value = src_cell.value
    if src_cell.has_style:
        dst_cell.font = copy.copy(src_cell.font)
        dst_cell.fill = copy.copy(src_cell.fill)
        dst_cell.border = copy.copy(src_cell.border)
        dst_cell.alignment = copy.copy(src_cell.alignment)
        dst_cell.number_format = src_cell.number_format


def new_month(src_path, dst_path):
    """Новый месяц: справочник товаров без цен предыдущих замеров.

    Не копия+delete_cols: у файла раздут max_column (~16000 - похоже на
    случайное форматирование «на весь лист» в Excel), и удаление
    столбцов на такой ширине двигает все строки по всем тысячам колонок
    - на практике не укладывается и в несколько минут (проверено: два
    прогона не завершились). Вместо этого собираем новый лист, копируя
    только реально используемые колонки (1..«Масса (г)») - это отсекает
    и столбцы-даты, и мусорный хвост одним движением, без единого
    delete_cols, и работает за секунды вместо минут. Стили, ширины
    колонок и легенда в строках 1-4 копируются по каждой ячейке, а не
    "приходят бесплатно" вместе с файлом - другого способа обойти
    медленный delete_cols при такой ширине листа нет.
    """
    src_wb, src_ws, header_row, cols = load_table(src_path)
    # ВАЖНО: cols также содержит "last_date" - индекс столбца-даты, то
    # есть ровно то, что нужно исключить. Берём максимум только по
    # структурным колонкам, а не по всем числовым значениям словаря -
    # иначе last_col «случайно» дотягивается до дат и они не отсекаются.
    structure_keys = ("chain", "manuf", "product", "brand", "type_", "stm", "group_", "formula", "mass")
    last_col = max(cols[k] for k in structure_keys if k in cols)

    dst_wb = Workbook()
    dst_wb.remove(dst_wb.active)
    dst_ws = dst_wb.create_sheet(src_ws.title)

    for r in range(1, src_ws.max_row + 1):
        for c in range(1, last_col + 1):
            _copy_cell(src_ws.cell(r, c), dst_ws.cell(r, c))

    for c in range(1, last_col + 1):
        letter = get_column_letter(c)
        if letter in src_ws.column_dimensions:
            dst_ws.column_dimensions[letter].width = src_ws.column_dimensions[letter].width

    dst_wb.save(dst_path)
    return dst_path


def find_similar_products(ws, header_row, cols, chain_canonical, product_text, threshold=80):
    """Проверка на дубликат перед добавлением нового товара.

    Без неё справочник за несколько месяцев зарастает дублями: один и
    тот же товар заводят повторно, потому что fuzzy-поиск в конвейере
    его не нашёл (порог не пройден), а на самом деле строка уже есть.
    """
    out = []
    for row, prod, manuf, brand, mass in build_candidates(ws, header_row, cols, chain_canonical):
        s = fuzz.token_set_ratio(norm(product_text), norm(prod))
        if s >= threshold:
            out.append((s, row, prod, mass))
    return sorted(out, reverse=True)


def add_product_row(ws, header_row, cols, chain, manuf, brand, type_, stm, product, group_, mass):
    """Новая строка товара. Формула в 'Номенклатура ИТОГО' - та же, что
    уже используется в таблице для остальных строк."""
    r = ws.max_row + 1
    ws.cell(r, cols["chain"], chain)
    ws.cell(r, cols["manuf"], manuf)
    if cols.get("brand"):  ws.cell(r, cols["brand"], brand)
    if cols.get("type_"):  ws.cell(r, cols["type_"], type_)
    if cols.get("stm"):    ws.cell(r, cols["stm"], stm)
    ws.cell(r, cols["product"], product)
    if cols.get("formula"):
        # Буквально та же формула, что уже стоит в таблице для остальных
        # строк (=CONCATENATE(F.," ",K.,"г, ",J.,", ",E.," ",C.," (",B.,")"
        # ," ",D.)) - копируем её текст, а не собираем заново по именам
        # столбцов: если когда-нибудь макет таблицы изменится, изменится
        # и сама эта формула в шапке, и её тогда меняют в файле напрямую.
        ws.cell(r, cols["formula"],
                f'=CONCATENATE(F{r}," ",K{r},"г, ",J{r},", ",E{r}," ",C{r}," (",B{r},")"," ",D{r})')
    if cols.get("group_"): ws.cell(r, cols["group_"], group_)
    ws.cell(r, cols["mass"], mass)
    return r
