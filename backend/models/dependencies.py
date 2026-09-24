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
    status: Literal["ok", "semgrep_unavailable", "semgrep_timeout", "semgrep_error"] = "ok"

    def category_set(self) -> set[CapabilityCategory]:
        """Categories backed by shipped evidence — the basis for all comparisons."""
        return {e.category for e in self.evidence if e.path_class == PathClass.SHIPPED}
