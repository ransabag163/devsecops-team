"""Normal behavior of samples/login.py. Must pass on the original and on a good fix."""

import sqlite3

import pytest

from behavior_helpers import command_words


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (name TEXT, role TEXT)")
    conn.executemany("INSERT INTO users VALUES (?, ?)", [("ran", "admin"), ("dana", "user")])
    yield conn
    conn.close()


def test_find_user_returns_the_user(sample, conn):
    assert sample.find_user(conn, "ran") == ("ran", "admin")


def test_find_user_unknown_name_returns_none(sample, conn):
    assert sample.find_user(conn, "nobody") is None


def test_find_user_safe_still_works(sample, conn):
    assert sample.find_user_safe(conn, "dana") == ("dana", "user")


def test_backup_db_copies_the_database(sample, commands):
    sample.backup_db("backup.db")

    assert len(commands) == 1
    words = command_words(commands[0])
    assert "cp" in words and "users.db" in words and "backup.db" in words


def test_db_password_still_exists(sample):
    assert hasattr(sample, "DB_PASSWORD")
