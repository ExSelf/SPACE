import pytest


@pytest.fixture(autouse=True)
def packet_hmac_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUN_PACKET_HMAC_KEY", "test-only-shared-key-for-packet-tests")
