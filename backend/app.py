"""HTTP API for the library database delivered by member A."""
import json
import os
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from pathlib import Path
from time import sleep

import pymysql
from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from db import connect


class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status = status
        self.code = code
        self.message = message


def now():
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None, microsecond=0)


def query(sql, params):
    with closing(connect()) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def write(operation):
    for attempt in range(3):
        with closing(connect()) as conn, conn.cursor() as cur:
            try:
                conn.begin()
                result = operation(cur)
                conn.commit()
                return result
            except Exception as exc:
                conn.rollback()
                if isinstance(exc, pymysql.MySQLError) and exc.args[0] in (1205, 1213):
                    if attempt == 2:
                        raise ApiError(503, "busy", "系统繁忙，请重试") from exc
                else:
                    raise
        sleep(0.03 * (attempt + 1))


def require_reader():
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer":
        for secret, reader_no in g.tokens.items():
            if compare_digest(token.encode(), secret.encode()):
                return reader_no
    raise ApiError(401, "unauthorized", "请提供有效的读者令牌")


def borrow(cur, reader_no, barcode):
    cur.execute("SELECT reader_id,status FROM readers WHERE reader_no=%s FOR UPDATE", (reader_no,))
    reader = cur.fetchone()
    if not reader or reader["status"] != "ACTIVE":
        raise ApiError(403, "reader_inactive", "读者账号不可借阅")
    cur.execute("SELECT copy_id,status FROM book_copies WHERE barcode=%s FOR UPDATE", (barcode,))
    copy = cur.fetchone()
    if not copy:
        raise ApiError(404, "copy_not_found", "找不到该副本")
    if copy["status"] != "IN_SERVICE":
        raise ApiError(409, "copy_unavailable", "该副本不可借")
    cur.execute("SELECT loan_id FROM loans WHERE active_copy_id=%s FOR UPDATE", (copy["copy_id"],))
    if cur.fetchone():
        raise ApiError(409, "already_on_loan", "该副本已借出")
    borrowed_at = now()
    due_at = borrowed_at + timedelta(days=14)
    try:
        cur.execute(
            "INSERT INTO loans(reader_id,copy_id,borrowed_at,due_at) VALUES (%s,%s,%s,%s)",
            (reader["reader_id"], copy["copy_id"], borrowed_at, due_at),
        )
    except pymysql.IntegrityError as exc:
        if exc.args[0] == 1062 and "uq_loans_active_copy" in str(exc):
            raise ApiError(409, "already_on_loan", "该副本已借出") from exc
        raise
    return {"loan_id": cur.lastrowid, "barcode": barcode, "borrowed_at": borrowed_at, "due_at": due_at}


def return_copy(cur, reader_no, loan_id):
    cur.execute("SELECT reader_id FROM readers WHERE reader_no=%s", (reader_no,))
    reader = cur.fetchone()
    if not reader:
        raise ApiError(404, "loan_not_found", "找不到该借阅记录")
    cur.execute(
        "SELECT returned_at,borrowed_at FROM loans WHERE loan_id=%s AND reader_id=%s FOR UPDATE",
        (loan_id, reader["reader_id"]),
    )
    loan = cur.fetchone()
    if not loan:
        raise ApiError(404, "loan_not_found", "找不到该借阅记录")
    if loan["returned_at"] is not None:
        return {"loan_id": loan_id, "returned_at": loan["returned_at"], "already_returned": True}
    returned_at = now()
    if returned_at < loan["borrowed_at"]:
        raise ApiError(409, "invalid_return_time", "归还时间早于借阅时间")
    cur.execute("UPDATE loans SET returned_at=%s WHERE loan_id=%s", (returned_at, loan_id))
    return {"loan_id": loan_id, "returned_at": returned_at, "already_returned": False}


