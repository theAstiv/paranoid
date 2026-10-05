#!/usr/bin/env python3
"""Generate the ATT&CK / ATLAS technique catalog consumed by map_techniques.

Usage:
    python scripts/build_techniques.py

Fetches MITRE's published data over HTTPS and emits:
    seeds/techniques/attack_enterprise.json
    seeds/techniques/atlas.json

Each file is a JSON object:
    {"generated": "...", "source": "...", "source_version": "...",
     "attribution": "...", "techniques": [{id, name, tactics, description, url}]}

ATT&CK Enterprise is filtered to techniques tagged with a cloud/SaaS/identity
platform (the slice this project's seeds and dependency engine care about)
plus an explicit include-list of IDs referenced by backend/deps/threats.py's
rule_id -> technique mapping, so dependency-threat technique IDs always
resolve. ATLAS is small and AI/ML-focused already (~170 techniques), so it is
taken in full.

Deprecated/revoked techniques are skipped, but when an explicitly-included ID
has been revoked, its MITRE-recorded replacement is substituted automatically
and a note is printed — MITRE periodically restructures tactics (e.g. the
whole T1562 "Impair Defenses" family was revoked and replaced by new
techniques under the newer "Defense Impairment" / "Stealth" tactics in a 2025
ATT&CK update; this script would silently pick up the replacement rather than
emit a dead ID).

If the live fetch fails (offline, MITRE unreachable), this script falls back
to a small hand-written subset covering exactly the IDs
backend/deps/threats.py's rule_id mapping needs, so map_techniques degrades
gracefully rather than crashing. Regenerate with network access for the full
catalog.

License: MITRE ATT&CK and ATLAS content is used under MITRE's terms of use
(https://attack.mitre.org/resources/terms-of-use/, https://atlas.mitre.org) —
this script carries no modification of their text beyond truncation.
"""

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ATTACK_STIX_URL = (
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/"
    "master/enterprise-attack/enterprise-attack.json"
)
ATLAS_YAML_URL = "https://raw.githubusercontent.com/mitre-atlas/atlas-data/main/dist/ATLAS.yaml"
FETCH_TIMEOUT_SECONDS = 30

# Platforms that define "the cloud-relevant slice" of ATT&CK Enterprise this
# project's seeds and dependency engine target.
_CLOUD_PLATFORMS = {"IaaS", "SaaS", "Office Suite", "Identity Provider", "Containers"}

# IDs backend/deps/threats.py's rule_id -> technique mapping (map_techniques
# step) depends on. Always included even if not platform-tagged, and
# resolved through a revoked-by replacement if MITRE has retired the ID.
_ATTACK_EXPLICIT_INCLUDE = {
    "T1195.002",  # Compromise Software Supply Chain -> drift_signal
    "T1059",  # Command and Scripting Interpreter -> install_hook_*
    "T1027",  # Obfuscated Files or Information -> dynamic_code
    "T1552",  # Unsecured Credentials -> network_environment
    "T1567",  # Exfiltration Over Web Service -> network_environment
    "T1620",  # Reflective Code Loading -> native_ffi
}

# Minimal offline fallback: exactly what backend/deps/threats.py needs, so
# map_techniques still works without network access. No tactics/url beyond
# what's hand-verifiable here; regenerate for real coverage when online.
_ATTACK_FALLBACK: list[dict[str, Any]] = [
    {
        "id": "T1195.002",
        "name": "Compromise Software Supply Chain",
        "tactics": ["Initial Access"],
        "description": "Manipulation of software dependencies or development "
        "tools prior to the final distribution of a product.",
        "url": "https://attack.mitre.org/techniques/T1195/002",
    },
    {
        "id": "T1059",
        "name": "Command and Scripting Interpreter",
        "tactics": ["Execution"],
        "description": "Abuse of command and script interpreters to execute "
        "commands, scripts, or binaries.",
        "url": "https://attack.mitre.org/techniques/T1059",
    },
    {
        "id": "T1027",
        "name": "Obfuscated Files or Information",
        "tactics": ["Stealth"],
        "description": "Obfuscation of content to make it harder to discover "
        "or analyze.",
        "url": "https://attack.mitre.org/techniques/T1027",
    },
    {
        "id": "T1552",
        "name": "Unsecured Credentials",
        "tactics": ["Credential Access"],
        "description": "Searching for and collecting credentials stored in "
        "files, environment variables, or other unsecured locations.",
        "url": "https://attack.mitre.org/techniques/T1552",
    },
    {
        "id": "T1567",
        "name": "Exfiltration Over Web Service",
        "tactics": ["Exfiltration"],
        "description": "Transferring data to a legitimate external web "
        "service rather than a dedicated C2 channel.",
        "url": "https://attack.mitre.org/techniques/T1567",
    },
    {
        "id": "T1620",
        "name": "Reflective Code Loading",
        "tactics": ["Stealth"],
        "description": "Loading self-contained or reflective payloads into a "
        "process's memory outside the normal module loading path.",
        "url": "https://attack.mitre.org/techniques/T1620",
    },
]


