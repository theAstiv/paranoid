"""Pydantic models for the dependency capability engine (npm/JS+TS, Layer 1)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.models.enums import CapabilityCategory, PathClass, SourceKind


class PackageRef(BaseModel):
    """A dependency as requested — name + version, nothing resolved yet."""

    name: str
    version: str


class ResolvedPackage(BaseModel):
    """npm registry metadata for one `name@version`, plus GitHub resolution status."""

    name: str
    version: str
    tarball_url: str
    integrity: str  # dist.integrity SSRI string, e.g. "sha512-..."

    git_head: str | None = None
    repo_owner: str | None = None
    repo_name: str | None = None
    repo_directory: str | None = None  # monorepo subdirectory, e.g. "packages/core"

    publisher: str | None = None  # _npmUser.name
    maintainers: list[str] = Field(default_factory=list)
    published_at: datetime | None = None

    github_status: Literal["resolved", "unavailable", "not_attempted"] = "not_attempted"
    github_ref: str | None = None  # the ref that actually resolved on codeload


class CapabilityEvidence(BaseModel):
    """One static-analysis match backing a capability finding."""

    category: CapabilityCategory
    rule_id: str
    file: str
    line: int
    snippet: str
    source_kind: SourceKind
    path_class: PathClass
    # Set when `backend.deps.references` found a relative require()/import
    # chain from a shipped entry point into a file path-classified TEST/
    # EXAMPLE/BUILD — `path_class` above is then SHIPPED (the promoted
    # value) and this field holds what `classify_path()` originally said.
    reclassified_from: PathClass | None = None
    # Where the promotion came from — another file's relative path (reachability),
    # or "package.json (install hook)" when it's promoted because a lifecycle
    # hook runs it directly. None when `reclassified_from` is None.
    reclassified_via: str | None = None
    # True when `backend.deps.install_hooks.find_install_time_files` found
    # this file executed directly by a package.json lifecycle hook (e.g.
    # `postinstall: node scripts/setup.js`) — code that runs on `npm install`
    # regardless of whether anything ever imports it at runtime.
    install_time: bool = False


class CapabilityProfile(BaseModel):
    """The result of scanning one package's source for a given `SourceKind`."""

    name: str
    version: str
    source_kind: SourceKind
    evidence: list[CapabilityEvidence] = Field(default_factory=list)
    install_hooks: list[str] = Field(default_factory=list)
    # Display-only summary of evidence categories — never diffed as strings.
    # Comparisons always operate on category sets built from `evidence`.
    capability_vector: list[CapabilityCategory] = Field(default_factory=list)
    # "partial_fetch": some source files couldn't be extracted (Windows
    # path-length limit) — set by the CLI from FetchResult.skipped_long_paths
    # when the scan itself otherwise finished cleanly. Deliberately != "ok"
    # so `backend.deps.drift.compare_sources` treats it the same as an
    # incomplete scan, without drift.py needing to know about fetch-time skips.
    status: Literal[
        "ok", "semgrep_unavailable", "semgrep_timeout", "semgrep_error", "partial_fetch"
    ] = "ok"
    skipped_long_paths: int = 0
    skipped_link_names: list[str] = Field(default_factory=list)
    # Exact names of the files skipped for `skipped_long_paths`, from
    # `FetchResult.skipped_long_path_names`. `backend.deps.drift` matches
    # these by exact name rather than recomputing the length check itself —
    # the fetch-time check runs against a longer temporary staging path than
    # the final cache path drift sees, so recomputing it against the final
    # path would miss names in the gap between the two.
    skipped_long_path_names: list[str] = Field(default_factory=list)
    # Set (GitHub only) when this package wasn't found at the wrapper root of
    # its repo and `backend.deps.fetcher` had to discover which subdirectory
    # actually declares it — e.g. "npm/esbuild" for esbuild's Go-language
    # monorepo. None when the whole tarball (or a registry-declared
    # `repository.directory`) was already the right scope.
    discovered_directory: str | None = None
    # Root-relative paths of files reachable via a relative require()/import
    # with a non-standard extension (see backend.deps.references
    # .find_reachable_unscanned_files) that exceeded
    # backend.deps.scanner._MAX_EXTRA_TARGETS_TOTAL and so were never actually
    # scanned by Semgrep — never silently dropped: a status="ok" profile with
    # unscanned reachable code would otherwise let an attacker who knows the
    # cap hide a payload past it. backend.deps.drift treats a non-empty list
    # here the same as a package-identity mismatch — a strong signal on its
    # own, since "this code exists and executes, but we never checked it" is
    # itself the finding.
    unscanned_reachable_files: list[str] = Field(default_factory=list)

    def category_set(self) -> set[CapabilityCategory]:
        """Categories backed by shipped evidence — the basis for all comparisons.

        A flagged install hook is itself a capability (code that runs on
        `npm install`), so it counts toward BUILD_INSTALL here even though it
        has no corresponding `CapabilityEvidence` entry — `install_hooks` is
        deterministic pattern matching over package.json, not a Semgrep rule.
        """
        categories = {e.category for e in self.evidence if e.path_class == PathClass.SHIPPED}
        if self.install_hooks:
            categories.add(CapabilityCategory.BUILD_INSTALL)
        return categories


