"""Atomic, idempotent CSV catalog import. Sample records are synthetic."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


HEADERS = (
    "isbn", "title", "authors", "publisher", "publication_year",
    "category", "copies", "shelf_code", "description",
)


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class CatalogRow:
    line: int
    isbn: str
    title: str
    authors: tuple[tuple[str, str], ...]
    publisher: str
    publication_year: int
    category: str
    copies: int
    shelf_code: str
    description: str

    def metadata(self):
        return (
            self.isbn, self.title, self.authors, self.publisher,
            self.publication_year, self.category, self.copies,
            self.shelf_code, self.description,
        )


@dataclass(frozen=True)
class CatalogBatch:
    rows: tuple[CatalogRow, ...]
    duplicates_skipped: int


def valid_isbn13(value: str) -> bool:
    if not re.fullmatch(r"(?:978|979)[0-9]{10}", value):
        return False
    return sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(value)) % 10 == 0


def _text(value: str, name: str, maximum: int, line: int, required=True) -> str:
    value = value.strip()
    if (required and not value) or len(value) > maximum or "\x00" in value:
        raise CatalogError(f"CSV line {line}: invalid {name} (maximum {maximum} characters).")
    return value


def _integer(value: str, name: str, low: int, high: int, line: int) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise CatalogError(f"CSV line {line}: {name} must be an integer in {low}..{high}.")
    number = int(value)
    if not low <= number <= high:
        raise CatalogError(f"CSV line {line}: {name} must be in {low}..{high}.")
    return number


def parse_catalog(path: str | Path) -> CatalogBatch:
    """Validate the entire file before any connection or database write."""
    seen: dict[str, CatalogRow] = {}
    author_names: dict[str, str] = {}
    duplicate_count = 0
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or len(reader.fieldnames) != len(HEADERS) or set(reader.fieldnames) != set(HEADERS):
            raise CatalogError("CSV header must contain exactly: " + ",".join(HEADERS))
        for values in reader:
            line = reader.line_num
            if None in values or any(value is None for value in values.values()):
                raise CatalogError(f"CSV line {line}: wrong number of fields.")
            values = {key: value.strip() for key, value in values.items()}
            isbn = values["isbn"]
            if not valid_isbn13(isbn):
                raise CatalogError(f"CSV line {line}: invalid ISBN-13 or checksum.")
            authors = []
            for part in values["authors"].split("|"):
                if ":" not in part:
                    raise CatalogError(f"CSV line {line}: authors must use key:name|key:name.")
                key, name = part.split(":", 1)
                key = _text(key, "author_key", 64, line)
                if not key.isascii():
                    raise CatalogError(f"CSV line {line}: author_key must contain ASCII characters only.")
                name = _text(name, "author name", 120, line)
                if key in {item[0] for item in authors}:
                    raise CatalogError(f"CSV line {line}: repeated author_key in a book.")
                if key in author_names and author_names[key] != name:
                    raise CatalogError(f"CSV line {line}: author_key {key!r} has conflicting names.")
                author_names[key] = name
                authors.append((key, name))
            description = _text(values["description"], "description", 65535, line, required=False)
            if len(description.encode("utf-8")) > 65535:
                raise CatalogError(f"CSV line {line}: description exceeds MySQL TEXT byte limit.")
            row = CatalogRow(
                line=line, isbn=isbn,
                title=_text(values["title"], "title", 255, line),
                authors=tuple(sorted(authors)),
                publisher=_text(values["publisher"], "publisher", 160, line),
                publication_year=_integer(values["publication_year"], "publication_year", 1450, 2100, line),
                category=_text(values["category"], "category", 80, line),
                copies=_integer(values["copies"], "copies", 1, 1000, line),
                shelf_code=_text(values["shelf_code"], "shelf_code", 40, line),
                description=description,
            )
            if isbn in seen:
                if row.metadata() != seen[isbn].metadata():
                    raise CatalogError(f"CSV line {line}: conflicting duplicate ISBN (first seen on line {seen[isbn].line}).")
                duplicate_count += 1
            else:
                seen[isbn] = row
    return CatalogBatch(tuple(seen.values()), duplicate_count)


def _reference(cursor, table: str, key_column: str, id_column: str, value: str) -> int:
    # Identifiers are private constants; all input values remain bound parameters.
    cursor.execute(
        f"INSERT INTO {table} ({key_column}) VALUES (%s) "
        f"ON DUPLICATE KEY UPDATE {id_column}=LAST_INSERT_ID({id_column})", (value,),
    )
    cursor.execute(f"SELECT {id_column},{key_column} FROM {table} WHERE {key_column}=%s FOR UPDATE", (value,))
    record = cursor.fetchone()
    if record[key_column] != value:
        raise CatalogError(f"{table} name collides under database collation; use the existing exact spelling")
    return record[id_column]


def _existing_matches(cursor, existing: dict, row: CatalogRow) -> bool:
    cursor.execute(
        "SELECT a.author_key,a.name FROM book_authors ba "
        "JOIN authors a ON a.author_id=ba.author_id WHERE ba.book_id=%s", (existing["book_id"],),
    )
    authors = tuple(sorted((a["author_key"], a["name"]) for a in cursor.fetchall()))
    cursor.execute("SELECT barcode,shelf_code FROM book_copies WHERE book_id=%s", (existing["book_id"],))
    copies = cursor.fetchall()
    expected_barcodes = {f"{row.isbn}-{i:03d}" for i in range(1, row.copies + 1)}
    return (
        existing["isbn"] == row.isbn and existing["title"] == row.title
        and existing["publisher"] == row.publisher and existing["category"] == row.category
        and existing["publication_year"] == row.publication_year
        and (existing["description"] or "") == row.description and authors == row.authors
        and len(copies) == row.copies
        and {c["barcode"] for c in copies} == expected_barcodes
        and all(c["shelf_code"] == row.shelf_code for c in copies)
    )


def import_batch(conn, batch: CatalogBatch, acquired_at: date | None = None) -> dict:
    """Own one transaction. Do not call with other pending work on this connection."""
    acquired_at = acquired_at or datetime.now(timezone(timedelta(hours=8))).date()
    stats = {"books_inserted": 0, "copies_inserted": 0, "books_skipped": batch.duplicates_skipped}
    try:
        conn.begin()
        with conn.cursor() as cursor:
            for row in batch.rows:
                try:
                    cursor.execute(
                        "SELECT b.book_id,b.isbn,b.title,b.publication_year,b.description,"
                        "c.name AS category,p.name AS publisher FROM books b "
                        "JOIN categories c ON c.category_id=b.category_id "
                        "JOIN publishers p ON p.publisher_id=b.publisher_id WHERE b.isbn=%s FOR UPDATE", (row.isbn,),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        if not _existing_matches(cursor, existing, row):
                            raise CatalogError("existing ISBN has different metadata, authors or copies")
                        stats["books_skipped"] += 1
                        continue
                    category_id = _reference(cursor, "categories", "name", "category_id", row.category)
                    publisher_id = _reference(cursor, "publishers", "name", "publisher_id", row.publisher)
                    author_ids = []
                    for key, name in row.authors:
                        cursor.execute(
                            "INSERT INTO authors(author_key,name) VALUES(%s,%s) "
                            "ON DUPLICATE KEY UPDATE author_id=LAST_INSERT_ID(author_id)", (key, name),
                        )
                        cursor.execute("SELECT author_id,name FROM authors WHERE author_key=%s FOR UPDATE", (key,))
                        author = cursor.fetchone()
                        if author["name"] != name:
                            raise CatalogError(f"author_key {key!r} already has a different name")
                        author_ids.append(author["author_id"])
                    cursor.execute(
                        "INSERT INTO books(isbn,title,category_id,publisher_id,publication_year,description) "
                        "VALUES(%s,%s,%s,%s,%s,%s)",
                        (row.isbn, row.title, category_id, publisher_id, row.publication_year, row.description or None),
                    )
                    book_id = cursor.lastrowid
                    cursor.executemany("INSERT INTO book_authors(book_id,author_id) VALUES(%s,%s)", [(book_id, a) for a in author_ids])
                    cursor.executemany(
                        "INSERT INTO book_copies(book_id,barcode,shelf_code,status,acquired_at) "
                        "VALUES(%s,%s,%s,%s,%s)",
                        [(book_id, f"{row.isbn}-{i:03d}", row.shelf_code, "IN_SERVICE", acquired_at) for i in range(1, row.copies + 1)],
                    )
                    stats["books_inserted"] += 1
                    stats["copies_inserted"] += row.copies
                except Exception as exc:
                    if isinstance(exc, CatalogError):
                        detail = str(exc)
                    else:
                        # A driver exception can include arbitrary input; never echo credentials.
                        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else type(exc).__name__
                        detail = f"database rejected the row ({code})"
                    raise CatalogError(f"CSV line {row.line}: {detail}; entire import rolled back.") from exc
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return stats


def import_catalog(conn, path: str | Path, acquired_at: date | None = None) -> dict:
    return import_batch(conn, parse_catalog(path), acquired_at)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args(argv)
    conn = None
    try:
        batch = parse_catalog(args.csv_path)
        from db import connect
        conn = connect()
        print(json.dumps(import_batch(conn, batch), ensure_ascii=False))
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
