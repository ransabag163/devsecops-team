import os

import config


def test_load_env_reads_key_value_lines(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_KEY", raising=False)
    monkeypatch.delenv("DEMO_QUOTED", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('# a comment\n\nDEMO_KEY=abc\nDEMO_QUOTED = "x y"\nnot a pair\n')

    config.load_env(env_file)

    assert os.environ["DEMO_KEY"] == "abc"
    assert os.environ["DEMO_QUOTED"] == "x y"
    monkeypatch.delenv("DEMO_KEY")
    monkeypatch.delenv("DEMO_QUOTED")


def test_load_env_does_not_override_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_KEY", "from-env")
    env_file = tmp_path / ".env"
    env_file.write_text("DEMO_KEY=from-file\n")

    config.load_env(env_file)

    assert os.environ["DEMO_KEY"] == "from-env"


def test_missing_env_file_is_fine(tmp_path):
    config.load_env(tmp_path / "missing.env")


def test_every_agent_provider_exists():
    for provider in config.AGENT_PROVIDER.values():
        assert provider in config.PROVIDERS
