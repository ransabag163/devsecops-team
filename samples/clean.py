"""A small module with no known weaknesses (used by the tests)."""

import os
import subprocess

DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
api_token = ""


def find_user(conn, username):
    query = "SELECT * FROM users WHERE name = ?"
    return conn.execute(query, (username,)).fetchone()


def backup_db(target):
    subprocess.run(["cp", "users.db", target])
