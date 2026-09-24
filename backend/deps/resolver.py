"""npm registry resolution + GitHub ref resolution for the dependency capability engine.

No GitHub REST API calls and no token: repository location, publisher, and the
GitHub ref candidates all come from npm registry metadata. GitHub source itself
is fetched through codeload.github.com (backend/deps/fetcher.py), which does
not count against GitHub's unauthenticated REST rate limit.
"""

import re
from datetime import datetime
from urllib.parse import quote

import httpx

from backend.models.dependencies import ResolvedPackage


_NPM_REGISTRY = "https://registry.npmjs.org"
_CODELOAD = "https://codeload.github.com"
_TIMEOUT_S = 15.0

_GITHUB_SHORTHAND_RE = re.compile(r"^github:(?P<owner>[^/]+)/(?P<repo>[^#]+?)(?:#.*)?$")
# Covers, with or without a leading "git+": https://, http://, git://, ssh:// (with
# an optional user@ prefix, e.g. git+ssh://git@github.com/...), a bare "www."
# prefix, and no scheme at all (github.com/o/r or the scp-like git@github.com:o/r).
_GIT_URL_RE = re.compile(
    r"^(?:git\+)?"
    r"(?:(?:https?|git|ssh)://)?"
    r"(?:[^@/\s]+@)?"
    r"(?:www\.)?"
    r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/#]+?)(?:\.git)?(?:#.*)?$"
)
_OWNER_REPO_RE = re.compile(r"^(?P<owner>[^/\s]+)/(?P<repo>[^/\s#]+)$")


def _encode_package_name(name: str) -> str:
    """Scoped package names (`@scope/name`) are percent-encoded in registry URLs."""
    if name.startswith("@"):
        scope, _, rest = name.partition("/")
        return f"{quote(scope, safe='')}%2F{quote(rest, safe='')}"
    return quote(name, safe="")


def _normalize_repository(
    repository: str | dict | None,
) -> tuple[str | None, str | None, str | None]:
    """Return (owner, repo, directory) from a package.json-style `repository` field.

    Accepts string form (`git+https://...`, `git+ssh://git@...`, `github:o/r`,
    `o/r` shorthand) and object form (`{"type": "git", "url": ..., "directory": ...}`).
    Only GitHub repositories resolve to (owner, repo) — anything else resolves to
    (None, None, directory), which is treated as GitHub-unavailable downstream.
    """
    if repository is None:
        return None, None, None

    directory = repository.get("directory") if isinstance(repository, dict) else None
    url = repository.get("url") if isinstance(repository, dict) else repository
    if not isinstance(url, str) or not url:
        return None, None, directory

    url = url.strip()
    for pattern in (_GIT_URL_RE, _GITHUB_SHORTHAND_RE):
        m = pattern.match(url)
        if m:
            return m.group("owner"), m.group("repo"), directory

    # Bare "owner/repo" shorthand implies GitHub by npm convention.
    m = _OWNER_REPO_RE.match(url)
    if m and "://" not in url:
        return m.group("owner"), m.group("repo"), directory

    return None, None, directory


def github_tarball_url(owner: str, repo: str, ref: str) -> str:
    """Build the codeload.github.com tarball URL for `owner/repo` at `ref`.

    The single source of truth for this URL — used both to probe candidates
    in `resolve_github_ref` and to actually download in `fetcher.fetch_source`,
    so the ref that passes the probe is guaranteed to be the ref that gets
    fetched (matters for refs with special characters, e.g. "{name}@{version}"
    monorepo tags).
    """
    return f"{_CODELOAD}/{owner}/{repo}/tar.gz/{quote(ref, safe='')}"


async def fetch_registry_doc(name: str, client: httpx.AsyncClient) -> dict:
    """Fetch the full npm registry document for `name` (all versions + time map)."""
    resp = await client.get(f"{_NPM_REGISTRY}/{_encode_package_name(name)}")
    resp.raise_for_status()
    return resp.json()


