"""Fuzz tests for backend.deps.fetcher's tar extraction safety net.

500 seeded-random malformed tarballs run through fetch_source(). Each one
must either be rejected with a typed FetchError (never a bare/generic
exception) or — for the rare mutation that still parses into something
harmless — succeed cleanly. A subset of iterations builds tarballs carrying
an actual hostile member (path traversal, absolute path, symlink escape):
those three strategies are required to be rejected (a "success" for one of
them is itself the finding, not a pass), and the escape canary is checked
both outside the sandbox and at its exact in-cache target path — a symlink
member that slipped through wouldn't write canary *content* anywhere; it
would leave a dangling symlink at that path instead. No partial cache
directory may be left behind either way.

Offline: everything is served via httpx.MockTransport. Seeded RNG makes a
failing run reproducible (the seed is printed in the assertion message).
"""

import base64
import hashlib
import io
import random
import tarfile

import httpx
import pytest

from backend.deps import fetcher
from backend.models.dependencies import ResolvedPackage
from backend.models.enums import SourceKind


_SEED = 20260924
_ITERATIONS = 500
_CANARY_NAME = "fuzz_escape_canary.txt"


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher.settings, "deps_cache_dir", str(tmp_path))
    fetcher._locks.clear()
    fetcher._lock_refcounts.clear()
    return tmp_path


def _resolved(version: str, integrity: str) -> ResolvedPackage:
    return ResolvedPackage(
        name="fuzzpkg",
        version=version,
        tarball_url="https://registry.npmjs.org/fuzzpkg.tgz",
        integrity=integrity,
    )


def _client(content: bytes) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _integrity_for(data: bytes) -> str:
    digest = hashlib.sha512(data).digest()
    return "sha512-" + base64.b64encode(digest).decode()


def _valid_tar_gz(rng: random.Random) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for i in range(rng.randint(1, 5)):
            content = bytes(rng.randrange(256) for _ in range(rng.randint(0, 64)))
            info = tarfile.TarInfo(name=f"package/file{i}.js")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Byte-level corruption strategies (operate on already-valid tar.gz bytes).
# A "success" is an acceptable outcome for all of these — the mutation may
# have produced something structurally harmless.
# ---------------------------------------------------------------------------


def _truncate(data: bytes, rng: random.Random) -> bytes:
    return data[: rng.randint(0, max(0, len(data) - 1))]


def _flip_bytes(data: bytes, rng: random.Random) -> bytes:
    mutable = bytearray(data)
    for _ in range(rng.randint(1, 20)):
        if not mutable:
            break
        mutable[rng.randrange(len(mutable))] = rng.randrange(256)
    return bytes(mutable)


def _truncate_gzip_header(data: bytes, rng: random.Random) -> bytes:
    return data[: rng.randint(0, 10)]


def _garbage(data: bytes, rng: random.Random) -> bytes:
    return bytes(rng.randrange(256) for _ in range(rng.randint(0, 500)))


def _empty(data: bytes, rng: random.Random) -> bytes:
    return b""


def _double_gzip(data: bytes, rng: random.Random) -> bytes:
    return data + data


_SOFT_STRATEGIES = (
    _truncate,
    _flip_bytes,
    _truncate_gzip_header,
    _garbage,
    _empty,
    _double_gzip,
)

# ---------------------------------------------------------------------------
# Hostile-member strategies (build a fresh, structurally-valid tar.gz whose
# only payload is an escape attempt). Unlike the corruption strategies above,
# these MUST be rejected — a "success" here means the containment check
# regressed, and is the fuzz finding itself, not an acceptable outcome.
# ---------------------------------------------------------------------------


def _traversal_member(data: bytes, rng: random.Random) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        content = b"evil"
        depth = rng.randint(2, 8)
        name = "/".join([".."] * depth) + f"/{_CANARY_NAME}"
        info = tarfile.TarInfo(name=name)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _absolute_path_member(data: bytes, rng: random.Random) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        content = b"evil"
        info = tarfile.TarInfo(name=f"/{_CANARY_NAME}")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _symlink_escape_member(data: bytes, rng: random.Random) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=f"package/{_CANARY_NAME}")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    return buf.getvalue()


_HOSTILE_STRATEGIES = (_traversal_member, _absolute_path_member, _symlink_escape_member)
_MUTATION_STRATEGIES = _SOFT_STRATEGIES + _HOSTILE_STRATEGIES


