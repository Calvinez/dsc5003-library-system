"""Integration tests against the schema in DB_NAME. Creates only its own synthetic fixtures.

Run: python -m unittest discover -s tests -p test_database.py -v
Credentials and DB connection settings follow scripts/db.py. No tables are dropped.
"""
from __future__ import annotations

import concurrent.futures
import sys
import threading
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from db import connect


BORROWED = datetime(2026, 11, 1, 9)
DUE = BORROWED + timedelta(days=14)
RULE_ERRORS = {1644, 3819}


def valid_isbn():
    base = "978" + f"{uuid.uuid4().int % 1_000_000_000:09d}"
    check = (-sum(int(digit) * (1 if index % 2 == 0 else 3)
                  for index, digit in enumerate(base))) % 10
    return base + str(check)


def insert_fixture(conn):
    prefix = "T" + uuid.uuid4().hex[:14]
    ids = {"prefix": prefix, "isbn": valid_isbn()}
    with conn.cursor() as cur:
        cur.execute("INSERT INTO categories(name) VALUES (%s)", (prefix + " category",))
        ids["category"] = cur.lastrowid
        cur.execute("INSERT INTO publishers(name) VALUES (%s)", (prefix + " publisher",))
        ids["publisher"] = cur.lastrowid
        cur.execute("INSERT INTO authors(author_key,name) VALUES (%s,%s)", (prefix, "Synthetic author"))
        ids["author"] = cur.lastrowid
        cur.execute("""INSERT INTO books(isbn,title,category_id,publisher_id,publication_year)
            VALUES (%s,%s,%s,%s,2026)""",
                    (ids["isbn"], prefix + " synthetic book", ids["category"], ids["publisher"]))
        ids["book"] = cur.lastrowid
        cur.execute("INSERT INTO book_authors(book_id,author_id) VALUES (%s,%s)",
                    (ids["book"], ids["author"]))
        ids["copies"] = []
        for index in range(3):
            cur.execute("""INSERT INTO book_copies(book_id,barcode,shelf_code,acquired_at)
                VALUES (%s,%s,'TEST','2026-01-01')""", (ids["book"], prefix + f"-C{index}"))
            ids["copies"].append(cur.lastrowid)
        ids["readers"] = []
        for index in range(2):
            cur.execute("INSERT INTO readers(reader_no,name,email) VALUES (%s,%s,%s)",
                        (prefix + f"-R{index}", "Synthetic reader", prefix + f"-{index}@test.invalid"))
            ids["readers"].append(cur.lastrowid)
    return ids


