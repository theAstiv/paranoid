"""Source-id validation in backend/sources/paths.py (CodeQL path-injection group)."""

import uuid

import pytest

from backend.config import settings
from backend.sources.paths import clone_dir_for, data_dir, index_db_for


BAD_IDS = [
    "",
    "../x",
    "..\\x",
    "a/b",
    "0123456789ABCDEF0123456789ABCDEF",  # uppercase
    "0123456789abcdef0123456789abcde",  # 31 chars
    "0123456789abcdef0123456789abcdef0",  # 33 chars
    "0123456789abcdef0123456789abcdeg",  # non-hex
    "0123456789abcdef0123456789abcdef\n",  # trailing newline slips past `$`
    "abc123",
]


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))


@pytest.mark.parametrize("bad", BAD_IDS)
def test_clone_dir_for_rejects_malformed_ids(bad):
    with pytest.raises(ValueError, match="32 lowercase hex"):
        clone_dir_for(bad)


@pytest.mark.parametrize("bad", BAD_IDS)
def test_index_db_for_rejects_malformed_ids(bad):
    with pytest.raises(ValueError, match="32 lowercase hex"):
        index_db_for(bad)


def test_valid_uuid_hex_round_trips():
    sid = uuid.uuid4().hex
    assert clone_dir_for(sid) == data_dir() / "sources" / sid
    assert index_db_for(sid).name == f"{sid}.db"
