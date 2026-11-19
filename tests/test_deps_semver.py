"""Tests for backend/deps/semver.py and the lockfile range check (BB-54)."""

import httpx
import pytest

from backend.deps import analyze
from backend.deps.semver import parse_version, satisfies
from backend.export._common import dependency_flags


def test_parse_version():
    assert parse_version("1.2.3") == (1, 2, 3, None)
    assert parse_version("v1.2.3-beta.1+build.5") == (1, 2, 3, "beta.1")
    assert parse_version("1.2") is None
    assert parse_version("git+https://github.com/a/b.git") is None


@pytest.mark.parametrize(
    ("version", "range_str"),
    [
        ("5.3.0", "^5.3.0"),
        ("5.9.1", "^5.3.0"),
        ("0.2.9", "^0.2.3"),
        ("0.0.3", "^0.0.3"),
        ("1.9.0", "^1"),
        ("0.1.5", "^0.1"),
        ("1.2.9", "~1.2.3"),
        ("1.2.0", "~1.2"),
        ("1.9.0", "~1"),
        ("1.2.3", "1.2.3"),
        ("1.2.3", "=1.2.3"),
        ("1.2.7", "1.2.x"),
        ("1.4.0", "1"),
        ("3.0.0", "*"),
        ("3.0.0", ""),
        ("2.0.0", ">=1.2.0 <3"),
        ("2.0.0", ">= 1.2.0 < 3.0.0"),
        ("1.5.0", "1.2.3 - 2.3"),
        ("2.3.9", "1.2.3 - 2.3"),
        ("2.0.0", "^1.0.0 || ^2.0.0"),
        ("1.3.0", ">1.2"),
        ("1.2.9", "<=1.2"),
        ("1.2.3", ">=1.2.3-beta"),
    ],
)
def test_satisfies_inside(version, range_str):
    assert satisfies(version, range_str) is True


@pytest.mark.parametrize(
    ("version", "range_str"),
    [
        ("2.4.2", "^5.3.0"),  # the bug-bash case
        ("6.0.0", "^5.3.0"),
        ("0.3.0", "^0.2.3"),
        ("0.0.4", "^0.0.3"),
        ("0.2.0", "^0.1"),
        ("1.3.0", "~1.2.3"),
        ("2.0.0", "~1"),
        ("1.2.4", "1.2.3"),
        ("1.3.0", "1.2.x"),
        ("3.0.0", ">=1.2.0 <3"),
        ("2.4.0", "1.2.3 - 2.3"),
        ("1.2.2", "1.2.3 - 2.3"),
        ("3.0.0", "^1.0.0 || ^2.0.0"),
        ("1.2.9", ">1.2"),
        ("1.3.0", "<=1.2"),
        ("1.2.3", "<1.2.3-beta"),
    ],
)
def test_satisfies_outside(version, range_str):
    assert satisfies(version, range_str) is False


@pytest.mark.parametrize(
    ("version", "range_str"),
    [
        ("1.0.0", "github:user/repo#v1"),
        ("1.0.0", "git+https://github.com/a/b.git"),
        ("1.0.0", "file:../local"),
        ("1.0.0", "npm:other@^1.0.0"),
        ("1.0.0", "workspace:*"),
        ("1.0.0", "latest"),
        ("1.0.0-beta.1", "^1.0.0"),  # prerelease pins aren't modelled
        ("not-a-version", "^1.0.0"),
        ("1.0.0", "1.x.3"),
        ("1.0.0", "<*"),
    ],
)
def test_satisfies_unknown(version, range_str):
    assert satisfies(version, range_str) is None


def test_or_range_with_one_unreadable_side_is_unknown_not_false():
    assert satisfies("3.0.0", "^1.0.0 || latest") is None
    assert satisfies("1.5.0", "^1.0.0 || latest") is True


def _not_found_registry() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(404, json={"error": "Not found"}))
    )


def _lockfile(pins: dict[str, str]) -> dict:
    return {
        "lockfileVersion": 3,
        "packages": {f"node_modules/{name}": {"version": v} for name, v in pins.items()},
    }


@pytest.mark.asyncio
async def test_manifest_marks_a_lockfile_pin_outside_the_range():
    manifest = {"dependencies": {"chalk": "^5.3.0", "lodash": "^4.17.0", "local": "file:../x"}}
    lockfile = _lockfile({"chalk": "2.4.2", "lodash": "4.17.21", "local": "1.0.0"})

    async with _not_found_registry() as client:
        context = await analyze.analyze_manifest(manifest, lockfile, client=client)

    by_name = {pa.ref.name: pa for pa in context.packages}
    # The pinned version is what gets analysed; the record carries the range it missed.
    assert by_name["chalk"].ref.version == "2.4.2"
    assert by_name["chalk"].lockfile_out_of_range == "^5.3.0"
    assert by_name["lodash"].lockfile_out_of_range is None
    assert by_name["local"].lockfile_out_of_range is None


@pytest.mark.asyncio
async def test_a_floor_pin_without_a_lockfile_is_never_flagged():
    async with _not_found_registry() as client:
        context = await analyze.analyze_manifest(
            {"dependencies": {"a": "^1.2.3"}}, None, client=client
        )

    assert [pa.lockfile_out_of_range for pa in context.packages] == [None]


@pytest.mark.asyncio
async def test_the_warning_reaches_the_scan_row():
    manifest = {"dependencies": {"chalk": "^5.3.0"}}
    async with _not_found_registry() as client:
        context = await analyze.analyze_manifest(
            manifest, _lockfile({"chalk": "2.4.2"}), client=client
        )

    [(package, version, row)] = analyze.dependency_scan_rows(context)
    assert (package, version, row["lockfile_out_of_range"]) == ("chalk", "2.4.2", "^5.3.0")


def test_export_flags_show_the_mismatch():
    assert "lock-mismatch" in dependency_flags({"lockfile_out_of_range": "^5.3.0"})
    assert "lock-mismatch" not in dependency_flags({"lockfile_out_of_range": None})
