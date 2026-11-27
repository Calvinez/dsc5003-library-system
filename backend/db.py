"""Shared MySQL connection settings. Never put a password in source or argv."""
from __future__ import annotations

import os


def connect():
    """Connect with a transaction and dictionary rows; import driver lazily."""
    if "DB_PASSWORD" not in os.environ:
        raise RuntimeError("DB_PASSWORD is required (an explicitly empty value is allowed).")
    try:
        port = int(os.environ.get("DB_PORT", "3306"))
    except ValueError as exc:
        raise RuntimeError("DB_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("DB_PORT must be between 1 and 65535.")
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("Install requirements.txt before connecting to MySQL.") from exc
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=port,
        user=os.environ.get("DB_USER", "library_app"),
        password=os.environ["DB_PASSWORD"],
        database=os.environ.get("DB_NAME", "library_project"),
        charset="utf8mb4",
        init_command=("SET SESSION sql_mode='STRICT_TRANS_TABLES,NO_ZERO_DATE,"
                      "NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION',"
                      "time_zone='+08:00'"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=10,
        read_timeout=120,
        write_timeout=120,
    )