def previous_version(doc: dict, before: str) -> str | None:
    """Return the version published immediately before `before`, by publish order.

    Orders by the registry's `time` field (actual publish order), not semver —
    a patch can be republished out of semver order (deprecation + republish).
    Only versions that are both timestamped *and* still present in `versions`
    are considered: the `time` map can retain entries for unpublished/removed
    versions (and always carries non-version "created"/"modified" keys, plus,
    for a fully unpublished package, an "unpublished" object rather than a
    timestamp string) — none of those are valid predecessors. Returns None if
    `before` isn't in the resulting order or has no predecessor.
    """
    versions: dict = doc.get("versions", {})
    time_map: dict = doc.get("time", {})
    ordered = sorted(
        (v for v, ts in time_map.items() if v in versions and isinstance(ts, str)),
        key=lambda v: time_map[v],
    )
    if before not in ordered:
        return None
    idx = ordered.index(before)
    return ordered[idx - 1] if idx > 0 else None


def resolved_package_from_doc(name: str, version: str, doc: dict) -> ResolvedPackage:
    """Build a `ResolvedPackage` for `name@version` from an already-fetched registry doc."""
    version_doc = doc.get("versions", {}).get(version)
    if version_doc is None:
        raise ValueError(f"{name}@{version} not found on the npm registry")

    dist = version_doc.get("dist", {})
    tarball_url = dist.get("tarball")
    integrity = dist.get("integrity") or dist.get("shasum") or ""
    if not tarball_url:
        raise ValueError(f"{name}@{version} has no dist.tarball on the npm registry")

    owner, repo, directory = _normalize_repository(
        version_doc.get("repository") or doc.get("repository")
    )

    npm_user = version_doc.get("_npmUser") or {}
    maintainers = [m.get("name") for m in version_doc.get("maintainers", []) if m.get("name")]

    published_at = None
    time_str = doc.get("time", {}).get(version)
    if time_str:
        published_at = datetime.fromisoformat(time_str.replace("Z", "+00:00"))

    return ResolvedPackage(
        name=name,
        version=version,
        tarball_url=tarball_url,
        integrity=integrity,
        git_head=version_doc.get("gitHead"),
        repo_owner=owner,
        repo_name=repo,
        repo_directory=directory,
        publisher=npm_user.get("name"),
        maintainers=maintainers,
        published_at=published_at,
    )


async def resolve_npm(
    name: str, version: str, client: httpx.AsyncClient | None = None
) -> ResolvedPackage:
    """Resolve one `name@version` against the npm registry. Raises on network/lookup failure."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
    try:
        doc = await fetch_registry_doc(name, client)
        return resolved_package_from_doc(name, version, doc)
    finally:
        if owns_client:
            await client.aclose()


async def resolve_github_ref(
    resolved: ResolvedPackage, client: httpx.AsyncClient | None = None
) -> ResolvedPackage:
    """Probe GitHub ref candidates via codeload HEAD requests; set github_status/github_ref.

    Candidate order: gitHead -> tag "{name}@{version}" (monorepo convention used
    by Babel, Jest, most scoped packages) -> "v{version}" -> "{version}". Each
    candidate is probed independently; a 404 moves to the next. Never raises —
    a fully unresolved repo just gets github_status="unavailable" so the caller
    can proceed with npm-tarball-only scanning.
    """
    if not resolved.repo_owner or not resolved.repo_name:
        return resolved.model_copy(update={"github_status": "unavailable"})

    candidates = []
    if resolved.git_head:
        candidates.append(resolved.git_head)
    candidates.append(f"{resolved.name}@{resolved.version}")
    candidates.append(f"v{resolved.version}")
    candidates.append(resolved.version)

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
    try:
        for ref in candidates:
            url = github_tarball_url(resolved.repo_owner, resolved.repo_name, ref)
            try:
                resp = await client.head(url, follow_redirects=True)
            except httpx.HTTPError:
                continue
            if resp.status_code == 200:
                return resolved.model_copy(update={"github_status": "resolved", "github_ref": ref})

        return resolved.model_copy(update={"github_status": "unavailable"})
    finally:
        if owns_client:
            await client.aclose()