def _mutate(data: bytes, rng: random.Random):
    """Apply one random corruption/escape strategy. Returns (mutated_bytes, strategy)."""
    strategy = rng.choice(_MUTATION_STRATEGIES)
    return strategy(data, rng), strategy


def _assert_canary_absent(tmp_path, cache_dir) -> None:
    """The escape-attempt strategies target `_CANARY_NAME` either above the
    sandbox (traversal/absolute-path) or at a fixed in-cache path (symlink) —
    checking only ancestors of `tmp_path` would miss a symlink member that
    slipped through: it creates a dangling link *inside* the cache rather
    than writing canary content outside it, so that exact path is checked too.
    """
    for ancestor in (tmp_path, *list(tmp_path.parents)[:8]):
        candidate = ancestor / _CANARY_NAME
        assert not candidate.exists(), f"seed={_SEED}: escape canary found at {candidate}"
    in_cache_symlink = cache_dir / "package" / _CANARY_NAME
    assert not in_cache_symlink.is_symlink(), (
        f"seed={_SEED}: symlink member was extracted at {in_cache_symlink}"
    )


def _cleanup_stray_canaries(tmp_path) -> None:
    """A canary from an interrupted/sabotaged prior run (e.g. manually disabling
    a containment check to verify this test catches it) must not cause a false
    positive on the next run — this is a real system path (tmp_path's ancestors
    reach outside pytest's own tmp tree), not something pytest resets for us."""
    for ancestor in (tmp_path, *list(tmp_path.parents)[:8]):
        (ancestor / _CANARY_NAME).unlink(missing_ok=True)


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_fuzzed_malformed_tarballs_never_escape_safety_net(tmp_path):
    _cleanup_stray_canaries(tmp_path)
    rng = random.Random(_SEED)  # noqa: S311 - reproducible fuzz seed, not cryptographic use
    failures_by_type: dict[str, int] = {}
    successes = 0

    for i in range(_ITERATIONS):
        version = f"0.0.{i}"
        mutated, strategy = _mutate(_valid_tar_gz(rng), rng)
        # Integrity is checked against the bytes actually served, so a
        # mismatch never masks a real extraction-time bug as "integrity
        # failed" instead.
        resolved = _resolved(version, _integrity_for(mutated))
        cache_dir = fetcher.cache_dir_for(SourceKind.NPM_TARBALL, "fuzzpkg", version)

        result = None
        raised: fetcher.FetchError | None = None
        try:
            async with _client(mutated) as client:
                result = await fetcher.fetch_source(resolved, SourceKind.NPM_TARBALL, client=client)
        except fetcher.FetchError as exc:
            raised = exc
            failures_by_type[type(exc).__name__] = failures_by_type.get(type(exc).__name__, 0) + 1
        except Exception as exc:  # pragma: no cover - a fuzz failure IS the finding
            pytest.fail(
                f"seed={_SEED} iteration={i} (version={version}) raised an untyped "
                f"exception instead of a FetchError: {type(exc).__name__}: {exc}"
            )

        # Marker/escape checks run unconditionally and outside the try above,
        # so a real assertion failure here is reported as itself — not
        # mislabeled as "raised an untyped exception instead of a FetchError".
        if strategy in _HOSTILE_STRATEGIES:
            assert raised is not None, (
                f"seed={_SEED} iteration={i}: hostile strategy {strategy.__name__} "
                f"was NOT rejected (fetch_source returned {result!r} instead of raising)"
            )
        if result is not None:
            successes += 1
            assert (result / ".complete").is_file(), f"seed={_SEED} iteration={i}"
        _assert_canary_absent(tmp_path, cache_dir)

        # No partial cache directory left behind, whichever way this went.
        if cache_dir.exists():
            assert (cache_dir / ".complete").is_file(), f"seed={_SEED} iteration={i}"

    assert successes + sum(failures_by_type.values()) == _ITERATIONS

    # fetcher.fetch_source stages every fetch in a tempfile.mkdtemp() directory
    # named ".{cache_dir.name}.<random>" under cache_dir.parent, cleaned up in
    # a `finally`. None of those dot-prefixed directories may survive a run —
    # a completed cache_dir itself is never dot-prefixed, so this can't
    # false-positive on real output.
    leftover_temp_dirs = [p for p in tmp_path.rglob(".*") if p.is_dir()]
    assert not leftover_temp_dirs, f"leftover temp directories: {leftover_temp_dirs}"
