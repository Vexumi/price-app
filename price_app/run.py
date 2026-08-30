# -*- coding: utf-8 -*-
"""CLI-конвейер без GUI: обработать папку фото одного магазина.

    python -m price_app.run --dir <папка> --chain ПЯТЕРОЧКА \\
        --shop "Ленина 1" --date 05.03.2026 [--dry-run] [--table файл.xlsx]

--dry-run печатает отчёт и ничего не сохраняет: ни в журнал (SQLite), ни
в Excel. Без него результаты уходят в журнал и уверенные («авто»)
записи сразу пишутся в таблицу - это первый CLI-прогон одного магазина,
многомагазинную сверку и разрешение конфликтов делает GUI (см. план,
раздел «Разрешение конфликта»).
"""
import argparse, datetime, pathlib, sys

from . import excel_io as X
from . import pipeline as PL
from .store import Store

PHOTO_EXT = (".png", ".jpg", ".jpeg")


def list_photos(folder):
    return sorted(p for p in pathlib.Path(folder).iterdir()
                  if p.suffix.lower() in PHOTO_EXT)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="папка с фото одного магазина")
    ap.add_argument("--chain", required=True, help="сеть (как в таблице, напр. ПЯТЕРОЧКА)")
    ap.add_argument("--shop", required=True, help="название/адрес магазина")
    ap.add_argument("--date", required=True, help="дата замера, ДД.ММ.ГГГГ")
    ap.add_argument("--table", default="итоговый ценовой срез(АВГУСТ).xlsx")
    ap.add_argument("--db", default="price_app.db", help="файл журнала SQLite")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    the_date = datetime.datetime.strptime(a.date, "%d.%m.%Y").date()
    photos = list_photos(a.dir)
    if not photos:
        sys.exit(f"В папке {a.dir!r} нет фото ({', '.join(PHOTO_EXT)}).")

    wb, ws, header_row, cols = X.load_table(a.table)
    chains = X.list_chains(ws, header_row, cols)
    chain = X.norm(a.chain)
    if chain not in chains:
        guess = X.guess_chain(a.chain, chains)
        hint = f" Похоже на {guess!r}?" if guess else ""
        sys.exit(f"Сети {a.chain!r} нет в таблице.{hint}\nЕсть: {', '.join(chains)}")

    candidates = X.build_candidates(ws, header_row, cols, chain)
    if not candidates:
        sys.exit(f"У сети {chain!r} нет ни одного товара в таблице.")

    store = Store(a.db)
    engine = PL.make_engine()
    refine_engine = PL.make_refine_engine()

    print(f"Сеть: {chain} | товаров-кандидатов: {len(candidates)} | фото: {len(photos)}\n")

    counts = {"авто": 0, "нужен товар": 0, "нужна цена": 0,
              "на проверку": 0, "подозрительная цена": 0}
    to_write, to_review = [], []

    for i, photo in enumerate(photos, 1):
        r = PL.process_photo(photo, chain, candidates, store, a.shop, engine, refine_engine)
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        price_s = f"{r['price']:.2f}" if r["price"] is not None else "   ---"
        row_s = str(r["row"]) if r["row"] is not None else "-"
        print(f"[{i:3}/{len(photos)}] {r['status']:<20} {price_s:>8} "
              f"строка={row_s:<6} {photo.name}")
        if r["status"] != "авто":
            to_review.append((photo, r))
        else:
            to_write.append(r)
            if not a.dry_run:
                store.cache_put(chain, X.norm(r["text"]), r["row"])

    print("\n" + "=" * 60)
    for k, v in counts.items():
        print(f"  {v:4}  {k}")

    if to_review:
        print(f"\nНа проверку ({len(to_review)}):")
        for photo, r in to_review:
            print(f"  {photo.name}: {r['why']}")
            for score, row, prod, mass in r["candidates"][:3]:
                print(f"      {score:5.1f}  строка {row}: {prod}")

    if a.dry_run:
        print("\n--dry-run: ничего не сохранено.")
        return

    for r in to_write:
        store.journal_add(the_date, chain, r["row"], a.shop, r["price"], r["discount"], r["photo"])
    store.shop_remember(a.shop, chain, a.shop)

    conflicts = store.journal_conflicts(the_date)
    if conflicts:
        print(f"\nКонфликты за {a.date} ({len(conflicts)}) - НЕ записаны, нужно разрешить вручную:")
        for c in conflicts:
            print(f"  сеть={c['chain']} строка={c['row']}: {c['entries']}")

    ready = store.journal_for_write(the_date, chain)
    if ready:
        col, n = X.write_prices(wb, ws, header_row, cols, the_date, ready, a.table)
        print(f"\nЗаписано в {a.table}: {n} цен, столбец {col} ({a.date}).")
    else:
        print("\nНечего записывать (все записи в конфликте или их нет).")


if __name__ == "__main__":
    main()
