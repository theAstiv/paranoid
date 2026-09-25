"""Offline tests for backend.deps.resolver — npm registry + GitHub ref resolution.

All network access is mocked via httpx.MockTransport; no real HTTP calls are made.
"""

import httpx
import pytest

from backend.deps.resolver import (
    fetch_registry_doc,
    github_tarball_url,
    previous_version,
    resolve_github_ref,
    resolve_npm,
    resolved_package_from_doc,
)
from backend.models.dependencies import ResolvedPackage


def _registry_doc(*, repository=None, git_head="abc123", npm_user="alice") -> dict:
    version_doc = {
        "dist": {
            "tarball": "https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz",
            "integrity": "sha512-AAAA",
        },
        "gitHead": git_head,
        "_npmUser": {"name": npm_user},
        "maintainers": [{"name": "alice"}, {"name": "bob"}],
    }
    if repository is not None:
        version_doc["repository"] = repository
    return {
        "name": "pkg",
        "versions": {"1.0.0": version_doc, "0.9.0": {**version_doc}},
        "time": {
            "created": "2020-01-01T00:00:00.000Z",
            "modified": "2020-06-01T00:00:00.000Z",
            "0.9.0": "2020-01-15T00:00:00.000Z",
            "1.0.0": "2020-06-01T00:00:00.000Z",
        },
    }


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# repository field shapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("repository", "expected_owner", "expected_repo", "expected_directory"),
    [
        ("https://github.com/facebook/react", "facebook", "react", None),
        ("git+https://github.com/facebook/react.git", "facebook", "react", None),
        ("git+https://github.com/facebook/react", "facebook", "react", None),
        ("git+ssh://git@github.com/facebook/react.git", "facebook", "react", None),
        ("git://github.com/facebook/react.git", "facebook", "react", None),
        ("http://github.com/facebook/react", "facebook", "react", None),
        ("www.github.com/facebook/react", "facebook", "react", None),
        ("github.com/facebook/react", "facebook", "react", None),
        ("git@github.com:facebook/react.git", "facebook", "react", None),
        ("github:facebook/react", "facebook", "react", None),
        ("facebook/react", "facebook", "react", None),
        (
            {
                "type": "git",
                "url": "https://github.com/babel/babel.git",
                "directory": "packages/core",
            },
            "babel",
            "babel",
            "packages/core",
        ),
        (None, None, None, None),
    ],
)
def test_repository_shapes_normalize(repository, expected_owner, expected_repo, expected_directory):
    doc = _registry_doc(repository=repository)
    resolved = resolved_package_from_doc("pkg", "1.0.0", doc)
    assert resolved.repo_owner == expected_owner
    assert resolved.repo_name == expected_repo
    assert resolved.repo_directory == expected_directory


@pytest.mark.parametrize(
    "repository",
    [
        "https://github.com/../react",  # owner "..", fails GitHub's own naming rule
        "https://github.com/facebook/..",  # repo "..", would escape as a path segment
        "a?x=1/react",  # owner carries characters GitHub never allows
        "https://github.com/" + "a" * 40 + "/react",  # owner over GitHub's 39-char cap
    ],
)
def test_invalid_owner_repo_resolves_to_none(repository):
    """An owner/repo shape that doesn't fit GitHub's own naming rules must never
    reach `github_tarball_url` — it's treated as GitHub-unavailable instead of
    being fed into a codeload URL unescaped."""
    doc = _registry_doc(repository=repository)
    resolved = resolved_package_from_doc("pkg", "1.0.0", doc)
    assert resolved.repo_owner is None
    assert resolved.repo_name is None


def test_non_github_repository_resolves_to_none():
    doc = _registry_doc(repository="https://gitlab.com/o/r.git")
    resolved = resolved_package_from_doc("pkg", "1.0.0", doc)
    assert resolved.repo_owner is None
    assert resolved.repo_name is None


def test_missing_git_head():
    doc = _registry_doc(repository="facebook/react", git_head=None)
    del doc["versions"]["1.0.0"]["gitHead"]
    resolved = resolved_package_from_doc("pkg", "1.0.0", doc)
    assert resolved.git_head is None


def test_publisher_and_maintainers_captured():
    doc = _registry_doc(repository="facebook/react", npm_user="carol")
    resolved = resolved_package_from_doc("pkg", "1.0.0", doc)
    assert resolved.publisher == "carol"
    assert resolved.maintainers == ["alice", "bob"]


def test_missing_version_raises():
    doc = _registry_doc()
    with pytest.raises(ValueError, match="not found"):
        resolved_package_from_doc("pkg", "9.9.9", doc)


# ---------------------------------------------------------------------------
# publish-time ordering (previous_version)
# ---------------------------------------------------------------------------


def test_previous_version_orders_by_publish_time_not_semver():
    doc = {
        "versions": {"2.0.0": {}, "1.0.0-beta.1": {}},
        "time": {
            "created": "x",
            "modified": "x",
            "2.0.0": "2020-01-01T00:00:00.000Z",
            "1.0.0-beta.1": "2020-02-01T00:00:00.000Z",  # published *after* 2.0.0
        },
    }
    # Publish order: 2.0.0, then 1.0.0-beta.1 — previous_version follows time, not semver.
    assert previous_version(doc, "1.0.0-beta.1") == "2.0.0"


def test_previous_version_first_release_has_no_predecessor():
    doc = _registry_doc()
    assert previous_version(doc, "0.9.0") is None


def test_previous_version_unknown_version_returns_none():
    doc = _registry_doc()
    assert previous_version(doc, "9.9.9") is None


