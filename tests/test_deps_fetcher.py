"""Offline tests for backend.deps.fetcher — safe tarball fetch, integrity, extraction.

All network access is mocked via httpx.MockTransport. Hostile tarballs are built
in-memory; none of them are ever executed, only fed through the safe extractor.
"""

import asyncio
import base64
import hashlib
import io
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

    assert result is not None
    assert (result / ".complete").is_file()
    assert (result / "package" / "index.js").is_file()


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
    data = _build_tar_gz(lambda tar: _add_file(tar, "r-abc123/index.js", b"x"))
    resolved = _github_resolved()
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, content=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result is not None
    assert requested == [fetcher.github_tarball_url("o", "r", "v1.0.0")]


@pytest.mark.asyncio
async def test_github_monorepo_directory_found():
    data = _build_tar_gz(lambda tar: _add_file(tar, "r-v1.0.0/packages/core/index.js", b"x"))
    resolved = _github_resolved(repo_directory="packages/core")

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result is not None
    assert (result / "index.js").is_file()


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

    assert result is None


@pytest.mark.asyncio
async def test_github_source_unresolved_returns_none_without_network_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    resolved = _resolved()  # github_status defaults to "not_attempted"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.GITHUB, client=client)

    assert result is None
    assert calls == []


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_network():
    resolved = _resolved()
    cache_dir = fetcher.cache_dir_for(SourceKind.NPM_TARBALL, resolved.name, resolved.version)
    cache_dir.mkdir(parents=True)
    (cache_dir / ".complete").touch()

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result == cache_dir
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

    assert result is not None
    assert (result / ".complete").is_file()
    assert (result / "package" / "index.js").is_file()
    assert not (result / "stale.txt").exists()


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

    assert result is not None
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

    assert result is not None


@pytest.mark.asyncio
async def test_legacy_shasum_integrity_is_verified():
    """dist.shasum (bare hex SHA-1, no algo prefix) must still be checked, not skipped."""
    data = _normal_tarball_bytes()
    shasum = hashlib.sha1(data).hexdigest()
    resolved = _resolved(integrity=shasum)

    async with _client(data) as client:
        result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)

    assert result is not None


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

    assert result is not None


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

    assert result is not None
    assert "/" not in result.name  # a single path segment, not "@babel" then "core"
    assert result.name == "@babel__core@1.0.0"