def create_app():
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    app = Flask(__name__, static_folder=frontend, static_url_path="/assets")
    app.config["MAX_CONTENT_LENGTH"] = 8192
    tokens = json.loads(os.environ.get("LIBRARY_READER_TOKENS", "{}"))
    if not isinstance(tokens, dict) or any(
        not key or not isinstance(value, str) or not 1 <= len(value) <= 32
        for key, value in tokens.items()
    ):
        raise RuntimeError("LIBRARY_READER_TOKENS must map token strings to reader numbers")
    origin = os.environ.get("LIBRARY_FRONTEND_ORIGIN")

    @app.before_request
    def set_tokens():
        g.tokens = tokens

    @app.after_request
    def cors(response):
        if origin and request.headers.get("Origin") == origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.vary.add("Origin")
        return response

    @app.errorhandler(ApiError)
    def api_error(exc):
        return jsonify(error={"code": exc.code, "message": exc.message}), exc.status

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error={"code": exc.name.lower().replace(" ", "_"), "message": exc.description}), exc.code

    @app.errorhandler(pymysql.MySQLError)
    def database_error(exc):
        if exc.args and exc.args[0] == 1644:
            return api_error(ApiError(409, "rule_rejected", "数据库拒绝了该借阅操作"))
        app.logger.error("MySQL operation failed (code %s)", exc.args[0] if exc.args else "unknown")
        return api_error(ApiError(503, "database_error", "数据库暂时无法完成请求"))

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/books")
    def books():
        prefix = request.args.get("q", "").strip()
        if len(prefix) > 255:
            raise ApiError(400, "invalid_query", "搜索词过长")
        pattern = prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        return jsonify(items=query("""
            SELECT b.book_id,b.isbn,b.title,c.name AS category,p.name AS publisher
            FROM books b JOIN categories c USING(category_id) JOIN publishers p USING(publisher_id)
            WHERE b.title LIKE %s ESCAPE '!' ORDER BY b.title,b.book_id LIMIT 20
        """, (pattern,)))

    @app.get("/api/books/<isbn>/copies")
    def copies(isbn):
        if len(isbn) != 13 or not isbn.isascii() or not isbn.isdecimal():
            raise ApiError(400, "invalid_isbn", "ISBN 必须为 13 位数字")
        return jsonify(items=query("""
            SELECT b.isbn,b.title,bc.copy_id,bc.barcode,bc.shelf_code,
                CASE WHEN l.loan_id IS NOT NULL THEN 'ON_LOAN'
                     WHEN bc.status='IN_SERVICE' THEN 'AVAILABLE' ELSE bc.status END AS availability
            FROM books b JOIN book_copies bc USING(book_id)
            LEFT JOIN loans l ON l.active_copy_id=bc.copy_id
            WHERE b.isbn=%s ORDER BY bc.copy_id
        """, (isbn,)))

    @app.get("/api/loans")
    def loans():
        reader_no = require_reader()
        return jsonify(items=query("""
            SELECT l.loan_id,b.title,bc.barcode,l.borrowed_at,l.due_at,l.returned_at
            FROM readers r JOIN loans l USING(reader_id)
            JOIN book_copies bc USING(copy_id) JOIN books b USING(book_id)
            WHERE r.reader_no=%s ORDER BY l.borrowed_at DESC,l.loan_id DESC LIMIT 100
        """, (reader_no,)))

    @app.post("/api/loans")
    def create_loan():
        reader_no = require_reader()
        body = request.get_json(silent=True)
        barcode = body.get("barcode") if isinstance(body, dict) else None
        if not isinstance(barcode, str) or not 1 <= len(barcode.strip()) <= 40:
            raise ApiError(400, "invalid_barcode", "请提供有效的副本条码")
        return jsonify(write(lambda cur: borrow(cur, reader_no, barcode.strip()))), 201

    @app.post("/api/loans/<int:loan_id>/return")
    def close_loan(loan_id):
        reader_no = require_reader()
        if not 1 <= loan_id <= 2**64 - 1:
            raise ApiError(400, "invalid_loan_id", "借阅编号无效")
        return jsonify(write(lambda cur: return_copy(cur, reader_no, loan_id)))

    # Keep MySQL DATETIME values in the documented +08:00 business timezone.
    default_json = app.json.default
    app.json.default = lambda value: (
        value.replace(tzinfo=timezone(timedelta(hours=8))).isoformat()
        if isinstance(value, datetime) else default_json(value)
    )
    return app
