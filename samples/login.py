"""A small login module with three known weaknesses (used by the tests)."""

import subprocess

DB_PASSWORD = "hunter2"


def find_user(conn, username):
    query = "SELECT * FROM users WHERE name = '" + username + "'"
    return conn.execute(query).fetchone()


def find_user_safe(conn, username):
    return conn.execute("SELECT * FROM users WHERE name = ?", (username,)).fetchone()


def backup_db(target):
    subprocess.run("cp users.db " + target, shell=True)
