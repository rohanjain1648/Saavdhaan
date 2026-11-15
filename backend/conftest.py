"""Test-wide safety: tests must never ask Wajo Fo to text, email or call anyone."""
import pytest


@pytest.fixture(autouse=True)
def _no_real_fo_alerts(monkeypatch, request):
    if "test_fo_client" not in request.node.nodeid:   # those tests set their own Fo environment
        monkeypatch.setenv("FO_ALERTS", "off")
