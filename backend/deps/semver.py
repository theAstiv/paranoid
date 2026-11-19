"""A small semver parser and npm range check for the dependency engine.

`packaging` is PEP 440, not semver, so the engine keeps its own. The range
check is deliberately conservative: it answers True/False only for range
syntax it models (exact, `=`, comparators, caret, tilde, x-ranges, hyphen
ranges, `||`) and a release pin; anything else (git/file/url specs, `npm:`
aliases, `workspace:`, a prerelease pin) is None, "can't tell". Callers warn
only on a definite False (BB-54).
"""

import re


_SEMVER_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)

# A partial version in a range: "1", "1.2", "1.x", "1.2.*", "1.2.3-beta.1".
_PARTIAL_RE = re.compile(
    r"^v?(?P<major>\d+|[xX*])"
    r"(?:\.(?P<minor>\d+|[xX*]))?"
    r"(?:\.(?P<patch>\d+|[xX*]))?"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)
_HYPHEN_RE = re.compile(r"^\s*(\S+)\s+-\s+(\S+)\s*$")
_RANGE_CHARS_RE = re.compile(r"^[\s0-9A-Za-z.+\-^~<>=|*]*$")
_OPERATOR_SPACE_RE = re.compile(r"(<=|>=|<|>|=|\^|~)\s+")
_TOKEN_RE = re.compile(r"^(<=|>=|<|>|=|\^|~)?(.*)$")

type Version = tuple[int, int, int, str | None]
type Partial = tuple[int | None, int | None, int | None, str | None]
# (operator, (major, minor, patch, prerelease)) with operator in < <= > >= =
type Comparator = tuple[str, Version]


def parse_version(version: str) -> Version | None:
    """(major, minor, patch, prerelease) for a full semver string, else None."""
    m = _SEMVER_RE.match(version.strip())
    if m is None:
        return None
    return (
        int(m.group("major")),
        int(m.group("minor")),
        int(m.group("patch")),
        m.group("prerelease"),
    )


def satisfies(version: str, range_str: str) -> bool | None:
    """Whether `version` is inside the npm range `range_str`; None when unknown."""
    parsed = parse_version(version)
    if parsed is None or parsed[3] is not None:
        # A prerelease only matches ranges that name one on the same core
        # (npm's rule); not modelled, so don't guess.
        return None
    if not _RANGE_CHARS_RE.match(range_str):
        return None
    results = [_set_satisfied(parsed, part) for part in range_str.split("||")]
    if any(r is True for r in results):
        return True
    if any(r is None for r in results):
        return None
    return False


def _set_satisfied(version: Version, comparator_set: str) -> bool | None:
    comparators = _parse_set(comparator_set)
    if comparators is None:
        return None
    return all(_compare_ok(version, op, bound) for op, bound in comparators)


def _parse_set(text: str) -> list[Comparator] | None:
    text = text.strip()
    hyphen = _HYPHEN_RE.match(text)
    if hyphen:
        low = _desugar(">=", hyphen.group(1))
        high = _desugar("<=", hyphen.group(2))
        return None if low is None or high is None else low + high
    comparators: list[Comparator] = []
    for token in _OPERATOR_SPACE_RE.sub(r"\1", text).split():
        op, rest = _TOKEN_RE.match(token).groups()
        desugared = _desugar(op or "", rest)
        if desugared is None:
            return None
        comparators.extend(desugared)
    return comparators


def _parse_partial(text: str) -> Partial | None:
    m = _PARTIAL_RE.match(text)
    if m is None:
        return None

    def _num(group: str) -> int | None:
        value = m.group(group)
        return int(value) if value is not None and value.isdigit() else None

    major, minor, patch = _num("major"), _num("minor"), _num("patch")
    # "1.x.3" isn't meaningful; a wildcard ends the version.
    if (major is None and (minor is not None or patch is not None)) or (
        minor is None and patch is not None
    ):
        return None
    prerelease = m.group("prerelease") if patch is not None else None
    return major, minor, patch, prerelease


def _desugar(op: str, text: str) -> list[Comparator] | None:  # noqa: PLR0911 - one case per operator
    """Turn one range token into plain comparators; [] matches anything."""
    partial = _parse_partial(text)
    if partial is None:
        return None
    major, minor, patch, pre = partial

    if major is None:
        # "*", "x", ">=*": anything. "<*" or ">*" matches nothing; not worth modelling.
        return [] if op in ("", "=", ">=", "^", "~") else None

    floor: Version = (major, minor or 0, patch or 0, pre)

    def _next_major() -> Version:
        return (major + 1, 0, 0, None)

    def _next_minor() -> Version:
        return (major, (minor or 0) + 1, 0, None)

    if op == "^":
        if minor is None:
            upper = _next_major()
        elif patch is None:
            upper = _next_major() if major > 0 else _next_minor()
        elif major > 0:
            upper = _next_major()
        elif minor > 0:
            upper = _next_minor()
        else:
            upper = (0, 0, patch + 1, None)
        return [(">=", floor), ("<", upper)]
    if op == "~":
        upper = _next_major() if minor is None else _next_minor()
        return [(">=", floor), ("<", upper)]
    if op in ("", "="):
        if minor is None:
            return [(">=", floor), ("<", _next_major())]
        if patch is None:
            return [(">=", floor), ("<", _next_minor())]
        return [("=", floor)]
    if op == ">=":
        return [(">=", floor)]
    if op == ">":
        if minor is None:
            return [(">=", _next_major())]
        if patch is None:
            return [(">=", _next_minor())]
        return [(">", floor)]
    if op == "<":
        return [("<", floor)]
    if op == "<=":
        if minor is None:
            return [("<", _next_major())]
        if patch is None:
            return [("<", _next_minor())]
        return [("<=", floor)]
    return None


def _key(v: Version) -> tuple[int, int, int, int]:
    # Only orders a release against a release or a prerelease bound: a
    # prerelease sorts just below the release with the same core. Prerelease
    # pins never reach here (satisfies() returns None for them).
    return (v[0], v[1], v[2], 0 if v[3] is not None else 1)


def _compare_ok(version: Version, op: str, bound: Version) -> bool:
    a, b = _key(version), _key(bound)
    match op:
        case "<":
            return a < b
        case "<=":
            return a <= b
        case ">":
            return a > b
        case ">=":
            return a >= b
        case _:
            return a == b
