"""Offline dependency analysis: backend.deps.resolved_cache plus the fallback in
backend.deps.analyze.analyze_package (BB-85).

Every test warms a temp cache through the real resolver + fetcher against an
httpx.MockTransport, then cuts the network. Semgrep is stubbed: these tests
cover resolution and fetching, not scanning.
"""

import base64
import hashlib
import io
import json
import tarfile

import httpx
import pytest

from backend.deps import analyze, fetcher, resolved_cache
from backend.deps.resolver import github_tarball_url
from backend.models.dependencies import CapabilityProfile, ResolvedPackage
from backend.models.enums import SourceKind


_REGISTRY_URL = "https://registry.npmjs.org/pkg"
_TARBALL_URL = "https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz"
_GIT_HEAD = "abc123"
_GITHUB_URL = github_tarball_url("o", "r", _GIT_HEAD)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher.settings, "deps_cache_dir", str(tmp_path))
    fetcher._locks.clear()
    fetcher._lock_refcounts.clear()
    fetcher._in_use.clear()


@pytest.fixture(autouse=True)
def _stub_scanner(monkeypatch):
    async def fake_scan(path, kind, name, version):
        return CapabilityProfile(name=name, version=version, source_kind=kind, status="ok")

    monkeypatch.setattr(analyze, "scan_source", fake_scan)


def _tar_gz(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


_PACKAGE_JSON = b'{"name": "pkg", "version": "1.0.0"}'
_NPM_TARBALL = _tar_gz(
    {"package/index.js": b"module.exports = 1;\n", "package/package.json": _PACKAGE_JSON}
)
_GITHUB_TARBALL = _tar_gz(
    {
        f"r-{_GIT_HEAD}/index.js": b"module.exports = 1;\n",
        f"r-{_GIT_HEAD}/package.json": _PACKAGE_JSON,
    }
)


def _registry_doc() -> dict:
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(_NPM_TARBALL).digest()).decode()
    return {
        "name": "pkg",
        "versions": {
            "1.0.0": {
                "dist": {"tarball": _TARBALL_URL, "integrity": integrity},
                "repository": {"type": "git", "url": "git+https://github.com/o/r.git"},
                "gitHead": _GIT_HEAD,
                "_npmUser": {"name": "alice"},
            }
        },
        "time": {"1.0.0": "2024-01-01T00:00:00.000Z"},
    }


