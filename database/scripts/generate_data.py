"""Generate deterministic SYNTHETIC MySQL data; import only into empty tables."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path


COLUMNS = {
    "categories": ("category_id", "name"),
    "publishers": ("publisher_id", "name"),
    "authors": ("author_id", "author_key", "name"),
    "books": ("book_id", "isbn", "title", "category_id", "publisher_id", "publication_year", "description", "created_at"),
    "book_authors": ("book_id", "author_id"),
    "book_copies": ("copy_id", "book_id", "barcode", "shelf_code", "status", "acquired_at"),
    "readers": ("reader_id", "reader_no", "name", "email", "status", "created_at"),
    "loans": ("loan_id", "reader_id", "copy_id", "borrowed_at", "due_at", "returned_at"),
}


def make_isbn13(number: int) -> str:
    if not 0 <= number < 10**9:
        raise ValueError("ISBN synthetic sequence must be between 0 and 999999999.")
    first_twelve = f"979{number:09d}"
    check = (-sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(first_twelve))) % 10
    return first_twelve + str(check)


def sql_literal(value) -> str:
    """Hex-encode text, avoiding SQL-mode-dependent quote/backslash escaping."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, datetime):
        value = value.isoformat(sep=" ", timespec="seconds")
    elif isinstance(value, date):
        value = value.isoformat()
    if not isinstance(value, str):
        raise TypeError(f"Unsupported SQL value type: {type(value).__name__}")
    return "CONVERT(X'" + value.encode("utf-8").hex() + "' USING utf8mb4)"


