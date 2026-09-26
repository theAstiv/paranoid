"""Deterministic install-hook risk detection over package.json lifecycle scripts.

Runs without Semgrep: lifecycle scripts are short shell command strings, not
source files, so this is pattern matching on the script text itself.
"""

import json
import posixpath
import re
from pathlib import Path


_HOOK_SCRIPTS = ("preinstall", "install", "postinstall", "prepare")

# The only lifecycle commands treated as benign. Anything else in a hook is
# flagged — a lifecycle script is itself a capability (code that runs on
# `npm install`), so unrecognized commands are surfaced rather than trusted.
_BENIGN_RE = re.compile(
    r"^(?:"
    r"husky(?:\s+install)?|"
    r"is-ci|"
    r"tsc\b.*|"
    r"node-gyp\s+rebuild|"
    r"node-gyp-build|"
    r"prebuild-install\b.*|"
    r"node-pre-gyp\s+install\b.*|"
    r"patch-package\b.*|"
    r"prisma\s+generate\b.*|"
    r"webpack\b.*|"
    r"rollup\s+.*|"
    r"vite\s+build\b.*"
    r")$"
)
# `npm run build`, `yarn build`, `pnpm run build` — delegates to another script
# in the same package.json, which is then checked in turn.
_RUN_SCRIPT_RE = re.compile(
    r"^(?:npm\s+run(?:-script)?|yarn(?:\s+run)?|pnpm(?:\s+run)?)\s+([\w:.-]+)$"
)

_PIPE_TO_SHELL_RE = re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sh|bash|node)\b")
_DOWNLOAD_RE = re.compile(r"\b(curl|wget)\b")
_NODE_EVAL_RE = re.compile(r"\bnode\s+-e\b")
_NODE_FILE_RE = re.compile(r"\bnode\s+(?!-e\b)['\"]?([^\s&|;'\"]+\.(?:c?js|mjs))['\"]?")

# Command separators: &&, ||, ;, |, a lone & (background), and newlines.
# Two-character operators come first so `&&` isn't split as two `&`.
_COMMAND_SEPARATOR_RE = re.compile(r"&&|\|\||;|\||&|\n")
# Command substitution runs arbitrary code inside an otherwise-benign command.
_SUBSTITUTION_RE = re.compile(r"`|\$\(")


def _is_flagged(
    script: str, scripts: dict, seen: frozenset[str] = frozenset()
) -> tuple[bool, str | None]:
    """Return (flagged, reason). `reason` names which heuristic fired.

    The dangerous-pattern checks run first, over the whole script, so a
    benign-looking prefix can never mask them. Then the script is split on
    shell separators and each segment must be on the benign allowlist, or be
    `npm run <name>` (and friends) pointing at a script that is itself benign.
    `"husky install && tsc"` passes; `"./evil.sh"`, `"sh install.sh"` and
    `"webpack & ./evil.sh"` are flagged.
    """
    stripped = script.strip()
    flagged_checks = (
        (_PIPE_TO_SHELL_RE, "pipes a download directly into a shell/node interpreter"),
        (_NODE_EVAL_RE, "evaluates inline JavaScript via `node -e`"),
        (_DOWNLOAD_RE, "invokes a downloader (curl/wget)"),
        (_NODE_FILE_RE, "runs a JavaScript file at install time"),
        (_SUBSTITUTION_RE, "uses shell command substitution"),
    )
    for pattern, reason in flagged_checks:
        if pattern.search(stripped):
            return True, reason

    for segment in (s.strip() for s in _COMMAND_SEPARATOR_RE.split(stripped)):
        if not segment or _BENIGN_RE.match(segment):
            continue
        run = _RUN_SCRIPT_RE.match(segment)
        if run is None:
            return True, f"runs `{segment}`, which is not on the benign allowlist"
        target_name = run.group(1)
        target = scripts.get(target_name)
        # A cycle, or a name that isn't a script here (e.g. `yarn install`),
        # adds nothing new to check.
        if target_name in seen or not isinstance(target, str):
            continue
        is_flagged, reason = _is_flagged(target, scripts, seen | {target_name})
        if is_flagged:
            return True, f"via script `{target_name}`: {reason}"
    return False, None


