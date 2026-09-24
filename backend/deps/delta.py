"""Version-to-version capability diffing and supply-chain heuristics.

Compares two `CapabilityProfile`s (previous/current version of the same
package) plus their `ResolvedPackage` metadata, and flags the shape of
change that matches known supply-chain-compromise patterns — a small
publisher-changed patch release that adds a risky capability, an install
hook appearing for the first time, or a long-dormant package suddenly
gaining a new capability.
"""

import re

from backend.models.dependencies import CapabilityProfile, ResolvedPackage, VersionDelta
from backend.models.enums import CapabilityCategory


# packaging is PEP 440, not semver — a small local parser is used instead,
# only ever to produce the human-facing jump label.
_SEMVER_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)

# Capability categories a supply-chain compromise typically adds to gain
# control (execute code, reach the network, or run at install time).
_RISKY_CATEGORIES = frozenset(
    {
        CapabilityCategory.NETWORK,
        CapabilityCategory.PROCESS,
        CapabilityCategory.DYNAMIC_CODE,
        CapabilityCategory.BUILD_INSTALL,
    }
)
_DORMANCY_THRESHOLD_DAYS = 365.0


def _parse_semver(version: str) -> tuple[int, int, int, str | None] | None:
    m = _SEMVER_RE.match(version.strip())
    if m is None:
        return None
    return (
        int(m.group("major")),
        int(m.group("minor")),
        int(m.group("patch")),
        m.group("prerelease"),
    )


def semver_jump(previous: str, current: str) -> str:
    """Label the jump from `previous` to `current`: major/minor/patch/prerelease/unknown.

    Unparseable input on either side (non-semver version strings, which do
    occur on npm) returns "unknown" rather than raising — this label is
    informational only and never gates a flag.
    """
    prev = _parse_semver(previous)
    curr = _parse_semver(current)
    if prev is None or curr is None:
        return "unknown"

    prev_core, prev_pre = prev[:3], prev[3]
    curr_core, curr_pre = curr[:3], curr[3]

    if curr_core != prev_core:
        if curr_core[0] != prev_core[0]:
            return "major"
        if curr_core[1] != prev_core[1]:
            return "minor"
        return "patch"

    # Same major.minor.patch: a prerelease changing (including a prerelease
    # graduating to a release) is its own bucket; build metadata alone
    # (+build.5) or an identical version isn't a version bump at all.
    if prev_pre != curr_pre:
        return "prerelease"
    return "unknown"


def compute_delta(
    prev_pkg: ResolvedPackage,
    curr_pkg: ResolvedPackage,
    prev_profile: CapabilityProfile,
    curr_profile: CapabilityProfile,
) -> VersionDelta:
    """Diff two versions of the same package's capabilities and metadata.

    Category comparisons operate on `category_set()` — shipped evidence
    only, matching `CapabilityProfile`'s own rule that `capability_vector`
    is display-only and never diffed directly.
    """
    prev_categories = prev_profile.category_set()
    curr_categories = curr_profile.category_set()

    days_since_previous_publish = None
    if prev_pkg.published_at is not None and curr_pkg.published_at is not None:
        days_since_previous_publish = (
            curr_pkg.published_at - prev_pkg.published_at
        ).total_seconds() / 86400

    delta = VersionDelta(
        name=curr_pkg.name,
        previous_version=prev_pkg.version,
        current_version=curr_pkg.version,
        categories_added=sorted(curr_categories - prev_categories, key=lambda c: c.value),
        categories_removed=sorted(prev_categories - curr_categories, key=lambda c: c.value),
        publisher_changed=bool(
            prev_pkg.publisher and curr_pkg.publisher and prev_pkg.publisher != curr_pkg.publisher
        ),
        previous_publisher=prev_pkg.publisher,
        current_publisher=curr_pkg.publisher,
        days_since_previous_publish=days_since_previous_publish,
        install_hooks_added=sorted(
            set(curr_profile.install_hooks) - set(prev_profile.install_hooks)
        ),
        semver_jump=semver_jump(prev_pkg.version, curr_pkg.version),
    )
    return delta.model_copy(update={"flags": supply_chain_flags(delta)})


def supply_chain_flags(delta: VersionDelta) -> list[str]:
    """Heuristic supply-chain-compromise flags for an already-computed delta."""
    flags = []

    if (
        delta.semver_jump in ("patch", "minor")
        and delta.publisher_changed
        and set(delta.categories_added) & _RISKY_CATEGORIES
    ):
        flags.append("suspicious_capability_addition")

    if delta.install_hooks_added:
        flags.append("install_hook_added")

    if (
        delta.days_since_previous_publish is not None
        and delta.days_since_previous_publish > _DORMANCY_THRESHOLD_DAYS
        and delta.categories_added
    ):
        flags.append("dormant_package_new_capability")

    return flags