def _online_client(registry_status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == _REGISTRY_URL:
            if registry_status != 200:
                return httpx.Response(registry_status, json={"error": "Not found"})
            return httpx.Response(200, json=_registry_doc())
        if url == _TARBALL_URL:
            return httpx.Response(200, content=_NPM_TARBALL)
        if url == _GITHUB_URL:
            return httpx.Response(200, content=_GITHUB_TARBALL if request.method == "GET" else b"")
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _offline_client(requests: list[str], error: type[httpx.TransportError] = httpx.ConnectError):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(f"{request.method} {request.url}")
        raise error("network is down", request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _warm(source_mode: str = "both") -> None:
    async with _online_client() as client:
        result = await analyze.analyze_package("pkg", "1.0.0", source_mode, client)
    assert result.resolved_from_cache is False


# ---------------------------------------------------------------------------
# Offline fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError])
async def test_offline_with_warm_cache_uses_cached_metadata(error):
    await _warm("both")

    requests: list[str] = []
    async with _offline_client(requests, error) as client:
        result = await analyze.analyze_package("pkg", "1.0.0", "both", client)

    assert result.error is None
    assert result.resolved_from_cache is True
    assert result.resolved.publisher == "alice"
    assert result.resolved.github_status == "resolved"
    assert result.resolved.github_ref == _GIT_HEAD
    assert result.npm_profile is not None
    assert result.github_profile is not None
    assert result.drift is not None
    assert result.drift.status != "skipped_github_unavailable"
    # Only the failed registry lookup: no GitHub probe, no tarball download.
    assert requests == [f"GET {_REGISTRY_URL}"]


@pytest.mark.asyncio
async def test_offline_npm_mode_does_not_report_a_github_resolution():
    await _warm("both")

    requests: list[str] = []
    async with _offline_client(requests) as client:
        result = await analyze.analyze_package("pkg", "1.0.0", "npm", client)

    assert result.resolved_from_cache is True
    assert result.npm_profile is not None
    assert result.resolved.github_status == "not_attempted"
    assert result.resolved.github_ref is None
    assert requests == [f"GET {_REGISTRY_URL}"]


@pytest.mark.asyncio
async def test_offline_github_probed_when_github_source_not_cached():
    await _warm("npm")  # cached metadata, but no GitHub ref and no GitHub source

    requests: list[str] = []
    async with _offline_client(requests) as client:
        result = await analyze.analyze_package("pkg", "1.0.0", "both", client)

    assert result.error is None
    assert result.resolved_from_cache is True
    assert result.npm_profile is not None
    assert result.resolved.github_status == "unavailable"
    assert result.drift.status == "skipped_github_unavailable"


@pytest.mark.asyncio
async def test_offline_without_cached_metadata_gives_a_clear_error():
    requests: list[str] = []
    async with _offline_client(requests) as client:
        with pytest.raises(analyze.RegistryUnreachableError, match="no cached metadata"):
            await analyze.analyze_package("pkg", "1.0.0", "npm", client)

        context = await analyze.analyze_manifest(
            {"dependencies": {"pkg": "1.0.0"}}, None, source_mode="npm", client=client
        )

    [pa] = context.packages
    assert "registry unreachable and no cached metadata" in pa.error
    assert pa.resolved_from_cache is False


@pytest.mark.asyncio
async def test_registry_404_does_not_fall_back_to_cache():
    await _warm("npm")

    async with _online_client(registry_status=404) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await analyze.analyze_package("pkg", "1.0.0", "npm", client)


@pytest.mark.asyncio
async def test_version_missing_from_registry_does_not_fall_back_to_cache():
    # Cached metadata for a version the registry no longer lists (unpublished):
    # the registry's answer wins.
    await resolved_cache.save_resolved(
        ResolvedPackage(name="pkg", version="2.0.0", tarball_url=_TARBALL_URL, integrity="x")
    )

    async with _online_client() as client:
        with pytest.raises(ValueError, match="not found on the npm registry"):
            await analyze.analyze_package("pkg", "2.0.0", "npm", client)


# ---------------------------------------------------------------------------
# What gets cached, and where
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolved_metadata_lives_outside_the_source_cache(tmp_path):
    await _warm("both")

    npm_dir = fetcher.cache_dir_for(SourceKind.NPM_TARBALL, "pkg", "1.0.0")
    github_dir = fetcher.cache_dir_for(SourceKind.GITHUB, "pkg", "1.0.0")
    # Exactly the extracted source plus the marker — anything else would be
    # scanned by Semgrep and read by drift as a tarball-only file.
    assert sorted(p.name for p in npm_dir.iterdir()) == [".complete", "index.js", "package.json"]
    assert sorted(p.name for p in github_dir.iterdir()) == [".complete", "index.js", "package.json"]

    resolved_dir = tmp_path / "_resolved"
    assert [p.name for p in resolved_dir.iterdir()] == ["pkg@1.0.0.json"]
    saved = json.loads((resolved_dir / "pkg@1.0.0.json").read_text(encoding="utf-8"))
    assert saved["github_ref"] == _GIT_HEAD


@pytest.mark.asyncio
async def test_npm_only_resolve_keeps_a_previously_cached_github_ref():
    await _warm("both")
    await _warm("npm")

    cached = await resolved_cache.load_cached_resolved("pkg", "1.0.0")
    assert cached.github_status == "resolved"
    assert cached.github_ref == _GIT_HEAD


@pytest.mark.asyncio
async def test_failed_write_leaves_previous_metadata_and_no_temp_file(tmp_path, monkeypatch):
    original = ResolvedPackage(
        name="pkg", version="1.0.0", tarball_url=_TARBALL_URL, integrity="sha512-AAAA"
    )
    await resolved_cache.save_resolved(original)

    def failing_replace(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(resolved_cache.Path, "replace", failing_replace)
    # Must not raise: the analysis already resolved fine.
    await resolved_cache.save_resolved(original.model_copy(update={"publisher": "mallory"}))

    assert [p.name for p in (tmp_path / "_resolved").iterdir()] == ["pkg@1.0.0.json"]
    loaded = await resolved_cache.load_cached_resolved("pkg", "1.0.0")
    assert loaded == original


@pytest.mark.asyncio
async def test_corrupt_or_mismatched_cache_file_is_ignored():
    path = resolved_cache.resolved_path_for("pkg", "1.0.0")
    path.parent.mkdir(parents=True)

    path.write_text("{not json", encoding="utf-8")
    assert await resolved_cache.load_cached_resolved("pkg", "1.0.0") is None

    other = ResolvedPackage(name="other", version="1.0.0", tarball_url="x", integrity="y")
    path.write_text(other.model_dump_json(), encoding="utf-8")
    assert await resolved_cache.load_cached_resolved("pkg", "1.0.0") is None


@pytest.mark.asyncio
async def test_unsafe_name_is_never_used_as_a_path():
    assert await resolved_cache.load_cached_resolved("../../etc", "1.0.0") is None


@pytest.mark.asyncio
async def test_eviction_leaves_resolved_metadata_alone(tmp_path, monkeypatch):
    await _warm("npm")
    monkeypatch.setattr(fetcher.settings, "deps_cache_max_gb", 1e-12)

    fetcher._evict_cache_entries_over_budget()

    assert not fetcher.is_cached(SourceKind.NPM_TARBALL, "pkg", "1.0.0")
    assert (tmp_path / "_resolved" / "pkg@1.0.0.json").is_file()
