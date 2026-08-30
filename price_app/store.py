# -*- coding: utf-8 -*-
"""SQLite-хранилище приложения: кэш узнанных товаров, журнал цен по
магазинам (для отлова конфликтов между магазинами одной сети) и история
цен по конкретному магазину (для проверки на правдоподобие).

Всё состояние живёт здесь, а не в оперативной памяти - закрыла программу
посреди конвейера, открыла и продолжила с того же места (см. план,
раздел «Сохранение сессии»).
"""
import sqlite3
import datetime as dt
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    chain TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    row INTEGER NOT NULL,
    hits INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (chain, fingerprint)
);

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    the_date TEXT NOT NULL,
    chain TEXT NOT NULL,
    row INTEGER NOT NULL,
    shop_name TEXT NOT NULL,
    price REAL NOT NULL,
    discount INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'подтверждено',
    photo TEXT
);
CREATE INDEX IF NOT EXISTS idx_journal_slot ON journal (the_date, chain, row);

CREATE TABLE IF NOT EXISTS shops (
    name TEXT PRIMARY KEY,
    chain TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS shop_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder TEXT NOT NULL,
    chain TEXT NOT NULL,
    shop_name TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    the_date TEXT NOT NULL,
    table_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'очередь',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photo_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_run_id INTEGER NOT NULL,
    order_idx INTEGER NOT NULL,
    photo TEXT NOT NULL,
    price REAL,
    discount INTEGER NOT NULL DEFAULT 0,
    row INTEGER,
    product TEXT,
    text TEXT,
    candidates_json TEXT,
    meta_json TEXT,
    why TEXT,
    status TEXT NOT NULL,
    confirmed_price REAL,
    confirmed_row INTEGER,
    confirmed_discount INTEGER NOT NULL DEFAULT 0,
    journaled INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_run ON photo_items (shop_run_id, order_idx);
"""

# Статусы photo_items, с которыми элемент ещё не готов к записи в Excel -
# то есть должен показываться в конвейере проверки (Экран 3).
REVIEW_STATUSES = ("нужен товар", "нужна цена", "на проверку", "подозрительная цена")
# Финальные статусы, готовые к записи (либо решённые вручную).
DONE_STATUSES = ("авто", "подтверждено")


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --- кэш: сеть+отпечаток товара -> строка таблицы -----------------

    def cache_get(self, chain, fingerprint):
        row = self.conn.execute(
            "SELECT row FROM cache WHERE chain=? AND fingerprint=?",
            (chain, fingerprint)).fetchone()
        return row[0] if row else None

    def cache_put(self, chain, fingerprint, row):
        self.conn.execute(
            """INSERT INTO cache (chain, fingerprint, row, hits) VALUES (?,?,?,1)
               ON CONFLICT(chain, fingerprint) DO UPDATE SET
                   hits = hits + 1, row = excluded.row""",
            (chain, fingerprint, row))
        self.conn.commit()

    # --- журнал: дата+сеть+строка+магазин+цена -------------------------

    def journal_add(self, the_date, chain, row, shop_name, price, discount=False, photo=None):
        self.conn.execute(
            """INSERT INTO journal (the_date, chain, row, shop_name, price, discount, photo)
               VALUES (?,?,?,?,?,?,?)""",
            (the_date.isoformat(), chain, row, shop_name, price, int(discount), photo))
        self.conn.commit()

    def journal_conflicts(self, the_date, chain=None):
        """Строки, куда за эту дату разные магазины вписали разные цены."""
        q = """SELECT chain, row, COUNT(DISTINCT price) c
               FROM journal WHERE the_date=? {chain_filter}
               GROUP BY chain, row HAVING c > 1"""
        params = [the_date.isoformat()]
        chain_filter = ""
        if chain:
            chain_filter = "AND chain=?"
            params.append(chain)
        rows = self.conn.execute(q.format(chain_filter=chain_filter), params).fetchall()
        out = []
        for c, row, _ in rows:
            entries = self.conn.execute(
                """SELECT shop_name, price, photo FROM journal
                   WHERE the_date=? AND chain=? AND row=?""",
                (the_date.isoformat(), c, row)).fetchall()
            out.append({"chain": c, "row": row,
                        "entries": [{"shop_name": s, "price": p, "photo": ph} for s, p, ph in entries]})
        return out

    def journal_resolve_conflict(self, the_date, chain, row, keep_shop_name):
        """Оставить только запись выбранного магазина, остальные - удалить."""
        self.conn.execute(
            """DELETE FROM journal WHERE the_date=? AND chain=? AND row=? AND shop_name<>?""",
            (the_date.isoformat(), chain, row, keep_shop_name))
        self.conn.commit()

    def journal_for_write(self, the_date, chain=None):
        """Записи без конфликтов, готовые уйти в Excel одним пакетом."""
        q = """SELECT row, price, discount FROM journal j
               WHERE the_date=? {chain_filter}
               AND (SELECT COUNT(DISTINCT price) FROM journal j2
                    WHERE j2.the_date=j.the_date AND j2.chain=j.chain AND j2.row=j.row) = 1"""
        params = [the_date.isoformat()]
        chain_filter = ""
        if chain:
            chain_filter = "AND chain=?"
            params.append(chain)
        rows = self.conn.execute(q.format(chain_filter=chain_filter), params).fetchall()
        return [{"row": r, "price": p, "discount": bool(d)} for r, p, d in rows]

    # --- история цен по магазину: проверка на правдоподобие ------------

    def price_history(self, chain, row, shop_name, limit=5):
        rows = self.conn.execute(
            """SELECT the_date, price FROM journal
               WHERE chain=? AND row=? AND shop_name=?
               ORDER BY the_date DESC LIMIT ?""",
            (chain, row, shop_name, limit)).fetchall()
        return [{"date": d, "price": p} for d, p in rows]

    # --- магазины: запоминаем название+адрес для автоподстановки -------

    def shop_remember(self, name, chain, address):
        self.conn.execute(
            """INSERT INTO shops (name, chain, address) VALUES (?,?,?)
               ON CONFLICT(name) DO UPDATE SET chain=excluded.chain, address=excluded.address""",
            (name, chain, address))
        self.conn.commit()

    def shop_suggestions(self, prefix=""):
        rows = self.conn.execute(
            "SELECT name, chain, address FROM shops WHERE name LIKE ? ORDER BY name",
            (f"{prefix}%",)).fetchall()
        return [{"name": n, "chain": c, "address": a} for n, c, a in rows]

    def close(self):
        self.conn.close()

    # --- паки магазинов и фото-элементы (состояние GUI-сессии) ---------

    def shop_run_create(self, folder, chain, shop_name, address, the_date, table_path):
        cur = self.conn.execute(
            """INSERT INTO shop_runs (folder, chain, shop_name, address, the_date,
                                       table_path, status, created_at)
               VALUES (?,?,?,?,?,?, 'очередь', ?)""",
            (str(folder), chain, shop_name, address, the_date.isoformat(),
             str(table_path), dt.datetime.now().isoformat()))
        self.conn.commit()
        return cur.lastrowid

    def shop_run_list(self):
        rows = self.conn.execute(
            """SELECT id, folder, chain, shop_name, address, the_date, table_path, status
               FROM shop_runs ORDER BY id""").fetchall()
        out = []
        for (sid, folder, chain, shop_name, address, the_date, table_path, status) in rows:
            out.append({"id": sid, "folder": folder, "chain": chain, "shop_name": shop_name,
                        "address": address, "the_date": the_date, "table_path": table_path,
                        "status": status, "counts": self.shop_run_counts(sid)})
        return out

    def shop_run_get(self, shop_run_id):
        row = self.conn.execute(
            """SELECT id, folder, chain, shop_name, address, the_date, table_path, status
               FROM shop_runs WHERE id=?""", (shop_run_id,)).fetchone()
        if not row:
            return None
        sid, folder, chain, shop_name, address, the_date, table_path, status = row
        return {"id": sid, "folder": folder, "chain": chain, "shop_name": shop_name,
                "address": address, "the_date": the_date, "table_path": table_path,
                "status": status}

    def shop_run_set_status(self, shop_run_id, status):
        self.conn.execute("UPDATE shop_runs SET status=? WHERE id=?", (status, shop_run_id))
        self.conn.commit()

    def shop_run_counts(self, shop_run_id):
        rows = self.conn.execute(
            "SELECT status, COUNT(*) FROM photo_items WHERE shop_run_id=? GROUP BY status",
            (shop_run_id,)).fetchall()
        return {status: n for status, n in rows}

    _ITEM_COLS = ("id, shop_run_id, order_idx, photo, price, discount, row, product, text, "
                  "candidates_json, meta_json, why, status, confirmed_price, confirmed_row, "
                  "confirmed_discount, journaled")

    def photo_items_bulk_insert(self, shop_run_id, results):
        """results: список из pipeline.process_photo(), в порядке фото."""
        import json
        for i, r in enumerate(results):
            meta = {"price_bbox": r.get("price_bbox"), "img_w": r.get("img_w"), "img_h": r.get("img_h")}
            self.conn.execute(
                """INSERT INTO photo_items (shop_run_id, order_idx, photo, price, discount,
                       row, product, text, candidates_json, meta_json, why, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (shop_run_id, i, str(r["photo"]), r["price"], int(r["discount"]),
                 r["row"], r["product"], r["text"],
                 json.dumps(r["candidates"], ensure_ascii=False),
                 json.dumps(meta, ensure_ascii=False), r["why"], r["status"]))
        self.conn.commit()

    def _row_to_item(self, row):
        import json
        (iid, shop_run_id, order_idx, photo, price, discount, prow, product, text,
         cand_json, meta_json, why, status, cprice, crow, cdiscount, journaled) = row
        meta = json.loads(meta_json) if meta_json else {}
        return {"id": iid, "shop_run_id": shop_run_id, "order_idx": order_idx, "photo": photo,
                "price": price, "discount": bool(discount), "row": prow, "product": product,
                "text": text, "candidates": json.loads(cand_json) if cand_json else [],
                "price_bbox": meta.get("price_bbox"), "img_w": meta.get("img_w"), "img_h": meta.get("img_h"),
                "why": why, "status": status, "confirmed_price": cprice,
                "confirmed_row": crow, "confirmed_discount": bool(cdiscount), "journaled": bool(journaled)}

    def photo_items_all(self, shop_run_id):
        rows = self.conn.execute(
            f"SELECT {self._ITEM_COLS} FROM photo_items WHERE shop_run_id=? ORDER BY order_idx",
            (shop_run_id,)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def photo_items_for_review(self, shop_run_id):
        rows = self.conn.execute(
            f"""SELECT {self._ITEM_COLS} FROM photo_items WHERE shop_run_id=? AND status IN ({",".join("?" * len(REVIEW_STATUSES))})
               ORDER BY order_idx""",
            (shop_run_id, *REVIEW_STATUSES)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def photo_item_get(self, item_id):
        row = self.conn.execute(
            f"SELECT {self._ITEM_COLS} FROM photo_items WHERE id=?", (item_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def photo_item_set(self, item_id, status, price=None, row=None, discount=None):
        """Подтвердить/отложить элемент. price/row/discount - финальные
        значения человека (для 'подтверждено'); для 'отложено' не нужны."""
        self.conn.execute(
            """UPDATE photo_items SET status=?, confirmed_price=?, confirmed_row=?,
                       confirmed_discount=? WHERE id=?""",
            (status, price, row, int(bool(discount)), item_id))
        self.conn.commit()

    def photo_items_pending_journal(self, shop_run_id):
        """Готовые к записи (авто/подтверждено), ещё не попавшие в журнал -
        так повторное открытие «Итога» не задваивает journal_add."""
        rows = self.conn.execute(
            f"""SELECT {self._ITEM_COLS} FROM photo_items
               WHERE shop_run_id=? AND journaled=0 AND status IN ({",".join("?" * len(DONE_STATUSES))})""",
            (shop_run_id, *DONE_STATUSES)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def photo_item_mark_journaled(self, item_id):
        self.conn.execute("UPDATE photo_items SET journaled=1 WHERE id=?", (item_id,))
        self.conn.commit()
