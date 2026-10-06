"""CVSS v3.1 base-scoring instruction block, appended to the STRIDE/MAESTRO
threat-generation prompts only when the run's scoring_method includes "cvss"
(gated in backend/pipeline/nodes/threats.py's generate_threats(), the same
"append only if relevant" shape helpers.py uses for dependency_capabilities).

Prompt change justified per RULES.md: this adds a second, opt-in scoring
model that asks the LLM for the eight CVSS v3.1 base metrics using a fixed,
constrained vocabulary. The numeric score and severity are never trusted
from the LLM — backend.scoring.cvss31.score_and_severity_from_metrics()
computes them server-side from these metrics right after the provider call
(see Threat.cvss_score/cvss_severity in backend/models/state.py).
"""


def cvss_scoring_section() -> str:
    """CVSS v3.1 Base Scoring instructions, spliced into a threat-generation
    or improve-iteration prompt (before its closing </instructions> tag —
    see _insert_before_closing_instructions in threats.py) when
    scoring_method != "dread". Deliberately unnumbered: it's spliced into four prompts whose
    own numbered sections end at different numbers (7, 8, 9, 9), so a fixed
    number here would either skip one or collide with an existing section."""
    return """

**CVSS v3.1 Base Scoring** (in addition to DREAD, when requested):
   For each threat, also provide a CVSS v3.1 base vector. Use ONLY these
   single-letter codes per metric — do not invent other values and do not
   compute or report a numeric score yourself; the score is always computed
   server-side from the eight codes below.

   ### CVSS v3.1 BASE METRICS
   * **Attack Vector (AV)**: N (Network) | A (Adjacent) | L (Local) | P (Physical)
   * **Attack Complexity (AC)**: L (Low) | H (High)
   * **Privileges Required (PR)**: N (None) | L (Low) | H (High)
   * **User Interaction (UI)**: N (None) | R (Required)
   * **Scope (S)**: U (Unchanged) | C (Changed)
   * **Confidentiality (C)**: N (None) | L (Low) | H (High)
   * **Integrity (I)**: N (None) | L (Low) | H (High)
   * **Availability (A)**: N (None) | L (Low) | H (High)

   **CVSS Assessment**:
     - Attack Vector: [N/A/L/P]
     - Attack Complexity: [L/H]
     - Privileges Required: [N/L/H]
     - User Interaction: [N/R]
     - Scope: [U/C]
     - Confidentiality: [N/L/H]
     - Integrity: [N/L/H]
     - Availability: [N/L/H]
"""