def _fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(  # noqa: S310 - fixed https URLs only, see module constants
        url, headers={"User-Agent": "paranoid-build-techniques"}
    )
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:  # noqa: S310
        return resp.read()


def _clean_description(text: str) -> str:
    """Citations/markdown stripped, capped at ~600 chars for a compact entry.

    Keeps enough detail for embedding-similarity matching to work (a
    one-or-two-sentence summary was tried first and lost too much of the
    distinguishing detail between sibling sub-techniques — see the
    map_techniques golden-set test).
    """
    text = re.sub(r"\(Citation:[^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= 600:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept: list[str] = []
    total = 0
    for sentence in sentences:
        if total + len(sentence) > 600 and kept:
            break
        kept.append(sentence)
        total += len(sentence)
    return " ".join(kept).strip()


def _load_attack_bundle(url: str) -> dict[str, Any]:
    return json.loads(_fetch_bytes(url))


def build_attack_catalog(bundle: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Return (techniques, version) from a fetched ATT&CK Enterprise STIX bundle."""
    objects = bundle.get("objects", [])
    by_stix_id = {o["id"]: o for o in objects if "id" in o}

    tactic_names: dict[str, str] = {}
    for obj in objects:
        if obj.get("type") == "x-mitre-tactic":
            shortname = obj.get("x_mitre_shortname")
            if shortname:
                tactic_names[shortname] = obj.get("name", shortname)

    revoked_by: dict[str, str] = {}
    for obj in objects:
        if obj.get("type") == "relationship" and obj.get("relationship_type") == "revoked-by":
            revoked_by[obj["source_ref"]] = obj["target_ref"]

    patterns = [o for o in objects if o.get("type") == "attack-pattern"]

    def external_id(pattern: dict[str, Any]) -> str | None:
        for ref in pattern.get("external_references", []):
            if ref.get("source_name") == "mitre-attack":
                return ref.get("external_id")
        return None

    def url_for(pattern: dict[str, Any]) -> str:
        for ref in pattern.get("external_references", []):
            if ref.get("source_name") == "mitre-attack":
                return ref.get("url", "")
        return ""

    def resolve_active(pattern: dict[str, Any]) -> dict[str, Any] | None:
        """Follow revoked-by once to an active replacement, if any."""
        seen = set()
        current = pattern
        while current.get("revoked") or current.get("x_mitre_deprecated"):
            stix_id = current["id"]
            if stix_id in seen:
                return None
            seen.add(stix_id)
            replacement_ref = revoked_by.get(stix_id)
            if not replacement_ref or replacement_ref not in by_stix_id:
                return None
            current = by_stix_id[replacement_ref]
        return current

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_pattern in patterns:
        eid = external_id(raw_pattern)
        if not eid:
            continue
        platforms = set(raw_pattern.get("x_mitre_platforms", []) or [])
        explicitly_wanted = eid in _ATTACK_EXPLICIT_INCLUDE
        if not explicitly_wanted and not (platforms & _CLOUD_PLATFORMS):
            continue

        resolved = resolve_active(raw_pattern)
        if resolved is None:
            if explicitly_wanted:
                print(f"[warn] {eid} is revoked/deprecated with no replacement found", file=sys.stderr)
            continue
        pattern = resolved
        if resolved is not raw_pattern:
            new_id = external_id(resolved)
            print(f"[info] {eid} revoked -> using replacement {new_id} ({resolved.get('name')})", file=sys.stderr)
            eid = new_id
            if not eid:
                continue

        if eid in seen_ids:
            continue
        seen_ids.add(eid)

        tactics = [
            tactic_names.get(kc["phase_name"], kc["phase_name"])
            for kc in pattern.get("kill_chain_phases", [])
            if kc.get("kill_chain_name") == "mitre-attack"
        ]
        results.append(
            {
                "id": eid,
                "name": pattern.get("name", eid),
                "tactics": tactics,
                "description": _clean_description(pattern.get("description", "")),
                "url": url_for(pattern),
            }
        )

    missing = _ATTACK_EXPLICIT_INCLUDE - seen_ids
    if missing:
        print(f"[warn] explicit-include IDs never resolved: {sorted(missing)}", file=sys.stderr)

    results.sort(key=lambda t: t["id"])
    version = next(
        (o.get("x_mitre_version", "unknown") for o in objects if o.get("type") == "x-mitre-collection"),
        "unknown",
    )
    return results, version


def build_atlas_catalog(data: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Return (techniques, version) from a fetched ATLAS.yaml document."""
    matrix = data.get("matrices", [{}])[0]
    tactic_names = {t["id"]: t["name"] for t in matrix.get("tactics", [])}
    raw_techniques = matrix.get("techniques", [])
    by_id = {t["id"]: t for t in raw_techniques}

    def tactics_for(tech: dict[str, Any]) -> list[str]:
        tactic_ids = tech.get("tactics")
        if tactic_ids:
            return [tactic_names.get(tid, tid) for tid in tactic_ids]
        parent_id = tech.get("specializes")
        if parent_id and parent_id in by_id:
            return tactics_for(by_id[parent_id])
        return []

    results: list[dict[str, Any]] = []
    for tech in raw_techniques:
        results.append(
            {
                "id": tech["id"],
                "name": tech.get("name", tech["id"]),
                "tactics": tactics_for(tech),
                "description": _clean_description(tech.get("description", "")),
                "url": f"https://atlas.mitre.org/techniques/{tech['id']}",
            }
        )

    results.sort(key=lambda t: t["id"])
    return results, str(data.get("version", "unknown"))


def _write_catalog(path: Path, techniques: list[dict[str, Any]], source: str, version: str) -> None:
    payload = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": source,
        "source_version": version,
        "attribution": "MITRE ATT&CK (c) 2025 MITRE Corporation, used under "
        "https://attack.mitre.org/resources/terms-of-use/; MITRE ATLAS (c) "
        "2025 MITRE Corporation, used under https://atlas.mitre.org terms.",
        "techniques": techniques,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(techniques)} techniques -> {path}")


def main() -> None:
    seeds_dir = Path(__file__).parent.parent / "seeds" / "techniques"
    seeds_dir.mkdir(parents=True, exist_ok=True)

    try:
        bundle = _load_attack_bundle(ATTACK_STIX_URL)
        attack_techniques, attack_version = build_attack_catalog(bundle)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as e:
        print(f"[warn] ATT&CK live fetch failed ({e}); using offline fallback", file=sys.stderr)
        attack_techniques, attack_version = list(_ATTACK_FALLBACK), "offline-fallback"

    _write_catalog(
        seeds_dir / "attack_enterprise.json",
        attack_techniques,
        "https://github.com/mitre-attack/attack-stix-data (enterprise-attack)",
        attack_version,
    )

    try:
        import yaml

        atlas_bytes = _fetch_bytes(ATLAS_YAML_URL)
        atlas_data = yaml.safe_load(atlas_bytes)
        atlas_techniques, atlas_version = build_atlas_catalog(atlas_data)
    except ImportError:
        print("[warn] PyYAML not installed (pip install pyyaml); skipping ATLAS live fetch", file=sys.stderr)
        atlas_techniques, atlas_version = [], "offline-fallback"
    except (urllib.error.URLError, OSError, KeyError) as e:
        print(f"[warn] ATLAS live fetch failed ({e}); no offline fallback for ATLAS", file=sys.stderr)
        atlas_techniques, atlas_version = [], "offline-fallback"

    _write_catalog(
        seeds_dir / "atlas.json",
        atlas_techniques,
        "https://github.com/mitre-atlas/atlas-data (ATLAS.yaml)",
        atlas_version,
    )


if __name__ == "__main__":
    main()
