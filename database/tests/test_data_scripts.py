"""Offline checks; real MySQL constraint/transaction tests are separate."""
from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_data import build_fixture, generate_sql, make_isbn13, sql_literal
from import_books import CatalogError, HEADERS, import_batch, parse_catalog, valid_isbn13


def sample_row(**overrides):
    row = dict(zip(HEADERS, (
        "9790000000018", "合成数据库书目", "a001:合成作者甲|a002:合成作者乙",
        "合成出版社", "2026", "数据库", "3", "SYN-01", "Synthetic test record.",
    )))
    row.update(overrides)
    return row


class DataScriptsTests(unittest.TestCase):
    def setUp(self):
        # Default mkdir permissions also work in restricted Windows runtimes;
        # tempfile.TemporaryDirectory uses mode 0700, which some ACL bridges reject.
        self.temp_root = Path(tempfile.gettempdir()).resolve()
        self.directory = self.temp_root / ("library-test-" + uuid.uuid4().hex)
        self.directory.mkdir()

    def tearDown(self):
        target = self.directory.resolve()
        self.assertEqual(target.parent, self.temp_root)
        self.assertTrue(target.name.startswith("library-test-"))
        shutil.rmtree(target)

    def catalog(self, rows, headers=HEADERS):
        path = self.directory / "catalog.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_known_isbn_checksums_and_ascii_only(self):
        self.assertTrue(valid_isbn13("9780306406157"))
        self.assertFalse(valid_isbn13("9780306406158"))
        self.assertFalse(valid_isbn13("９７８０３０６４０６１５７"))
        self.assertFalse(valid_isbn13("1234567890128"))
        for i in (1, 2, 500, 999_999_999):
            self.assertTrue(valid_isbn13(make_isbn13(i)))

    def test_bom_chinese_and_author_set_duplicate(self):
        path = self.catalog([sample_row(), sample_row(authors="a002:合成作者乙|a001:合成作者甲")])
        batch = parse_catalog(path)
        self.assertEqual(len(batch.rows), 1)
        self.assertEqual(batch.duplicates_skipped, 1)
        self.assertEqual(batch.rows[0].title, "合成数据库书目")

    def test_conflicting_isbn_is_rejected_before_writes(self):
        path = self.catalog([sample_row(), sample_row(copies="4")])
        with self.assertRaisesRegex(CatalogError, "line 3.*conflicting duplicate ISBN"):
            parse_catalog(path)

    def test_stable_author_key_cannot_be_renamed(self):
        path = self.catalog([sample_row(), sample_row(isbn=make_isbn13(2), authors="a001:其他姓名")])
        with self.assertRaisesRegex(CatalogError, "line 3.*conflicting names"):
            parse_catalog(path)

    def test_input_bounds_and_unsupported_status_column(self):
        for override in ({"copies": "0"}, {"copies": "1001"}, {"publication_year": "1449"}, {"title": "x" * 256}, {"authors": "no-key"}, {"authors": "作者一:姓名"}):
            with self.subTest(override=override):
                with self.assertRaises(CatalogError):
                    parse_catalog(self.catalog([sample_row(**override)]))
        row = sample_row()
        row["status"] = "UNRECOGNIZED"
        with self.assertRaisesRegex(CatalogError, "header"):
            parse_catalog(self.catalog([row], (*HEADERS, "status")))

    def test_injection_text_is_bound_in_importer(self):
        attack = "x'); DROP TABLE books; -- \\ 中文"
        batch = parse_catalog(self.catalog([sample_row(title=attack, authors="a001:合成作者甲")]))
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [None, {"category_id": 1, "name": "数据库"}, {"publisher_id": 1, "name": "合成出版社"}, {"author_id": 1, "name": "合成作者甲"}]
        cursor.lastrowid = 10
        result = import_batch(conn, batch, date(2026, 11, 26))
        calls = cursor.execute.call_args_list
        self.assertTrue(any(attack in call.args[1] for call in calls))
        self.assertTrue(all(attack not in call.args[0] for call in calls))
        self.assertEqual(result["copies_inserted"], 3)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_late_database_conflict_rolls_back_whole_batch(self):
        batch = parse_catalog(self.catalog([sample_row(authors="a001:合成作者甲"), sample_row(isbn=make_isbn13(2), authors="a001:合成作者甲")]))
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.lastrowid = 10
        cursor.fetchone.side_effect = [
            None, {"category_id": 1, "name": "数据库"}, {"publisher_id": 1, "name": "合成出版社"}, {"author_id": 1, "name": "合成作者甲"},
            {"book_id": 20, "isbn": make_isbn13(2), "title": "合成数据库书目", "publication_year": 2026,
             "description": "Synthetic test record.", "category": "CONFLICT", "publisher": "合成出版社"},
        ]
        cursor.fetchall.side_effect = [[{"author_key": "a001", "name": "合成作者甲"}], []]
        with self.assertRaisesRegex(CatalogError, "line 3.*entire import rolled back"):
            import_batch(conn, batch)
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()

    def test_sql_encoding_preserves_injection_text_without_literal_sql(self):
        text = "O'Reilly\\path; DROP TABLE loans; -- 中文\x00"
        literal = sql_literal(text)
        self.assertNotIn("DROP TABLE", literal)
        self.assertNotIn(";", literal)
        encoded = literal.removeprefix("CONVERT(X'").removesuffix("' USING utf8mb4)")
        self.assertEqual(bytes.fromhex(encoded).decode("utf-8"), text)

    def test_generated_relations_dates_and_scenarios(self):
        fixture = build_fixture(10, 7, 100, 2026, date(2026, 11, 26))
        copies = {row[0]: row for row in fixture["book_copies"]}
        book_years = {row[0]: row[5] for row in fixture["books"]}
        self.assertTrue(all(book_years[row[1]] <= row[5].year for row in copies.values()))
        open_copies = set()
        intervals = defaultdict(list)
        for row in fixture["loans"]:
            _, reader_id, copy_id, borrowed, due, returned = row
            self.assertIn(reader_id, range(1, 8))
            self.assertEqual(copies[copy_id][4], "IN_SERVICE")
            self.assertLessEqual(copies[copy_id][5], borrowed.date())
            self.assertGreater(due, borrowed)
            if returned is None:
                self.assertNotIn(copy_id, open_copies)
                open_copies.add(copy_id)
            else:
                self.assertGreaterEqual(returned, borrowed)
            intervals[copy_id].append((borrowed, returned))
        for rows in intervals.values():
            rows.sort(key=lambda row: row[0])
            for earlier, later in zip(rows, rows[1:]):
                self.assertIsNotNone(earlier[1])
                self.assertLess(earlier[1], later[0])
        self.assertTrue(any(row[5] is None and row[4].date() < date(2026, 11, 26) for row in fixture["loans"]))
        self.assertTrue(any(row[5] is None and row[4].date() > date(2026, 11, 26) for row in fixture["loans"]))
        self.assertLess(len(open_copies), sum(row[4] == "IN_SERVICE" for row in copies.values()))
        self.assertEqual(fixture["authors"][0][2], fixture["authors"][1][2])
        self.assertNotEqual(fixture["authors"][0][1], fixture["authors"][1][1])
        self.assertEqual(sum(row[0] == 1 for row in fixture["book_authors"]), 2)

    def test_generation_is_byte_deterministic_and_manifest_matches(self):
        first = self.directory / "first" / "fixture.sql"
        second = self.directory / "second" / "fixture.sql"
        a = generate_sql(first, 5, 3, 40, 2026, date(2026, 11, 26))
        b = generate_sql(second, 5, 3, 40, 2026, date(2026, 11, 26))
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(a, b)
        self.assertEqual(json.loads(first.with_suffix(".manifest.json").read_text(encoding="utf-8")), a)
        self.assertTrue(a["synthetic"])
        self.assertEqual(a["table_rows"]["book_copies"], 15)
        self.assertEqual(a["table_rows"]["loans"], 40)
        self.assertNotIn("active_copy_id", first.read_text(encoding="utf-8"))

    def test_repository_sample_is_valid_and_explicitly_synthetic(self):
        batch = parse_catalog(ROOT / "data" / "books_sample.csv")
        self.assertEqual(len(batch.rows), 6)
        self.assertTrue(all("Synthetic" in row.description for row in batch.rows))


if __name__ == "__main__":
    unittest.main()