class VersionDelta(BaseModel):
    """What changed in a package's capabilities between two published versions."""

    name: str
    previous_version: str
    current_version: str
    categories_added: list[CapabilityCategory] = Field(default_factory=list)
    categories_removed: list[CapabilityCategory] = Field(default_factory=list)
    publisher_changed: bool = False
    previous_publisher: str | None = None
    current_publisher: str | None = None
    days_since_previous_publish: float | None = None
    install_hooks_added: list[str] = Field(default_factory=list)
    semver_jump: Literal["major", "minor", "patch", "prerelease", "unknown"] = "unknown"
    # Supply-chain heuristics from `backend.deps.delta.supply_chain_flags` —
    # "suspicious_capability_addition" | "install_hook_added" |
    # "dormant_package_new_capability".
    flags: list[str] = Field(default_factory=list)


class DriftReport(BaseModel):
    """Comparison of a package's npm-tarball source against its GitHub source.

    Every tarball-only file is classified into exactly one bucket below.
    Provenance (matched/sourcemap/build/bundled) narrows which capability
    *categories* a file is excused for — it never excuses all of them by
    itself. `signal` is true when any file's non-excused ("novel") category
    is entirely absent from the GitHub scan (`signal_files`, summarized in
    `signal_categories`), or when the tarball's package.json declares a
    lifecycle hook the GitHub package.json doesn't (`install_hooks_added`).
    A novel category that merely exists *elsewhere* in the GitHub scan is
    downgraded to informational (`relocated`) — see `backend.deps.drift`.
    """

    name: str
    version: str
    status: Literal[
        "compared",
        "skipped_github_unavailable",
        "skipped_npm_unavailable",
        "skipped_scan_incomplete",
    ] = "skipped_github_unavailable"
    matched: list[str] = Field(default_factory=list)
    explained_by_sourcemap: list[str] = Field(default_factory=list)
    explained_by_build: list[str] = Field(default_factory=list)
    bundled_dependency: list[str] = Field(default_factory=list)
    unexplained: list[str] = Field(default_factory=list)
    # Tarball-only files that fall through every explained bucket, but whose
    # exact path is one GitHub's `CapabilityProfile` recorded as skipped (a
    # symlink, or a path exceeding the platform's length limit) — "GitHub
    # doesn't have this" and "GitHub couldn't extract this" aren't the same
    # thing, so these never produce a signal.
    unverifiable: list[str] = Field(default_factory=list)
    signal: bool = False
    # {file: [novel categories absent from the GitHub scan entirely]} — the
    # strong findings that make `signal` true.
    signal_files: dict[str, list[CapabilityCategory]] = Field(default_factory=dict)
    # Union of every category in `signal_files`, for a quick top-line summary.
    signal_categories: list[CapabilityCategory] = Field(default_factory=list)
    # Informational: a file's novel category that already exists somewhere
    # else in the GitHub scan — not absent, so not a strong signal.
    relocated: list[dict] = Field(default_factory=list)
    # {file: [{category, rule_id, snippet}]} — evidence present on a *matched*
    # tarball file but not on its GitHub counterpart, even when the category
    # itself isn't novel (e.g. a second network call appended to a file that
    # already made one). Informational.
    new_evidence_in_matched: dict[str, list[dict]] = Field(default_factory=dict)
    # Lifecycle hook names (preinstall/install/postinstall/prepare) the
    # tarball's package.json declares (or changed) that the GitHub package.json
    # doesn't — a strong signal on its own, folded into `signal_files["package.json"]`.
    install_hooks_added: list[str] = Field(default_factory=list)
    # Set when status != "compared": a specific reason for the skip, e.g.
    # "github_unresolved", "repo_directory_missing", "path_too_long", or
    # "github_fetch_rejected:<ErrorType>" — so a "compared" rate can be
    # computed without every skip collapsing into one opaque status string.
    skip_reason: str | None = None
