"""Real MySQL CSV-import checks in an isolated, named test database.

Set RUN_IMPORT_DB_TESTS=1 and DB_HOST/DB_PORT/DB_USER/DB_PASSWORD, then run
this file directly. The account must be allowed to create library_importcheck.
No tables are dropped. Only this suite's precise fixture rows are cleaned up.
MYSQL_BIN optionally identifies the mysql command-line client for schema setup.
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect
from generate_data import make_isbn13
from import_books import CatalogError, HEADERS, import_catalog, parse_catalog

TEST_DATABASE = "library_importcheck"
TABLES = ("categories", "publishers", "authors", "books", "book_authors", "book_copies", "readers", "loans")


@unittest.skipUnless(os.environ.get("RUN_IMPORT_DB_TESTS") == "1", "Set RUN_IMPORT_DB_TESTS=1 to run the isolated MySQL import checks.")
class ImportDatabaseTests(unittest.TestCase):
    server_version = None

    @classmethod
    def setUpClass(cls):
        import pymysql

        if "DB_PASSWORD" not in os.environ:
            raise RuntimeError("DB_PASSWORD must be set; an explicitly empty value is allowed.")
        settings = dict(
            host=os.environ.get("DB_HOST", "127.0.0.1"), port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ.get("DB_USER", "library_app"), password=os.environ["DB_PASSWORD"],
            charset="utf8mb4", autocommit=True,
        )
        with pymysql.connect(**settings) as admin:
            with admin.cursor() as cursor:
                cursor.execute("SELECT VERSION()")
                cls.server_version = cursor.fetchone()[0]
                cursor.execute("CREATE DATABASE IF NOT EXISTS library_importcheck CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
                cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (TEST_DATABASE,))
                existing = {row[0] for row in cursor.fetchall()}
        if not existing:
            env = os.environ.copy()
            env["MYSQL_PWD"] = settings["password"]
            command = [
                os.environ.get("MYSQL_BIN", "mysql"), "--no-defaults",
                "--host", settings["host"], "--port", str(settings["port"]),
                "--user", settings["user"], "--default-character-set=utf8mb4",
                "--database", TEST_DATABASE,
            ]
            completed = subprocess.run(command, input=(ROOT / "sql" / "01_schema.sql").read_bytes(),
                                       capture_output=True, env=env, check=False)
            if completed.returncode:
                raise RuntimeError("Schema setup failed: " + completed.stderr.decode("utf-8", errors="replace"))
        elif existing != set(TABLES):
            raise RuntimeError("Refusing to reuse a test database whose tables do not match this project.")
        cls.env_patch = patch.dict(os.environ, {"DB_NAME": TEST_DATABASE})
        cls.env_patch.start()
        cls.conn = connect()
        with (ROOT / "data" / "books_sample.csv").open(encoding="utf-8-sig", newline="") as stream:
            cls.sample_rows = list(csv.DictReader(stream))
        cls.sample_isbns = {row["isbn"] for row in cls.sample_rows}
        # Repeated runs remove only the six exact synthetic sample records here.
        # Never remove an unexpected record, even in this dedicated database.
        with cls.conn.cursor() as cursor:
            placeholders = ",".join(["%s"] * len(cls.sample_isbns))
            cursor.execute(f"SELECT book_id,isbn,description FROM books WHERE isbn IN ({placeholders})", tuple(cls.sample_isbns))
            records = cursor.fetchall()
            source = {row["isbn"]: row["description"] for row in cls.sample_rows}
            for record in records:
                if record["description"] != source[record["isbn"]]:
                    raise RuntimeError("Refusing to clean a sample ISBN with unexpected content.")
            cls._delete_books(cursor, [record["book_id"] for record in records])
        cls.conn.commit()

    @staticmethod
    def _delete_books(cursor, book_ids):
        if not book_ids:
            return
        placeholders = ",".join(["%s"] * len(book_ids))
        cursor.execute(
            f"SELECT COUNT(*) AS n FROM loans l JOIN book_copies c ON c.copy_id=l.copy_id WHERE c.book_id IN ({placeholders})",
            tuple(book_ids),
        )
        if cursor.fetchone()["n"]:
            raise RuntimeError("Refusing fixture cleanup because borrowing history references these books.")
        cursor.execute(f"DELETE FROM book_authors WHERE book_id IN ({placeholders})", tuple(book_ids))
        cursor.execute(f"DELETE FROM book_copies WHERE book_id IN ({placeholders})", tuple(book_ids))
        cursor.execute(f"DELETE FROM books WHERE book_id IN ({placeholders})", tuple(book_ids))

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()
        if hasattr(cls, "env_patch"):
            cls.env_patch.stop()

    def setUp(self):
        self.prefix = "itimport-" + uuid.uuid4().hex[:16]
        self.temp_root = Path(tempfile.gettempdir()).resolve()
        self.directory = self.temp_root / ("library-import-test-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.fixture_isbns = set()
        self.author_keys = set()
        self.publisher_names = set()
        self.category_names = set()
        self.csv_number = 0

    def tearDown(self):
        self.conn.rollback()
        with self.conn.cursor() as cursor:
            if self.fixture_isbns:
                placeholders = ",".join(["%s"] * len(self.fixture_isbns))
                cursor.execute(f"SELECT book_id FROM books WHERE isbn IN ({placeholders})", tuple(self.fixture_isbns))
                self._delete_books(cursor, [row["book_id"] for row in cursor.fetchall()])
            for key in self.author_keys:
                cursor.execute("DELETE FROM authors WHERE author_key=%s AND NOT EXISTS (SELECT 1 FROM book_authors WHERE author_id=authors.author_id)", (key,))
            for name in self.publisher_names:
                cursor.execute("DELETE FROM publishers WHERE name=%s AND NOT EXISTS (SELECT 1 FROM books WHERE publisher_id=publishers.publisher_id)", (name,))
            for name in self.category_names:
                cursor.execute("DELETE FROM categories WHERE name=%s AND NOT EXISTS (SELECT 1 FROM books WHERE category_id=categories.category_id)", (name,))
        self.conn.commit()
        target = self.directory.resolve()
        self.assertEqual(target.parent, self.temp_root)
        self.assertTrue(target.name.startswith("library-import-test-"))
        shutil.rmtree(target)

    def new_row(self, **changes):
        isbn = make_isbn13(900_000_000 + uuid.uuid4().int % 99_999_999)
        row = dict(zip(HEADERS, (
            isbn, self.prefix + " 合成书目", self.prefix + "-a:合成测试作者",
            self.prefix + "-publisher", "2024", self.prefix + "-category", "2", "SYN-IT01",
            "Synthetic integration-test fixture only.",
        )))
        row.update(changes)
        if row["isbn"] not in self.sample_isbns:
            self.fixture_isbns.add(row["isbn"])
        for author in row["authors"].split("|"):
            if ":" in author and author.split(":", 1)[0].startswith(self.prefix):
                self.author_keys.add(author.split(":", 1)[0])
        if row["publisher"].startswith(self.prefix):
            self.publisher_names.add(row["publisher"])
        if row["category"].startswith(self.prefix):
            self.category_names.add(row["category"])
        return row

    def csv_file(self, rows, bom=False):
        self.csv_number += 1
        path = self.directory / f"catalog-{self.csv_number}.csv"
        with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def counts(self):
        with self.conn.cursor() as cursor:
            result = {}
            for table in TABLES:
                cursor.execute(f"SELECT COUNT(*) AS n FROM {table}")
                result[table] = cursor.fetchone()["n"]
        self.conn.commit()  # Avoid carrying a consistent-read snapshot into an import.
        return result

    def test_01_first_sample_import(self):
        before = self.counts()
        result = import_catalog(self.conn, ROOT / "data" / "books_sample.csv", date(2026, 11, 26))
        after = self.counts()
        self.assertEqual(result, {"books_inserted": 6, "copies_inserted": 13, "books_skipped": 0})
        self.assertEqual(after["books"] - before["books"], 6)
        self.assertEqual(after["book_copies"] - before["book_copies"], 13)

    def test_02_repeated_sample_import_is_idempotent(self):
        before = self.counts()
        result = import_catalog(self.conn, ROOT / "data" / "books_sample.csv", date(2026, 11, 27))
        self.assertEqual(result, {"books_inserted": 0, "copies_inserted": 0, "books_skipped": 6})
        self.assertEqual(self.counts(), before)

    def test_03_identical_rows_in_one_file_are_idempotent(self):
        row = self.new_row()
        path = self.csv_file([row, row])
        before = self.counts()
        result = import_catalog(self.conn, path)
        after = self.counts()
        self.assertEqual(result, {"books_inserted": 1, "copies_inserted": 2, "books_skipped": 1})
        self.assertEqual(after["books"] - before["books"], 1)
        self.assertEqual(after["book_copies"] - before["book_copies"], 2)
        self.assertEqual(import_catalog(self.conn, path)["books_skipped"], 2)
        self.assertEqual(self.counts(), after)

    def test_04_late_metadata_conflict_rolls_back_all_tables(self):
        new = self.new_row()
        conflict = dict(self.sample_rows[0], title="合成书目：冲突标题")
        path = self.csv_file([new, conflict])
        before = self.counts()
        with self.assertRaisesRegex(CatalogError, "line 3.*entire import rolled back"):
            import_catalog(self.conn, path)
        self.assertEqual(self.counts(), before)
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT book_id FROM books WHERE isbn=%s", (new["isbn"],))
            self.assertIsNone(cursor.fetchone())

    def test_05_author_key_rename_rolls_back_all_tables(self):
        first = self.new_row()
        conflict = self.new_row(authors="syn-a001:合成作者改名冲突")
        before = self.counts()
        with self.assertRaisesRegex(CatalogError, "line 3.*different name.*entire import rolled back"):
            import_catalog(self.conn, self.csv_file([first, conflict]))
        self.assertEqual(self.counts(), before)
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT name FROM authors WHERE author_key=%s", ("syn-a001",))
            self.assertEqual(cursor.fetchone()["name"], "合成作者甲")

    def test_06_sql_injection_text_is_stored_as_data(self):
        attack = "合成'); DROP TABLE books; -- \\ SQL文本"
        row = self.new_row(title=attack, description=attack)
        import_catalog(self.conn, self.csv_file([row]))
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT title,description FROM books WHERE isbn=%s", (row["isbn"],))
            self.assertEqual(cursor.fetchone(), {"title": attack, "description": attack})
            cursor.execute("SELECT COUNT(*) AS n FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (TEST_DATABASE, "books"))
            self.assertEqual(cursor.fetchone()["n"], 1)
            cursor.execute("SELECT COUNT(*) AS n FROM books WHERE isbn=%s", (self.sample_rows[0]["isbn"],))
            self.assertEqual(cursor.fetchone()["n"], 1)

    def test_07_invalid_isbn_anywhere_writes_nothing(self):
        first = self.new_row()
        invalid = self.new_row(isbn="9780000000010")
        before = self.counts()
        with self.assertRaisesRegex(CatalogError, "line 3.*ISBN-13"):
            import_catalog(self.conn, self.csv_file([first, invalid]))
        self.assertEqual(self.counts(), before)

    def test_08_utf8_bom_and_four_byte_unicode(self):
        title = "合成书目：中文与四字节字符 📚"
        row = self.new_row(title=title)
        path = self.csv_file([row], bom=True)
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(len(parse_catalog(path).rows), 1)
        self.assertEqual(import_catalog(self.conn, path)["books_inserted"], 1)
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT title FROM books WHERE isbn=%s", (row["isbn"],))
            self.assertEqual(cursor.fetchone()["title"], title)

    def test_09_conflicting_rows_in_one_file_write_nothing(self):
        row = self.new_row()
        before = self.counts()
        with self.assertRaisesRegex(CatalogError, "line 3.*conflicting duplicate ISBN"):
            import_catalog(self.conn, self.csv_file([row, dict(row, copies="3")]))
        self.assertEqual(self.counts(), before)


def main():
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ImportDatabaseTests))
    transcript = capture.getvalue()
    print(transcript, end="")
    target = ROOT / "evaluation"
    target.mkdir(parents=True, exist_ok=True)
    (target / "import-tests.txt").write_text(transcript, encoding="utf-8")
    summary = {
        "suite": "real MySQL catalog import integration tests",
        "database": TEST_DATABASE,
        "server_version": ImportDatabaseTests.server_version,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "success": result.wasSuccessful() and not result.skipped,
        "tables_dropped": False,
        "notes": "Uses only library_importcheck; precise synthetic fixture rows are cleaned, six sample books remain.",
    }
    (target / "import-tests.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