def is_hook_flagged(script: str, scripts: dict) -> bool:
    """Public entry point to the same benign-allowlist check `find_install_hooks`
    runs, for callers that need a yes/no on one hook script rather than the
    full `"{hook}: {command} — {reason}"` list — e.g. `backend.deps.drift`
    grading whether a hook *added* in the tarball is a strong signal or an
    allowlisted-benign one."""
    return _is_flagged(script, scripts)[0]


def _collect_node_files(script: str, scripts: dict, seen: frozenset[str], files: set[str]) -> None:
    """Walk `script` (and any `npm run <name>` it delegates to) collecting
    every `node <file>` target, so a payload behind a chain of otherwise-
    benign script names is still found."""
    for match in _NODE_FILE_RE.finditer(script):
        files.add(match.group(1))

    for segment in (s.strip() for s in _COMMAND_SEPARATOR_RE.split(script)):
        run = _RUN_SCRIPT_RE.match(segment) if segment else None
        if run is None:
            continue
        target_name = run.group(1)
        target = scripts.get(target_name)
        if target_name in seen or not isinstance(target, str):
            continue
        _collect_node_files(target, scripts, seen | {target_name}, files)


def hook_node_files_from_package_json(data: dict) -> set[str]:
    """Return package.json-relative file paths run via `node <file>` inside an
    install lifecycle hook, directly or through an `npm run <script>` chain —
    operating on an already-parsed manifest dict (shared by
    `find_install_time_files` below, which reads one from disk, and
    `backend.deps.drift`, which already has the tarball's manifest in memory
    and uses this to treat a hook's own target file as "declared by the
    manifest" for the external-build excuse, even when it isn't also named by
    main/bin/files/exports)."""
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        scripts = {}

    files: set[str] = set()
    for key in _HOOK_SCRIPTS:
        script = scripts.get(key)
        if isinstance(script, str) and script.strip():
            _collect_node_files(script, scripts, frozenset(), files)
    # Normalize so `"./lib/setup.js"` and `"lib/setup.js"` compare equal to
    # the root-relative paths `backend.deps.scanner` matches them against.
    return {posixpath.normpath(f) for f in files}


def find_install_time_files(package_json_path: Path) -> set[str]:
    """Return package.json-relative file paths run via `node <file>` inside an
    install lifecycle hook, directly or through an `npm run <script>` chain.

    A hook script itself is already a capability (`find_install_hooks`), but
    the *file it runs* deserves its own evidence marker: code that only ever
    executes at install time is easy to miss if it also happens to sit under
    a path classified TEST/EXAMPLE/BUILD.
    """
    try:
        data = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    return hook_node_files_from_package_json(data)


def find_install_hooks(package_json_path: Path) -> list[str]:
    """Return flagged (non-benign) lifecycle scripts from `package_json_path`.

    Each entry is `"{hook}: {command} — {reason}"`. A hook is flagged unless
    every command in it is on the benign allowlist (husky, tsc, bundler
    builds, node-gyp rebuild, prebuild-install, prisma generate, ...) or is
    `npm run <name>` pointing at a script that is itself benign. A `binding.gyp`
    alongside package.json (native addon build) is flagged separately since
    it isn't a lifecycle script at all.
    """
    try:
        data = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []

    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        scripts = {}

    flagged: list[str] = []
    for key in _HOOK_SCRIPTS:
        script = scripts.get(key)
        if not isinstance(script, str) or not script.strip():
            continue
        is_flagged, reason = _is_flagged(script, scripts)
        if is_flagged:
            flagged.append(f"{key}: {script} — {reason}")

    if (package_json_path.parent / "binding.gyp").is_file():
        flagged.append("binding.gyp: native addon build present")

    return flagged
