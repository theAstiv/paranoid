"""Tests for the config KV CRUD in backend/db/crud.py."""

import pytest

from backend.config import settings
from backend.db.crud import (
    delete_config_value,
    get_config_value,
    set_config_value,
)
from backend.security import source_key


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.delenv("CONFIG_SECRET", raising=False)
    source_key._reset_cache_for_tests()
    yield
    source_key._reset_cache_for_tests()


@pytest.mark.asyncio
async def test_config_kv_roundtrip(test_db):
    """Plaintext + encrypted values roundtrip; *_api_key is auto-encrypted."""
    await set_config_value("similarity_threshold_override", "0.91", encrypted=False)
    assert await get_config_value("similarity_threshold_override") == "0.91"

    # Caller passed encrypted=False but the key is secret — CRUD must force.
    await set_config_value("anthropic_api_key", "sk-ant-xyz", encrypted=False)
    assert await get_config_value("anthropic_api_key") == "sk-ant-xyz"


@pytest.mark.asyncio
async def test_config_kv_upsert_preserves_latest(test_db):
    await set_config_value("anthropic_api_key", "first", encrypted=True)
    await set_config_value("anthropic_api_key", "second", encrypted=True)
    assert await get_config_value("anthropic_api_key") == "second"


@pytest.mark.asyncio
async def test_config_kv_delete(test_db):
    await set_config_value("openai_api_key", "tmp", encrypted=True)
    await delete_config_value("openai_api_key")
    assert await get_config_value("openai_api_key") is None


@pytest.mark.asyncio
async def test_config_kv_missing_returns_none(test_db):
    assert await get_config_value("never_set") is None


@pytest.mark.asyncio
async def test_config_decrypt_failure_raises_patdecryptionerror(test_db, monkeypatch):
    """Ciphertext written under key A is unreadable after key source flips."""
    monkeypatch.setenv("CONFIG_SECRET", "secret-A")
    source_key._reset_cache_for_tests()
    await set_config_value("anthropic_api_key", "sk-ant-value", encrypted=True)

    monkeypatch.setenv("CONFIG_SECRET", "secret-B")
    source_key._reset_cache_for_tests()
    with pytest.raises(source_key.PATDecryptionError):
        await get_config_value("anthropic_api_key")
