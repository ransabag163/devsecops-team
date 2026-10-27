import pytest

import config
import models.llm_adapter


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    """Tests must never call the real model API."""
    def fail(*args, **kwargs):
        raise AssertionError("a test tried to call the real API")

    monkeypatch.setattr(models.llm_adapter, "urllib_transport", fail)


@pytest.fixture(autouse=True)
def no_real_waiting(monkeypatch):
    """Retries and the request gap never really sleep in tests."""
    monkeypatch.setattr(models.llm_adapter, "real_sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def private_work_dir(tmp_path, monkeypatch):
    """Tests never create or remove run folders in the real .work/, nor write to reports/."""
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / ".work")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
