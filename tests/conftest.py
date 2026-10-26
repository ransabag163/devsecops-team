import pytest

import models.llm_adapter


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    """Tests must never call the real model API."""
    def fail(*args, **kwargs):
        raise AssertionError("a test tried to call the real API")

    monkeypatch.setattr(models.llm_adapter, "urllib_transport", fail)