def test_previous_version_ignores_unpublished_time_entries():
    """time entries not present in `versions` (deprecated/removed) must be skipped.

    Regression: the time map can retain a version's timestamp after it's been
    unpublished from `versions`, or (for a fully unpublished package) carry an
    "unpublished" object instead of a string — comparing that against a string
    timestamp during sort would raise TypeError.
    """
    doc = {
        "versions": {"1.0.0": {}, "2.0.0": {}},
        "time": {
            "created": "x",
            "modified": "x",
            "1.0.0": "2020-01-01T00:00:00.000Z",
            "1.5.0": "2020-01-15T00:00:00.000Z",  # removed from versions, still timestamped
            "2.0.0": "2020-02-01T00:00:00.000Z",
            "unpublished": {"time": "2020-01-20T00:00:00.000Z"},  # not a string timestamp
        },
    }
    assert previous_version(doc, "2.0.0") == "1.0.0"


# ---------------------------------------------------------------------------
# scoped package name encoding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scoped_package_name_url_encoded():
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, json=_registry_doc(repository="babel/babel"))

    async with _client(handler) as client:
        await resolve_npm("@babel/core", "1.0.0", client=client)

    assert seen_urls == ["https://registry.npmjs.org/%40babel%2Fcore"]


@pytest.mark.asyncio
async def test_fetch_registry_doc_unscoped_name():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://registry.npmjs.org/express"
        return httpx.Response(200, json=_registry_doc())

    async with _client(handler) as client:
        doc = await fetch_registry_doc("express", client)
    assert doc["name"] == "pkg"


# ---------------------------------------------------------------------------
# GitHub ref resolution order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_ref_resolves_via_git_head_first():
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200)

    resolved = ResolvedPackage(
        name="pkg",
        version="1.0.0",
        tarball_url="https://x/pkg.tgz",
        integrity="sha512-AAAA",
        git_head="deadbeef",
        repo_owner="o",
        repo_name="r",
    )
    async with _client(handler) as client:
        result = await resolve_github_ref(resolved, client=client)

    assert result.github_status == "resolved"
    assert result.github_ref == "deadbeef"
    assert requested == ["https://codeload.github.com/o/r/tar.gz/deadbeef"]


@pytest.mark.asyncio
async def test_github_ref_falls_back_through_tag_candidates():
    # gitHead 404s, "{name}@{version}" 404s, "v{version}" resolves.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1.0.0"):
            return httpx.Response(200)
        return httpx.Response(404)

    resolved = ResolvedPackage(
        name="pkg",
        version="1.0.0",
        tarball_url="https://x/pkg.tgz",
        integrity="sha512-AAAA",
        git_head="deadbeef",
        repo_owner="o",
        repo_name="r",
    )
    async with _client(handler) as client:
        result = await resolve_github_ref(resolved, client=client)

    assert result.github_status == "resolved"
    assert result.github_ref == "v1.0.0"


@pytest.mark.asyncio
async def test_github_ref_falls_back_to_bare_version():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/1.0.0"):
            return httpx.Response(200)
        return httpx.Response(404)

    resolved = ResolvedPackage(
        name="pkg",
        version="1.0.0",
        tarball_url="https://x/pkg.tgz",
        integrity="sha512-AAAA",
        repo_owner="o",
        repo_name="r",
    )
    async with _client(handler) as client:
        result = await resolve_github_ref(resolved, client=client)

    assert result.github_status == "resolved"
    assert result.github_ref == "1.0.0"


@pytest.mark.asyncio
async def test_github_ref_all_candidates_fail_marks_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    resolved = ResolvedPackage(
        name="pkg",
        version="1.0.0",
        tarball_url="https://x/pkg.tgz",
        integrity="sha512-AAAA",
        repo_owner="o",
        repo_name="r",
    )
    async with _client(handler) as client:
        result = await resolve_github_ref(resolved, client=client)

    assert result.github_status == "unavailable"
    assert result.github_ref is None


@pytest.mark.asyncio
async def test_github_ref_no_repo_marks_unavailable_without_network_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    resolved = ResolvedPackage(
        name="pkg", version="1.0.0", tarball_url="https://x/pkg.tgz", integrity="sha512-AAAA"
    )
    async with _client(handler) as client:
        result = await resolve_github_ref(resolved, client=client)

    assert result.github_status == "unavailable"
    assert calls == []


@pytest.mark.asyncio
async def test_scoped_name_tag_candidate_url_encoded():
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if "%40babel%2Fcore%401.0.0" in str(request.url):
            return httpx.Response(200)
        return httpx.Response(404)

    resolved = ResolvedPackage(
        name="@babel/core",
        version="1.0.0",
        tarball_url="https://x/pkg.tgz",
        integrity="sha512-AAAA",
        repo_owner="babel",
        repo_name="babel",
    )
    async with _client(handler) as client:
        result = await resolve_github_ref(resolved, client=client)

    assert result.github_status == "resolved"
    assert result.github_ref == "@babel/core@1.0.0"


def test_github_tarball_url_is_the_single_source_of_truth():
    """The probe URL and the fetch URL must be built by the same function.

    Regression: the probe (resolve_github_ref) and the fetcher used to build
    this URL independently. For a ref like "@babel/core@7.0.0" — the exact
    monorepo-tag shape the candidate list targets — a divergence there means
    the URL that passed the probe isn't the URL that gets downloaded.
    """
    url = github_tarball_url("babel", "babel", "@babel/core@7.0.0")
    assert url == "https://codeload.github.com/babel/babel/tar.gz/%40babel%2Fcore%407.0.0"