def borrow(conn, ids, reader=0, copy=0, borrowed=BORROWED, due=DUE, returned=None):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO loans(reader_id,copy_id,borrowed_at,due_at,returned_at)
            VALUES (%s,%s,%s,%s,%s)""",
                    (ids["readers"][reader], ids["copies"][copy], borrowed, due, returned))
        return cur.lastrowid


def cleanup_committed_fixture(conn, ids):
    """Only used by the concurrent test, whose fixtures must be committed first."""
    conn.rollback()
    with conn.cursor() as cur:
        for copy_id in ids["copies"]:
            cur.execute("DELETE FROM loans WHERE copy_id=%s", (copy_id,))
            cur.execute("DELETE FROM book_copies WHERE copy_id=%s", (copy_id,))
        for reader_id in ids["readers"]:
            cur.execute("DELETE FROM readers WHERE reader_id=%s", (reader_id,))
        cur.execute("DELETE FROM book_authors WHERE book_id=%s", (ids["book"],))
        cur.execute("DELETE FROM books WHERE book_id=%s", (ids["book"],))
        cur.execute("DELETE FROM authors WHERE author_id=%s", (ids["author"],))
        cur.execute("DELETE FROM publishers WHERE publisher_id=%s", (ids["publisher"],))
        cur.execute("DELETE FROM categories WHERE category_id=%s", (ids["category"],))
    conn.commit()


class DatabaseConstraints(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.ids = insert_fixture(self.conn)

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def execute(self, sql, params=()):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else cur.rowcount

    def assert_rejected(self, sql, params, error_codes):
        try:
            self.execute(sql, params)
        except pymysql.MySQLError as error:
            self.assertIn(error.args[0], error_codes, f"Unexpected rejection: {error}")
        else:
            self.fail("The database accepted an invalid operation")

    def test_primary_key_rejects_duplicates(self):
        self.assert_rejected("INSERT INTO categories(category_id,name) VALUES (%s,%s)",
                             (self.ids["category"], self.ids["prefix"] + " other"), {1062})

    def test_foreign_key_rejects_orphans(self):
        self.assert_rejected("INSERT INTO book_authors(book_id,author_id) VALUES (%s,%s)",
                             (9_223_372_036_854_775_807, self.ids["author"]), {1452})

    def test_isbn_is_unique(self):
        self.assert_rejected("""INSERT INTO books(isbn,title,category_id,publisher_id,publication_year)
            VALUES (%s,'Another synthetic title',%s,%s,2026)""",
                             (self.ids["isbn"], self.ids["category"], self.ids["publisher"]), {1062})

    def test_copy_barcode_is_unique(self):
        self.assert_rejected("""INSERT INTO book_copies(book_id,barcode,shelf_code,acquired_at)
            VALUES (%s,%s,'TEST','2026-01-01')""",
                             (self.ids["book"], self.ids["prefix"] + "-C0"), {1062})

    def test_dates_rejected_on_insert(self):
        for due, returned in [(BORROWED, None), (DUE, BORROWED - timedelta(seconds=1))]:
            with self.subTest(due=due, returned=returned):
                try:
                    borrow(self.conn, self.ids, due=due, returned=returned)
                except pymysql.MySQLError as error:
                    self.assertIn(error.args[0], RULE_ERRORS)
                else:
                    self.fail("Invalid loan dates were accepted")

    def test_dates_rejected_on_update(self):
        loan = borrow(self.conn, self.ids)
        self.assert_rejected("UPDATE loans SET due_at=%s WHERE loan_id=%s", (BORROWED, loan), RULE_ERRORS)
        self.assert_rejected("UPDATE loans SET returned_at=%s WHERE loan_id=%s",
                             (BORROWED - timedelta(seconds=1), loan), RULE_ERRORS)
        row = self.execute("SELECT due_at,returned_at FROM loans WHERE loan_id=%s", (loan,))[0]
        self.assertEqual(row, {"due_at": DUE, "returned_at": None})

    def test_only_one_active_loan_per_copy(self):
        borrow(self.conn, self.ids)
        try:
            borrow(self.conn, self.ids, reader=1)
        except pymysql.MySQLError as error:
            self.assertIn(error.args[0], {1062, 1644})
        else:
            self.fail("Duplicate active copy was accepted")
        self.assertEqual(self.execute("SELECT COUNT(*) AS n FROM loans WHERE copy_id=%s AND returned_at IS NULL",
                                      (self.ids["copies"][0],))[0]["n"], 1)

    def test_return_releases_copy_for_new_loan(self):
        first = borrow(self.conn, self.ids)
        self.execute("UPDATE loans SET returned_at=%s WHERE loan_id=%s", (BORROWED + timedelta(days=1), first))
        second = borrow(self.conn, self.ids, reader=1, borrowed=BORROWED + timedelta(days=2))
        rows = self.execute("SELECT loan_id,active_copy_id FROM loans WHERE copy_id=%s ORDER BY loan_id",
                            (self.ids["copies"][0],))
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]["active_copy_id"])
        self.assertEqual(rows[1]["loan_id"], second)
        self.assertEqual(rows[1]["active_copy_id"], self.ids["copies"][0])

    def test_suspended_reader_cannot_borrow(self):
        self.execute("UPDATE readers SET status='SUSPENDED' WHERE reader_id=%s", (self.ids["readers"][0],))
        try:
            borrow(self.conn, self.ids)
        except pymysql.MySQLError as error:
            self.assertEqual(error.args[0], 1644)
        else:
            self.fail("A suspended reader could borrow")

    def test_non_service_copy_cannot_be_borrowed(self):
        for status in ("MAINTENANCE", "WITHDRAWN"):
            with self.subTest(status=status):
                self.execute("UPDATE book_copies SET status=%s WHERE copy_id=%s", (status, self.ids["copies"][0]))
                try:
                    borrow(self.conn, self.ids)
                except pymysql.MySQLError as error:
                    self.assertEqual(error.args[0], 1644)
                else:
                    self.fail("A non-service copy could be borrowed")

    def test_active_copy_cannot_enter_maintenance(self):
        borrow(self.conn, self.ids)
        self.assert_rejected("UPDATE book_copies SET status='MAINTENANCE' WHERE copy_id=%s",
                             (self.ids["copies"][0],), {1644})

    def test_suspended_reader_can_return_existing_loan(self):
        loan = borrow(self.conn, self.ids)
        self.execute("UPDATE readers SET status='SUSPENDED' WHERE reader_id=%s", (self.ids["readers"][0],))
        returned = BORROWED + timedelta(days=1)
        self.execute("UPDATE loans SET returned_at=%s WHERE loan_id=%s", (returned, loan))
        self.assertEqual(self.execute("SELECT returned_at FROM loans WHERE loan_id=%s", (loan,))[0]["returned_at"],
                         returned)

    def test_returned_history_cannot_be_reopened_or_changed(self):
        loan = borrow(self.conn, self.ids)
        self.execute("UPDATE loans SET returned_at=%s WHERE loan_id=%s", (BORROWED + timedelta(days=1), loan))
        self.assert_rejected("UPDATE loans SET returned_at=NULL WHERE loan_id=%s", (loan,), {1644})
        self.assert_rejected("UPDATE loans SET due_at=%s WHERE loan_id=%s", (DUE + timedelta(days=1), loan), {1644})

    def test_active_loan_identity_is_immutable(self):
        loan = borrow(self.conn, self.ids)
        for column, value in [("reader_id", self.ids["readers"][1]),
                              ("copy_id", self.ids["copies"][1]),
                              ("borrowed_at", BORROWED + timedelta(hours=1))]:
            with self.subTest(column=column):
                self.assert_rejected(f"UPDATE loans SET {column}=%s WHERE loan_id=%s", (value, loan), {1644})

    def test_borrow_transaction_rolls_back(self):
        self.execute("SAVEPOINT before_borrow")
        loan = borrow(self.conn, self.ids)
        self.execute("ROLLBACK TO SAVEPOINT before_borrow")
        self.assertEqual(self.execute("SELECT COUNT(*) AS n FROM loans WHERE loan_id=%s", (loan,))[0]["n"], 0)
        self.assertIsInstance(borrow(self.conn, self.ids), int)

    def test_return_transaction_rolls_back(self):
        loan = borrow(self.conn, self.ids)
        self.execute("SAVEPOINT before_return")
        self.execute("UPDATE loans SET returned_at=%s WHERE loan_id=%s", (BORROWED + timedelta(days=1), loan))
        self.execute("ROLLBACK TO SAVEPOINT before_return")
        self.assertIsNone(self.execute("SELECT returned_at FROM loans WHERE loan_id=%s", (loan,))[0]["returned_at"])

    def test_history_prevents_parent_deletion(self):
        borrow(self.conn, self.ids, returned=BORROWED + timedelta(days=1))
        self.assert_rejected("DELETE FROM readers WHERE reader_id=%s", (self.ids["readers"][0],), {1451})
        self.assert_rejected("DELETE FROM book_copies WHERE copy_id=%s", (self.ids["copies"][0],), {1451})


class ConcurrentBorrow(unittest.TestCase):
    def test_two_connections_only_one_can_borrow_same_copy(self):
        owner = connect()
        ids = None
        barrier = threading.Barrier(2)
        try:
            ids = insert_fixture(owner)
            owner.commit()

            def attempt(reader):
                conn = connect()
                try:
                    with conn.cursor() as cur:
                        cur.execute("SET SESSION innodb_lock_wait_timeout=10")
                    barrier.wait(timeout=10)
                    loan = borrow(conn, ids, reader=reader)
                    conn.commit()
                    return {"succeeded": True, "loan_id": loan}
                except pymysql.MySQLError as error:
                    conn.rollback()
                    return {"succeeded": False, "error_code": error.args[0]}
                finally:
                    conn.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(attempt, reader) for reader in (0, 1)]
                outcomes = [future.result(timeout=25) for future in futures]
            successes = [item for item in outcomes if item["succeeded"]]
            failures = [item for item in outcomes if not item["succeeded"]]
            self.assertEqual(len(successes), 1, outcomes)
            self.assertEqual(len(failures), 1, outcomes)
            self.assertIn(failures[0]["error_code"], {1062, 1213, 1644}, outcomes)
            with owner.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM loans WHERE copy_id=%s AND returned_at IS NULL",
                            (ids["copies"][0],))
                self.assertEqual(cur.fetchone()["n"], 1)
        finally:
            if ids is not None:
                cleanup_committed_fixture(owner, ids)
            owner.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
