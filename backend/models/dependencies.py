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

    def category_set(self) -> set[CapabilityCategory]:
        """Categories backed by shipped evidence — the basis for all comparisons."""
        return {e.category for e in self.evidence if e.path_class == PathClass.SHIPPED}


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
    `signal` is true only when an `unexplained` file carries a capability
    category absent from the GitHub scan (`unexplained_categories`) — the
    one drift finding strong enough to surface as a flag rather than
    information (see `backend.deps.drift`).
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
    signal: bool = False
    unexplained_categories: list[CapabilityCategory] = Field(default_factory=list)
    # Set when status != "compared": a specific reason for the skip, e.g.
    # "github_unresolved", "repo_directory_missing", "path_too_long", or
    # "github_fetch_rejected:<ErrorType>" — so a "compared" rate can be
    # computed without every skip collapsing into one opaque status string.
    skip_reason: str | None = None