def build_fixture(books: int, readers: int, loans: int, seed: int, as_of: date) -> dict:
    if not 1 <= books <= 999_999_999:
        raise ValueError("--books must be in 1..999999999.")
    if readers < 1 or loans < 0:
        raise ValueError("--readers must be positive; --loans must be nonnegative.")
    if not 1450 <= as_of.year <= 2100:
        raise ValueError("--as-of must have a year between 1450 and 2100.")
    rng = random.Random(seed)
    fixture = {table: [] for table in COLUMNS}
    category_count = min(8, books)
    publisher_count = min(12, books)
    author_count = max(2, min(2 * books, 500))
    fixture["categories"] = [(i, f"Synthetic Category {i:02d}") for i in range(1, category_count + 1)]
    fixture["publishers"] = [(i, f"Synthetic Publisher {i:02d}") for i in range(1, publisher_count + 1)]
    # Two people deliberately have the same display name but distinct stable keys.
    fixture["authors"] = [
        (i, f"syn-author-{i:05d}", "合成同名作者" if i in (1, 2) else f"Synthetic Author {i:05d}")
        for i in range(1, author_count + 1)
    ]
    eligible = [i for i in range(1, 3 * books + 1) if i % 20 != 0 and i % 37 != 0]
    rng.shuffle(eligible)
    active_count = min(loans, max(0, len(eligible) - 1), max(2, loans // 5)) if loans else 0
    history_count = loans - active_count
    cycles = (history_count + len(eligible) - 1) // len(eligible)
    try:
        origin = datetime.combine(as_of, time(9)) - timedelta(days=(cycles + 1) * 32 + 120)
        acquired = (origin - timedelta(days=30)).date()
    except (OverflowError, ValueError) as exc:
        raise ValueError("Dataset history exceeds the supported date range; increase --books or reduce --loans.") from exc
    if acquired.year < 1450:
        raise ValueError("Dataset acquisition date predates the allowed publication-year range; increase --books or reduce --loans.")
    created_at = datetime.combine(acquired, time(8))
    for i in range(1, books + 1):
        isbn = make_isbn13(i)
        fixture["books"].append((
            i, isbn, f"Synthetic Book {i:07d}", (i - 1) % category_count + 1,
            (i - 1) % publisher_count + 1, rng.randint(max(1450, acquired.year - 40), acquired.year),
            "Synthetic catalog record for database experiments; not a real publication.", created_at,
        ))
        first_author = (i - 1) % author_count + 1
        fixture["book_authors"].append((i, first_author))
        if i == 1 or i % 5 == 0:
            fixture["book_authors"].append((i, first_author % author_count + 1))
        for n in range(1, 4):
            copy_id = (i - 1) * 3 + n
            status = "MAINTENANCE" if copy_id % 20 == 0 else ("WITHDRAWN" if copy_id % 37 == 0 else "IN_SERVICE")
            fixture["book_copies"].append((copy_id, i, f"{isbn}-{n:03d}", f"SYN-{(i - 1) % 30 + 1:02d}", status, acquired))
    fixture["readers"] = [
        (i, f"SYN{i:08d}", f"Synthetic Reader {i:07d}", f"reader{i:08d}@example.invalid", "ACTIVE", created_at)
        for i in range(1, readers + 1)
    ]
    for i in range(history_count):
        copy_id = eligible[i % len(eligible)]
        cycle = i // len(eligible)
        borrowed = origin + timedelta(days=cycle * 32, hours=rng.randint(0, 5))
        due = borrowed + timedelta(days=30)
        returned = borrowed + timedelta(days=rng.randint(1, 25), hours=rng.randint(0, 3))
        fixture["loans"].append((i + 1, rng.randint(1, readers), copy_id, borrowed, due, returned))
    anchor = datetime.combine(as_of, time(12))
    for i, copy_id in enumerate(eligible[:active_count]):
        borrowed = anchor - timedelta(days=45 if i % 2 == 0 else 5)
        fixture["loans"].append((history_count + i + 1, rng.randint(1, readers), copy_id, borrowed, borrowed + timedelta(days=30), None))
    return fixture


def _write_insert(stream, table: str, rows: list, batch_size=500):
    columns = ",".join(f"`{name}`" for name in COLUMNS[table])
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset:offset + batch_size]
        stream.write(f"INSERT INTO `{table}` ({columns}) VALUES\n")
        stream.write(",\n".join("(" + ",".join(sql_literal(v) for v in row) + ")" for row in batch))
        stream.write(";\n\n")


def generate_sql(output: str | Path, books=1000, readers=500, loans=10000, seed=2026, as_of=date(2026, 11, 26)) -> dict:
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    fixture = build_fixture(books, readers, loans, seed, as_of)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("-- SYNTHETIC DATA ONLY: not real people, publications, or transactions.\n")
        stream.write("-- PRECONDITION: all eight application tables must be EMPTY.\n")
        stream.write("-- Do not combine this fixture with the CSV catalog sample.\n")
        stream.write("-- Do not use a client option that continues after SQL errors.\n")
        stream.write(f"-- seed={seed}; as_of={as_of.isoformat()}; books={books}; readers={readers}; loans={loans}\n")
        stream.write("SET NAMES utf8mb4;\nSTART TRANSACTION;\n\n")
        for table, rows in fixture.items():
            _write_insert(stream, table, rows)
        stream.write("COMMIT;\n")
    temporary.replace(output)
    anchor = datetime.combine(as_of, time(12))
    open_loans = [row for row in fixture["loans"] if row[5] is None]
    manifest = {
        "synthetic": True,
        "description": "Synthetic records, including deliberately shared author names; not real people or publications.",
        "generator": "scripts/generate_data.py",
        "parameters": {"books": books, "readers": readers, "loans": loans, "seed": seed, "as_of": as_of.isoformat()},
        "table_rows": {name: len(rows) for name, rows in fixture.items()},
        "scenarios": {
            "open_loans": len(open_loans),
            "overdue_at_as_of_noon": sum(row[4] < anchor for row in open_loans),
            "not_yet_due_at_as_of_noon": sum(row[4] >= anchor for row in open_loans),
            "returned_loans": loans - len(open_loans),
            "available_copies": sum(row[4] == "IN_SERVICE" for row in fixture["book_copies"]) - len(open_loans),
        },
        "precondition": "All eight application tables must be empty; use a separate experiment database.",
        "sql_file": output.name,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", type=int, default=1000)
    parser.add_argument("--readers", type=int, default=500)
    parser.add_argument("--loans", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 11, 26))
    parser.add_argument("--output", type=Path, default=Path("data/generated.sql"))
    args = parser.parse_args(argv)
    try:
        manifest = generate_sql(args.output, args.books, args.readers, args.loans, args.seed, args.as_of)
    except (OSError, ValueError) as exc:
        print(f"Generation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
