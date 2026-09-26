"""Offline tests for backend.deps.fetcher — safe tarball fetch, integrity, extraction.

All network access is mocked via httpx.MockTransport. Hostile tarballs are built
in-memory; none of them are ever executed, only fed through the safe extractor.
"""

import asyncio
import base64
import errno
import hashlib
import io
import json
import os
import tarfile

import httpx
import pytest

from backend.deps import fetcher
from backend.models.dependencies import ResolvedPackage
from backend.models.enums import SourceKind


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Point deps_cache_dir at a per-test temp directory and reset the lock table."""
    monkeypatch.setattr(fetcher.settings, "deps_cache_dir", str(tmp_path))
    fetcher._locks.clear()
    fetcher._lock_refcounts.clear()


def _resolved(
    name="pkg", version="1.0.0", integrity=None, tarball_url="https://registry.npmjs.org/pkg.tgz"
):
    return ResolvedPackage(
        name=name,
        version=version,
        tarball_url=tarball_url,
        integrity=integrity or "",
    )


def _build_tar_gz(builder) -> bytes:
    """`builder(tar)` adds members to an open tarfile.TarFile; returns the gzip bytes."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        builder(tar)
    return buf.getvalue()


def _add_file(tar: tarfile.TarFile, name: str, content: bytes = b"hello") -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))


def _normal_tarball_bytes() -> bytes:
    def build(tar):
        _add_file(tar, "package/index.js", b"module.exports = 1;\n")
        _add_file(tar, "package/package.json", b'{"name": "pkg", "version": "1.0.0"}')

    return _build_tar_gz(build)


def _integrity_for(data: bytes) -> str:
    digest = hashlib.sha512(data).digest()
    return "sha512-" + base64.b64encode(digest).decode()


