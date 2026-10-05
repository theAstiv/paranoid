"""The map_techniques pipeline node: deterministic, no LLM involved.

Attaches MITRE ATT&CK / ATLAS technique matches to every threat in a
ThreatsList. Pure function wrapping backend.rules.techniques.match_techniques
over each threat — kept as its own node module (not helpers.py) since it
operates on ThreatsList rather than building prompt text.
"""

import logging

from backend.models.state import ThreatsList
from backend.rules.techniques import match_techniques


logger = logging.getLogger(__name__)


def map_threat_techniques(threats: ThreatsList) -> tuple[ThreatsList, int]:
    """Set attack_techniques on every threat; return (threats, techniques_matched).

    Never raises — a failure to match a given threat just leaves its
    attack_techniques empty, logged at warning level, so one bad threat
    can't fail the whole pipeline step.
    """
    techniques_matched = 0
    for threat in threats.threats:
        try:
            threat.attack_techniques = match_techniques(threat)
        except (ValueError, RuntimeError, KeyError) as e:
            logger.warning(f"Technique matching failed for threat '{threat.name}': {e}")
            threat.attack_techniques = []
        techniques_matched += len(threat.attack_techniques)
    return threats, techniques_matched
