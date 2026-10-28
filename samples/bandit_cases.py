"""Weaknesses that only Bandit finds (used by the tests).

analyze_code has no rules for them, and there are no attack tests for them,
so every finding here is Bandit-only and its card is always needs_you.
yaml and requests are imported inside their functions, so the works tests can
load this file without those packages.
"""

import hashlib
import pickle


def read_value():
    return eval(input("value: "))


def save_session(session):
    return pickle.dumps(session)


def load_session(data):
    return pickle.loads(data)


def read_config(text):
    import yaml
    return yaml.load(text)


def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()


def fetch(url):
    import requests
    return requests.get(url, verify=False, timeout=10)