def _client(content: bytes, *, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _github_resolved(name="pkg", version="1.0.0", repo_directory=None) -> ResolvedPackage:
    return ResolvedPackage(
        name=name,
        version=version,
        tarball_url="https://registry.npmjs.org/pkg.tgz",
        integrity="",
        repo_owner="o",
        repo_name="r",
        repo_directory=repo_directory,
        github_status="resolved",
        github_ref="v1.0.0",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_valid_npm_tarball_extracts_and_marks_complete():
    data = _normal_tarball_bytes()
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path is not None
    assert (result.path / ".complete").is_file()
    assert (result.path / "index.js").is_file()  # wrapper "package/" stripped during extraction


@pytest.mark.asyncio
async def test_fetch_with_no_integrity_at_all_rejected():
    """An npm tarball with neither dist.integrity nor dist.shasum must fail closed.

    This is vanishingly rare on the real registry, but the module never fetches
    an npm tarball unverified.
    """
    data = _normal_tarball_bytes()
    resolved = _resolved(integrity="")

    async with _client(data) as client:
        with pytest.raises(fetcher.IntegrityError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_github_fetch_uses_shared_url_builder():
    """The fetch URL must be built by resolver.github_tarball_url, matching the probe."""

    def build(tar):
        _add_file(tar, "r-abc123/index.js", b"x")
        _add_file(tar, "r-abc123/package.json", b'{"name": "pkg"}')

    data = _build_tar_gz(build)
    resolved = _github_resolved()
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, content=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert requested == [fetcher.github_tarball_url("o", "r", "v1.0.0")]


@pytest.mark.asyncio
async def test_github_monorepo_directory_found():
    data = _build_tar_gz(lambda tar: _add_file(tar, "r-v1.0.0/packages/core/index.js", b"x"))
    resolved = _github_resolved(repo_directory="packages/core")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert (result.path / "index.js").is_file()


@pytest.mark.asyncio
async def test_github_package_discovered_in_subdirectory():
    """The esbuild shape: no `repository.directory` declared, and the
    wrapper-root has no package.json at all (a Go-language monorepo) — the
    npm package actually lives at `npm/esbuild/`. Discovery must find it by
    reading every non-`node_modules` package.json's declared name."""

    def build(tar):
        _add_file(tar, "esbuild-v0.28.2/main.go", b"package main")
        _add_file(tar, "esbuild-v0.28.2/npm/esbuild/package.json", b'{"name": "esbuild"}')
        _add_file(tar, "esbuild-v0.28.2/npm/esbuild/lib/main.js", b"module.exports = {};")
        _add_file(
            tar,
            "esbuild-v0.28.2/npm/esbuild/node_modules/dep/package.json",
            b'{"name": "esbuild"}',
        )

    data = _build_tar_gz(build)
    resolved = _github_resolved(name="esbuild")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert result.discovered_directory == "npm/esbuild"
    assert (result.path / "package.json").is_file()
    assert (result.path / "lib" / "main.js").is_file()
    assert not (result.path / "main.go").exists()


@pytest.mark.asyncio
async def test_github_package_discovery_not_found():
    def build(tar):
        _add_file(tar, "repo-v1.0.0/main.go", b"package main")
        _add_file(tar, "repo-v1.0.0/other/package.json", b'{"name": "not-the-right-package"}')

    data = _build_tar_gz(build)
    resolved = _github_resolved(name="pkg")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is None
    assert result.reason == "package_not_found_in_repo"


@pytest.mark.asyncio
async def test_github_package_discovery_ambiguous():
    def build(tar):
        _add_file(tar, "repo-v1.0.0/a/package.json", b'{"name": "pkg"}')
        _add_file(tar, "repo-v1.0.0/b/package.json", b'{"name": "pkg"}')

    data = _build_tar_gz(build)
    resolved = _github_resolved(name="pkg")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is None
    assert result.reason == "package_ambiguous_in_repo"


@pytest.mark.asyncio
async def test_github_declared_repo_directory_skips_discovery_even_if_root_matches():
    """A registry-declared `repository.directory` is trusted as-is — no
    discovery pass, even when the wrapper root also happens to have a
    (differently-named) package.json."""

    def build(tar):
        _add_file(tar, "repo-v1.0.0/package.json", b'{"name": "monorepo-root"}')
        _add_file(tar, "repo-v1.0.0/packages/core/package.json", b'{"name": "pkg"}')
        _add_file(tar, "repo-v1.0.0/packages/core/index.js", b"x")

    data = _build_tar_gz(build)
    resolved = _github_resolved(name="pkg", repo_directory="packages/core")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert result.discovered_directory is None
    assert (result.path / "index.js").is_file()


@pytest.mark.asyncio
async def test_github_root_package_json_match_skips_full_discovery_scan():
    """The common case: the wrapper-root package.json already declares the
    right name, so no discovery is needed and `discovered_directory` stays
    unset — even though a same-named decoy exists elsewhere (proving the
    root-first check actually short-circuits rather than always scanning)."""

    def build(tar):
        _add_file(tar, "repo-v1.0.0/package.json", b'{"name": "pkg"}')
        _add_file(tar, "repo-v1.0.0/index.js", b"x")
        _add_file(tar, "repo-v1.0.0/examples/demo/package.json", b'{"name": "pkg"}')

    data = _build_tar_gz(build)
    resolved = _github_resolved(name="pkg")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert result.discovered_directory is None
    assert (result.path / "index.js").is_file()


@pytest.mark.asyncio
async def test_github_discovered_directory_persists_across_cache_hit():
    def build(tar):
        _add_file(tar, "esbuild-v0.28.2/main.go", b"package main")
        _add_file(tar, "esbuild-v0.28.2/npm/esbuild/package.json", b'{"name": "esbuild"}')

    data = _build_tar_gz(build)
    resolved = _github_resolved(name="esbuild")

    async with _client(data) as client:
        first = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)
    assert first.discovered_directory == "npm/esbuild"

    async with _client(data) as client:
        second = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert second.path == first.path
    assert second.discovered_directory == "npm/esbuild"


@pytest.mark.asyncio
async def test_github_monorepo_directory_missing_returns_none_not_whole_repo():
    """A renamed/moved repo_directory must never fall back to the whole monorepo.

    Regression: silently returning the unscoped extraction root would credit
    every package in the monorepo to this one package's capability profile.
    """
    data = _build_tar_gz(lambda tar: _add_file(tar, "r-v1.0.0/packages/other/index.js", b"x"))
    resolved = _github_resolved(repo_directory="packages/core")  # doesn't exist in this tarball

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is None


@pytest.mark.asyncio
async def test_github_source_unresolved_returns_none_without_network_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    resolved = _resolved()  # github_status defaults to "not_attempted"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is None
    assert calls == []


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_network():
    resolved = _resolved()
    cache_dir = fetcher.cache_dir_for(SourceKind.NPM_TARBALL, resolved.name, resolved.version)
    cache_dir.mkdir(parents=True)
    (cache_dir / ".complete").write_text(
        json.dumps({"schema_version": fetcher._MARKER_SCHEMA_VERSION})
    )

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path == cache_dir
    assert calls == []


@pytest.mark.asyncio
async def test_directory_without_marker_is_refetched():
    data = _normal_tarball_bytes()
    resolved = _resolved(integrity=_integrity_for(data))
    cache_dir = fetcher.cache_dir_for(SourceKind.NPM_TARBALL, resolved.name, resolved.version)
    cache_dir.mkdir(parents=True)
    (cache_dir / "stale.txt").write_text("leftover from a crashed fetch")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path is not None
    assert (result.path / ".complete").is_file()
    assert (result.path / "index.js").is_file()  # wrapper "package/" stripped during extraction
    assert not (result.path / "stale.txt").exists()


@pytest.mark.asyncio
async def test_stale_marker_without_skipped_long_path_names_is_refetched():
    """A `.complete` marker written before `skipped_long_path_names` existed
    (pre-PR-C) has no `schema_version` key at all, which reads back as 0 —
    below the current schema version — so it's treated as a cache miss and
    refetched. `backend.deps.drift` matches skipped paths by exact name, so
    trusting a stale, name-less count back would silently make every one of
    those files look like an ordinary unexplained file instead of
    `unverifiable`, and could raise a false drift signal."""
    data = _normal_tarball_bytes()
    resolved = _resolved(integrity=_integrity_for(data))
    cache_dir = fetcher.cache_dir_for(SourceKind.NPM_TARBALL, resolved.name, resolved.version)
    cache_dir.mkdir(parents=True)
    (cache_dir / "index.js").write_text("stale cached content, predates this fetch")
    (cache_dir / ".complete").write_text(json.dumps({"skipped_long_paths": 1}))

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path == cache_dir
    assert result.skipped_long_paths == 0
    assert result.skipped_long_path_names == ()
    assert (cache_dir / "index.js").read_text() != "stale cached content, predates this fetch"


@pytest.mark.asyncio
async def test_marker_with_current_schema_version_is_a_normal_cache_hit():
    """The counterpart to the staleness check: a marker already written at
    the current schema version is a normal cache hit, even with
    `skipped_long_paths > 0` — no unnecessary refetch."""
    resolved = _resolved()
    cache_dir = fetcher.cache_dir_for(SourceKind.NPM_TARBALL, resolved.name, resolved.version)
    cache_dir.mkdir(parents=True)
    (cache_dir / ".complete").write_text(
        json.dumps(
            {
                "schema_version": fetcher._MARKER_SCHEMA_VERSION,
                "skipped_long_paths": 1,
                "skipped_long_path_names": ["deep/file.js"],
            }
        )
    )

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert calls == []
    assert result.path == cache_dir
    assert result.skipped_long_path_names == ("deep/file.js",)


@pytest.mark.asyncio
async def test_pre_c2_github_marker_without_discovered_directory_is_stale():
    """The exact bug a live review found: a GitHub `.complete` marker written
    before package discovery existed (PR C2) has no `schema_version` and no
    `discovered_directory` key, but otherwise "looks complete" under the old
    per-field staleness check (it already has `skipped_long_path_names`).
    Trusting it back would keep comparing against whatever directory the
    pre-discovery fetch happened to land on (e.g. a monorepo's repo root)
    forever, even after upgrading to a version that fixes this. The
    schema-version check catches it generically instead of needing a new
    bespoke staleness rule for every field this marker gains."""

    def build(tar):
        _add_file(tar, "esbuild-v0.28.2/main.go", b"package main")
        _add_file(tar, "esbuild-v0.28.2/npm/esbuild/package.json", b'{"name": "esbuild"}')

    data = _build_tar_gz(build)
    resolved = _github_resolved(name="esbuild")
    cache_dir = fetcher.cache_dir_for(SourceKind.GITHUB, resolved.name, resolved.version)
    cache_dir.mkdir(parents=True)
    (cache_dir / "main.go").write_text("stale pre-discovery repo-root tree")
    (cache_dir / ".complete").write_text(
        json.dumps({"skipped_long_paths": 0, "skipped_long_path_names": []})
    )

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert result.discovered_directory == "npm/esbuild"
    assert (result.path / "package.json").is_file()
    assert not (result.path / "main.go").exists()


@pytest.mark.asyncio
async def test_concurrent_fetches_of_same_key_download_once():
    data = _normal_tarball_bytes()
    resolved = _resolved(integrity=_integrity_for(data))
    download_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal download_count
        download_count += 1
        return httpx.Response(200, content=data)

    async def one_fetch():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    results = await asyncio.gather(*[one_fetch() for _ in range(5)])

    assert download_count == 1
    assert all(r == results[0] for r in results)


@pytest.mark.asyncio
async def test_lock_table_does_not_grow_after_fetch_completes():
    """The per-key lock and its refcount must be dropped once the last holder
    releases it — the tables must not grow unbounded across many packages."""
    data = _normal_tarball_bytes()
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path is not None
    assert fetcher._locks == {}
    assert fetcher._lock_refcounts == {}


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integrity_mismatch_rejected_and_no_partial_cache():
    data = _normal_tarball_bytes()
    resolved = _resolved(integrity=_integrity_for(b"not the actual bytes"))

    async with _client(data) as client:
        with pytest.raises(fetcher.IntegrityError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    cache_dir = fetcher.cache_dir_for(SourceKind.NPM_TARBALL, resolved.name, resolved.version)
    assert not cache_dir.exists()
    assert not cache_dir.with_name(f".{cache_dir.name}.tmp").exists()


@pytest.mark.asyncio
async def test_integrity_hash_runs_over_compressed_bytes():
    """The digest must match the compressed tarball bytes, not the extracted content."""
    data = _normal_tarball_bytes()
    resolved = _resolved(integrity=_integrity_for(data))  # correct: hash of compressed bytes

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path is not None


@pytest.mark.asyncio
async def test_legacy_shasum_integrity_is_verified():
    """dist.shasum (bare hex SHA-1, no algo prefix) must still be checked, not skipped."""
    data = _normal_tarball_bytes()
    shasum = hashlib.sha1(data).hexdigest()
    resolved = _resolved(integrity=shasum)

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path is not None


@pytest.mark.asyncio
async def test_legacy_shasum_mismatch_rejected():
    data = _normal_tarball_bytes()
    resolved = _resolved(integrity=hashlib.sha1(b"wrong bytes").hexdigest())

    async with _client(data) as client:
        with pytest.raises(fetcher.IntegrityError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_multi_hash_ssri_picks_strongest():
    """A space-separated multi-hash SSRI string must be verified using the strongest hash.

    A deliberately wrong sha1 entry is included; only the sha512 entry is correct.
    If the parser picked the (weaker) sha1 entry, this would fail closed instead.
    """
    data = _normal_tarball_bytes()
    wrong_sha1 = base64.b64encode(hashlib.sha1(b"not the actual bytes").digest()).decode()
    correct_sha512 = base64.b64encode(hashlib.sha512(data).digest()).decode()
    resolved = _resolved(integrity=f"sha1-{wrong_sha1} sha512-{correct_sha512}")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path is not None


@pytest.mark.asyncio
async def test_unparseable_integrity_fails_closed():
    """An integrity value that's present but unrecognized must reject, not silently pass."""
    data = _normal_tarball_bytes()
    resolved = _resolved(integrity="md5-notarealalgorithm==")

    async with _client(data) as client:
        with pytest.raises(fetcher.IntegrityError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


# ---------------------------------------------------------------------------
# Size caps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_compressed_tarball_rejected(monkeypatch):
    monkeypatch.setattr(fetcher.settings, "deps_max_tarball_mb", 1)
    data = b"x" * (2 * 1024 * 1024)
    # The size cap aborts the download mid-stream, before the integrity check
    # ever runs — this just needs to parse, not match.
    resolved = _resolved(integrity=_integrity_for(b"placeholder"))

    async with _client(data) as client:
        with pytest.raises(fetcher.TarballTooLargeError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    cache_dir = fetcher.cache_dir_for(SourceKind.NPM_TARBALL, resolved.name, resolved.version)
    assert not cache_dir.exists()


@pytest.mark.asyncio
async def test_oversized_extracted_content_rejected(monkeypatch):
    monkeypatch.setattr(fetcher, "_MAX_EXTRACTED_BYTES", 10)
    data = _normal_tarball_bytes()  # well over 10 bytes once extracted
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.TarballTooLargeError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    cache_dir = fetcher.cache_dir_for(SourceKind.NPM_TARBALL, resolved.name, resolved.version)
    assert not cache_dir.exists()


@pytest.mark.asyncio
async def test_too_many_files_rejected(monkeypatch):
    monkeypatch.setattr(fetcher, "_MAX_EXTRACTED_FILES", 2)

    def build(tar):
        for i in range(5):
            _add_file(tar, f"package/file{i}.js", b"x")

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.TarballTooLargeError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


# ---------------------------------------------------------------------------
# Hostile tar members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_traversal_member_rejected():
    def build(tar):
        _add_file(tar, "../../etc/passwd", b"pwned")

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_absolute_path_member_rejected():
    def build(tar):
        _add_file(tar, "/etc/passwd", b"pwned")

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_symlink_member_rejected():
    def build(tar):
        info = tarfile.TarInfo(name="package/evil-link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_hardlink_member_rejected():
    def build(tar):
        _add_file(tar, "package/real.js", b"x")
        info = tarfile.TarInfo(name="package/hard-link")
        info.type = tarfile.LNKTYPE
        info.linkname = "package/real.js"
        tar.addfile(info)

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_fifo_member_rejected():
    def build(tar):
        info = tarfile.TarInfo(name="package/pipe")
        info.type = tarfile.FIFOTYPE
        tar.addfile(info)

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_device_member_rejected():
    def build(tar):
        info = tarfile.TarInfo(name="package/dev")
        info.type = tarfile.CHRTYPE
        info.devmajor = 1
        info.devminor = 1
        tar.addfile(info)

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_filter_error_mapped_to_unsafe_member_error(monkeypatch):
    """tarfile's own "data" filter rejecting a member is an unsafe-member finding,
    not a parse failure — it must not surface as CorruptTarballError."""

    def _raise_filter_error(self, member, path, **kwargs):
        raise tarfile.FilterError("blocked by data filter")

    monkeypatch.setattr(tarfile.TarFile, "extract", _raise_filter_error)

    data = _normal_tarball_bytes()
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_truncated_gzip_rejected():
    # A trailing-bytes truncation can land in the tar's zero-block padding and
    # decode cleanly, so truncate to roughly half the stream — deep enough to
    # land inside the deflate body and guarantee a decompression error.
    data = _normal_tarball_bytes()
    truncated = data[: len(data) // 2]
    # Integrity must match what's actually served (the truncated bytes) so the
    # download succeeds and the failure comes from extraction, as intended.
    resolved = _resolved(integrity=_integrity_for(truncated))

    async with _client(truncated) as client:
        with pytest.raises(fetcher.CorruptTarballError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_corrupt_header_rejected():
    garbage = b"\x1f\x8b" + b"not a real gzip stream" * 20
    resolved = _resolved(integrity=_integrity_for(garbage))

    async with _client(garbage) as client:
        with pytest.raises(fetcher.CorruptTarballError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_hostile_tarball_leaves_no_files_outside_cache(tmp_path):
    """A rejected tarball must not leave anything written outside the isolated cache dir."""
    before = set(tmp_path.rglob("*"))

    def build(tar):
        _add_file(tar, "../../../escaped.txt", b"pwned")

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    after = set(tmp_path.rglob("*"))
    # Only empty scaffold dirs (kind/name@version parents) may remain; no file leaked.
    leaked_files = {p for p in (after - before) if p.is_file()}
    assert leaked_files == set()


# ---------------------------------------------------------------------------
# Scoped package cache path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scoped_package_name_sanitized_for_cache_dir():
    data = _normal_tarball_bytes()
    resolved = _resolved(name="@babel/core", integrity=_integrity_for(data))

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path is not None
    assert "/" not in result.path.name  # a single path segment, not "@babel" then "core"
    assert result.path.name == "@babel__core@1.0.0"


# ---------------------------------------------------------------------------
# Per-entry wrapper stripping (PR A: fix/deps-fetch-coverage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_npm_strips_each_entrys_own_leading_segment_independently():
    """`npm install <tarball>` strips one leading path component from each
    entry *independently* — it never assumes a single wrapper name taken
    from whichever entry happened to come first. A tarball whose entries
    disagree on their top-level folder must still install every one of
    them, matching what a real `npm install` would actually put on disk;
    assuming one global wrapper would silently drop the divergent entries
    from the scan instead."""

    def build(tar):
        _add_file(tar, "package/package.json", b"{}")
        _add_file(tar, "evil/backdoor.js", b"require('child_process').exec('pwned')")

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path is not None
    assert (result.path / "package.json").is_file()
    assert (result.path / "backdoor.js").is_file()


@pytest.mark.asyncio
async def test_npm_colliding_stripped_paths_rejected():
    """Two entries under different top-level folders that strip to the same
    install path is not something a real `npm pack` ever produces — treated
    as tampering rather than silently letting one overwrite the other."""

    def build(tar):
        _add_file(tar, "package/index.js", b"real")
        _add_file(tar, "evil/index.js", b"shadow")

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)


@pytest.mark.asyncio
async def test_github_inconsistent_wrapper_rejected():
    """Unlike an npm tarball, a GitHub codeload archive always uses one
    consistent `{repo}-{ref}/` prefix for every entry. A member that departs
    from the wrapper established by the first entry is a hostile/corrupt
    shape and must reject the whole tarball, not be silently skipped as if
    it were an ordinary out-of-scope sibling."""

    def build(tar):
        _add_file(tar, "r-v1.0.0/index.js", b"x")
        _add_file(tar, "r-v1.0.0/package.json", b'{"name": "pkg"}')
        _add_file(tar, "other-repo-abc/sneaky.js", b"x")

    data = _build_tar_gz(build)
    resolved = _github_resolved()

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)


@pytest.mark.asyncio
async def test_repo_directory_leading_dot_slash_normalized():
    """A `repository.directory` value like "./packages/core" (a leading
    "./", as some package.json authors write it) must still match the
    tarball's real member paths instead of silently missing and being
    reported as `repo_directory_missing`."""
    data = _build_tar_gz(lambda tar: _add_file(tar, "r-v1.0.0/packages/core/index.js", b"x"))
    resolved = _github_resolved(repo_directory="./packages/core/")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert (result.path / "index.js").is_file()


# ---------------------------------------------------------------------------
# Windows path-length limit (PR A: fix/deps-fetch-coverage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows-specific path-length behavior")
async def test_windows_long_path_skipped_and_counted_not_silently_invisible():
    """A file whose extraction target would exceed Windows' MAX_PATH must be
    skipped and counted rather than written via a `\\\\?\\`-escaped path —
    on a machine without LongPathsEnabled, a `\\\\?\\`-written file becomes
    invisible to ordinary directory walks (drift, Semgrep), producing a
    silent partial scan instead of a loud, counted one."""

    def build(tar):
        _add_file(tar, "package/short.js", b"x")
        _add_file(tar, "package/" + ("a" * 300) + "/deep.js", b"x")

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result.path is not None
    assert (result.path / "short.js").is_file()
    assert result.skipped_long_paths == 1
    assert not any(p.name == "deep.js" for p in result.path.rglob("*"))
    assert result.skipped_long_path_names == (("a" * 300) + "/deep.js",)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific path-length behavior")
def test_windows_directory_limit_checked_separately_from_file_limit():
    """Windows caps *directory* creation at 248 chars, shorter than the
    260-char full-path limit — a short filename inside a long-enough
    directory chain must still be flagged even though the full path stays
    under 260. Uses a short synthetic base path (rather than going through
    a real fetch, whose temp-directory prefix length is unpredictable) so
    the 248-vs-260 boundary is exact and deterministic."""
    from pathlib import Path as _Path

    base = _Path("C:/x")
    deep_dir = base / ("d" * 245) / "f.js"  # dir portion: 250 chars (>=248); full: 255 (<260)

    assert len(str(deep_dir.parent)) >= fetcher._WINDOWS_MAX_DIR_PATH
    assert len(str(deep_dir)) < fetcher._WINDOWS_MAX_PATH
    assert fetcher._exceeds_windows_path_limits(deep_dir)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows-specific path-length behavior")
async def test_skipped_long_paths_persists_across_cache_hit():
    """A cache hit never re-runs `_safe_extract`, so the skip count must be
    recorded in the `.complete` marker itself — otherwise a second call for
    the same version silently reports the extraction as clean."""

    def build(tar):
        _add_file(tar, "package/short.js", b"x")
        _add_file(tar, "package/" + ("a" * 300) + "/deep.js", b"x")

    data = _build_tar_gz(build)
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        first = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)
    assert first.skipped_long_paths == 1
    assert first.skipped_long_path_names == (("a" * 300) + "/deep.js",)

    async with _client(data) as client:
        second = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert second.path == first.path
    assert second.skipped_long_paths == 1
    assert second.skipped_long_path_names == first.skipped_long_path_names


# ---------------------------------------------------------------------------
# Scoped extraction (PR A: fix/deps-fetch-coverage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scoped_extraction_writes_only_package_subtree_with_prefix_stripped():
    """A monorepo tarball's sibling package must never be written to disk, and
    the returned directory must hold the scoped package's files directly —
    not nested under `{wrapper}/{repo_directory}/`."""

    def build(tar):
        _add_file(tar, "r-v1.0.0/packages/core/index.js", b"x")
        _add_file(tar, "r-v1.0.0/packages/core/package.json", b"{}")
        _add_file(tar, "r-v1.0.0/packages/other/index.js", b"unrelated sibling package")

    data = _build_tar_gz(build)
    resolved = _github_resolved(repo_directory="packages/core")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert (result.path / "index.js").is_file()
    assert (result.path / "package.json").is_file()
    assert not (result.path / "packages").exists()  # not nested under the stripped prefix
    assert not (result.path.parent / "other").exists()  # sibling package never written


@pytest.mark.asyncio
async def test_scoped_extraction_caps_count_only_in_scope_members(monkeypatch):
    """An oversized member in a sibling package (outside `repo_directory`) must
    never trip this package's extraction caps — only members actually written
    for this package count."""
    monkeypatch.setattr(fetcher, "_MAX_EXTRACTED_BYTES", 10)

    def build(tar):
        _add_file(tar, "r-v1.0.0/packages/core/index.js", b"x")
        _add_file(tar, "r-v1.0.0/packages/other/big.bin", b"x" * 1000)  # out of scope

    data = _build_tar_gz(build)
    resolved = _github_resolved(repo_directory="packages/core")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert (result.path / "index.js").is_file()


@pytest.mark.asyncio
async def test_traversal_disguised_by_scoped_prefix_rejected():
    """A member name that only escapes `extract_root` *after* the
    `{wrapper}/{repo_directory}/` prefix is stripped must still be rejected.

    Regression: the containment check ran on the raw, prefix-included member
    name (`extract_root / "r-v1.0.0/packages/core/../../../secrets_leak"`),
    which resolves right back inside `extract_root` (the three ".." segments
    exactly cancel the three prefix segments) — but the member is actually
    extracted as `extract_root / rel_name` after the prefix is stripped,
    i.e. `extract_root / "../../../secrets_leak"`, which is three levels
    *outside* extract_root. The manual check must validate that real target,
    not the pre-strip one.
    """

    def build(tar):
        _add_file(tar, "r-v1.0.0/packages/core/index.js", b"x")
        _add_file(tar, "r-v1.0.0/packages/core/../../../secrets_leak", b"pwned")

    data = _build_tar_gz(build)
    resolved = _github_resolved(repo_directory="packages/core")

    async with _client(data) as client:
        with pytest.raises(fetcher.UnsafeTarMemberError):
            await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)


@pytest.mark.asyncio
async def test_scoped_extraction_ignores_out_of_scope_symlink():
    """A symlink living in a sibling package (outside `repo_directory`) must be
    silently ignored, not counted against this package's `skipped_links`."""

    def build(tar):
        _add_file(tar, "r-v1.0.0/packages/core/index.js", b"x")
        info = tarfile.TarInfo(name="r-v1.0.0/packages/other/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "index.js"
        tar.addfile(info)

    data = _build_tar_gz(build)
    resolved = _github_resolved(repo_directory="packages/core")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert result.skipped_links == 0  # out of repo_directory scope, never even inspected


@pytest.mark.asyncio
async def test_github_monorepo_directory_missing_reports_skip_reason():
    data = _build_tar_gz(lambda tar: _add_file(tar, "r-v1.0.0/packages/other/index.js", b"x"))
    resolved = _github_resolved(repo_directory="packages/core")  # doesn't exist in this tarball

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is None
    assert result.reason == "repo_directory_missing"


# ---------------------------------------------------------------------------
# GitHub symlink policy (PR A: fix/deps-fetch-coverage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_symlink_skipped_and_counted_not_rejected():
    """A real repo carrying a legitimate symlink (zod's `.codex/skills`,
    esbuild) must not reject the whole GitHub tarball — only an NPM_TARBALL
    symlink means tampering (`npm pack` never emits one)."""

    def build(tar):
        _add_file(tar, "r-v1.0.0/index.js", b"x")
        _add_file(tar, "r-v1.0.0/package.json", b'{"name": "pkg"}')
        info = tarfile.TarInfo(name="r-v1.0.0/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "index.js"
        tar.addfile(info)

    data = _build_tar_gz(build)
    resolved = _github_resolved()

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert result.skipped_links == 1
    assert result.skipped_link_names == ("link",)
    assert (result.path / "index.js").is_file()
    assert not (result.path / "link").exists()


@pytest.mark.asyncio
async def test_github_hardlink_skipped_and_counted_not_rejected():
    def build(tar):
        _add_file(tar, "r-v1.0.0/real.js", b"x")
        _add_file(tar, "r-v1.0.0/package.json", b'{"name": "pkg"}')
        info = tarfile.TarInfo(name="r-v1.0.0/hard-link")
        info.type = tarfile.LNKTYPE
        info.linkname = "r-v1.0.0/real.js"
        tar.addfile(info)

    data = _build_tar_gz(build)
    resolved = _github_resolved()

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result.path is not None
    assert result.skipped_links == 1


# ---------------------------------------------------------------------------
# Path-too-long (PR A: fix/deps-fetch-coverage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_too_long_mapped_to_path_too_long_error(monkeypatch):
    """A filename-too-long OSError during extraction (Windows MAX_PATH, POSIX
    ENAMETOOLONG) must surface as `PathTooLongError`, not be misreported as a
    corrupt tarball — the CI-observed Babel/Jest monorepo failure shape."""

    def _raise_name_too_long(self, member, path, **kwargs):
        raise OSError(errno.ENAMETOOLONG, "File name too long")

    monkeypatch.setattr(tarfile.TarFile, "extract", _raise_name_too_long)

    data = _normal_tarball_bytes()
    resolved = _resolved(integrity=_integrity_for(data))

    async with _client(data) as client:
        with pytest.raises(fetcher.PathTooLongError):
            await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)
