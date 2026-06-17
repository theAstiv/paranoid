"""Tests for backend/pipeline/input_parser.py.

Covers all 12 functions:
  Private helpers:   _extract_xml_section, _extract_bulleted_list,
                     _extract_key_value, _extract_subsections
  Public parsers:    parse_stride_component_description,
                     parse_maestro_component_description,
                     parse_stride_assumptions,
                     parse_maestro_assumptions
  Detection:         detect_input_format
  Formatters:        format_structured_description_for_prompt,
                     format_structured_assumptions_for_prompt
"""

from backend.pipeline.input_parser import (
    _extract_bulleted_list,
    _extract_key_value,
    _extract_subsections,
    _extract_xml_section,
    detect_input_format,
    format_structured_assumptions_for_prompt,
    format_structured_description_for_prompt,
    parse_maestro_assumptions,
    parse_maestro_component_description,
    parse_stride_assumptions,
    parse_stride_component_description,
)


# ---------------------------------------------------------------------------
# _extract_xml_section
# ---------------------------------------------------------------------------


def test_extract_xml_section_basic():
    text = "<foo>hello world</foo>"
    assert _extract_xml_section(text, "foo") == "hello world"


def test_extract_xml_section_strips_whitespace():
    text = "<foo>  content  </foo>"
    assert _extract_xml_section(text, "foo") == "content"


def test_extract_xml_section_multiline():
    text = "<foo>\nline1\nline2\n</foo>"
    result = _extract_xml_section(text, "foo")
    assert "line1" in result
    assert "line2" in result


def test_extract_xml_section_case_insensitive():
    text = "<FOO>data</FOO>"
    assert _extract_xml_section(text, "foo") == "data"


def test_extract_xml_section_missing_returns_none():
    assert _extract_xml_section("no tags here", "foo") is None


def test_extract_xml_section_nested_content():
    text = "<outer><component_description>inner content</component_description></outer>"
    assert _extract_xml_section(text, "component_description") == "inner content"


# ---------------------------------------------------------------------------
# _extract_bulleted_list
# ---------------------------------------------------------------------------


def test_extract_bulleted_list_dash_bullets():
    text = "**Controls:**\n- item one\n- item two\n- item three"
    result = _extract_bulleted_list(text, "Controls:")
    assert result == ["item one", "item two", "item three"]


def test_extract_bulleted_list_star_bullets():
    text = "**Controls:**\n* item one\n* item two"
    result = _extract_bulleted_list(text, "Controls:")
    assert result == ["item one", "item two"]


def test_extract_bulleted_list_stops_at_next_header():
    text = "**Section A:**\n- item1\n**Section B:**\n- item2"
    result = _extract_bulleted_list(text, "Section A:")
    assert result == ["item1"]
    assert "item2" not in result


def test_extract_bulleted_list_header_not_found():
    result = _extract_bulleted_list("no headers here", "Missing:")
    assert result == []


def test_extract_bulleted_list_empty_section():
    text = "**Controls:**\n\n**Next:**\n- other"
    result = _extract_bulleted_list(text, "Controls:")
    assert result == []


# ---------------------------------------------------------------------------
# _extract_key_value
# ---------------------------------------------------------------------------


def test_extract_key_value_basic():
    text = "**Name:** My Service"
    assert _extract_key_value(text, "Name:") == "My Service"


def test_extract_key_value_multiword():
    text = "**Purpose:** Acts as an API gateway for downstream services"
    assert _extract_key_value(text, "Purpose:") == "Acts as an API gateway for downstream services"


def test_extract_key_value_missing_key():
    assert _extract_key_value("no keys here", "Name:") == ""


def test_extract_key_value_stops_at_next_bold():
    text = "**Name:** First\n**Purpose:** Second"
    assert _extract_key_value(text, "Name:") == "First"


# ---------------------------------------------------------------------------
# _extract_subsections
# ---------------------------------------------------------------------------


def test_extract_subsections_basic():
    # _extract_subsections treats `- **Key:**` lines as subsection headers and
    # subsequent `- item` lines as values.  Inline values on the header line
    # (e.g. `- **Languages:** Python, Go`) are intentionally ignored by the
    # parser — only the follow-up bullet lines are collected.
    text = "**Technology Stack:**\n  - **Languages:**\n  - Python\n  - Go\n"
    result = _extract_subsections(text, "Technology Stack:")
    assert "Languages" in result
    assert result["Languages"] == ["Python", "Go"]


def test_extract_subsections_missing_header():
    result = _extract_subsections("no subsections", "Technology Stack:")
    assert result == {}


def test_extract_subsections_stops_at_top_level_header():
    text = "**Tech Stack:**\n  - **Languages:** Python\n**Next Section:**\n  - **Other:** stuff\n"
    result = _extract_subsections(text, "Tech Stack:")
    assert "Other" not in result


# ---------------------------------------------------------------------------
# parse_stride_component_description
# ---------------------------------------------------------------------------

STRIDE_COMPONENT_TEXT = """
<component_description>
**Name:** Payment Service
**Purpose:** Handles card transactions

**Technology Stack:**
  - **Backend:** Python, FastAPI

**Interfaces and Protocols:**
  - **Inbound:** REST over HTTPS

**Data Handled:**
  - **PII:** Card numbers

**Internal/External:** Internal
**Authentication / Authorization Used:** OAuth 2.0

**Dependencies:**
- Stripe API
- PostgreSQL
</component_description>
"""


def test_parse_stride_component_description_name():
    result = parse_stride_component_description(STRIDE_COMPONENT_TEXT)
    assert result is not None
    assert result.name == "Payment Service"


def test_parse_stride_component_description_purpose():
    result = parse_stride_component_description(STRIDE_COMPONENT_TEXT)
    assert result is not None
    assert result.purpose == "Handles card transactions"


def test_parse_stride_component_description_dependencies():
    result = parse_stride_component_description(STRIDE_COMPONENT_TEXT)
    assert result is not None
    assert "Stripe API" in result.dependencies
    assert "PostgreSQL" in result.dependencies


def test_parse_stride_component_description_missing_tag_returns_none():
    assert parse_stride_component_description("no tags here") is None


def test_parse_stride_component_description_empty_tag_returns_none():
    # _extract_xml_section("<component_description></component_description>") returns
    # "" (empty string after strip), then `if not content: return None` fires.
    result = parse_stride_component_description("<component_description></component_description>")
    assert result is None


# ---------------------------------------------------------------------------
# parse_maestro_component_description
# ---------------------------------------------------------------------------

MAESTRO_COMPONENT_TEXT = """
<maestro_component_description>
**Name:** Loan Approval Agent
**Operational Mission:** Approve or deny personal loan applications
**Autonomy Level:** Semi-autonomous
**Decision Authority:** Human-in-the-loop for amounts > $50k

**Agent / Model Profile:**
  - **Model Used:** GPT-4o
  - **Hosting:** Azure OpenAI

**Technology Stack:**
  - **Framework:** LangChain

**Assets:**
  - **Data:** Applicant PII

**Actors:**
  - **Human:** Loan officer

**Interfaces and Protocols:**
  - **Inbound:** REST API

**Trust Level:** Medium
**Agent Trust Chain:** Verified via internal PKI
**Human Override Mechanism:** Manual review portal
**Authentication / Authorization:** JWT

**Dependencies:**
- Credit bureau API
</maestro_component_description>
"""


def test_parse_maestro_component_description_name():
    result = parse_maestro_component_description(MAESTRO_COMPONENT_TEXT)
    assert result is not None
    assert result.name == "Loan Approval Agent"


def test_parse_maestro_component_description_mission_alignment():
    result = parse_maestro_component_description(MAESTRO_COMPONENT_TEXT)
    assert result is not None
    assert "Operational Mission" in result.mission_alignment


def test_parse_maestro_component_description_dependencies():
    result = parse_maestro_component_description(MAESTRO_COMPONENT_TEXT)
    assert result is not None
    assert "Credit bureau API" in result.dependencies


def test_parse_maestro_component_description_missing_tag_returns_none():
    assert parse_maestro_component_description("plain text") is None


# ---------------------------------------------------------------------------
# parse_stride_assumptions
# ---------------------------------------------------------------------------

STRIDE_ASSUMPTIONS_TEXT = """
<assumptions>
**Security Controls Already in Place:**
- TLS 1.3 on all endpoints
- WAF deployed

**Areas Considered In-Scope:**
- API authentication flow

**Areas Considered Out-of-Scope:**
- Physical security

**Known Constraints or Limitations:**
- No budget for HSM

**Development or Operational Considerations:**
- CI/CD pipeline enforces SAST

**Threat Modeling Focus Areas:**
- Authentication bypass
- Data exfiltration
</assumptions>
"""


def test_parse_stride_assumptions_security_controls():
    result = parse_stride_assumptions(STRIDE_ASSUMPTIONS_TEXT)
    assert result is not None
    assert "TLS 1.3 on all endpoints" in result.security_controls
    assert "WAF deployed" in result.security_controls


def test_parse_stride_assumptions_in_scope():
    result = parse_stride_assumptions(STRIDE_ASSUMPTIONS_TEXT)
    assert result is not None
    assert "API authentication flow" in result.in_scope


def test_parse_stride_assumptions_out_of_scope():
    result = parse_stride_assumptions(STRIDE_ASSUMPTIONS_TEXT)
    assert result is not None
    assert "Physical security" in result.out_of_scope


def test_parse_stride_assumptions_focus_areas():
    result = parse_stride_assumptions(STRIDE_ASSUMPTIONS_TEXT)
    assert result is not None
    assert "Authentication bypass" in result.focus_areas


def test_parse_stride_assumptions_missing_tag_returns_none():
    assert parse_stride_assumptions("no tags") is None


# ---------------------------------------------------------------------------
# parse_maestro_assumptions
# ---------------------------------------------------------------------------

MAESTRO_ASSUMPTIONS_TEXT = """
<maestro_assumptions>
**Mission Constraints:**
- Must comply with GDPR

**Security Controls Already in Place:**
- Input validation on all LLM prompts

**AI-Specific Controls in Place:**
- Prompt injection guard

**Areas Considered In-Scope:**
- Agent decision path

**Areas Considered Out-of-Scope:**
- Physical infrastructure

**Known Constraints or Limitations:**
- No adversarial training data

**Agentic / AI-Specific Considerations:**
- Tool call audit logging

**Development or Operational Considerations:**
- Blue-green deployments

**Threat Modeling Focus Areas:**
- Prompt injection
</maestro_assumptions>
"""


def test_parse_maestro_assumptions_mission_constraints():
    result = parse_maestro_assumptions(MAESTRO_ASSUMPTIONS_TEXT)
    assert result is not None
    assert "Must comply with GDPR" in result.mission_constraints


def test_parse_maestro_assumptions_ai_specific_controls():
    result = parse_maestro_assumptions(MAESTRO_ASSUMPTIONS_TEXT)
    assert result is not None
    assert "Prompt injection guard" in result.ai_specific_controls


def test_parse_maestro_assumptions_agentic_considerations():
    result = parse_maestro_assumptions(MAESTRO_ASSUMPTIONS_TEXT)
    assert result is not None
    assert "Tool call audit logging" in result.agentic_considerations


def test_parse_maestro_assumptions_focus_areas():
    result = parse_maestro_assumptions(MAESTRO_ASSUMPTIONS_TEXT)
    assert result is not None
    assert "Prompt injection" in result.focus_areas


def test_parse_maestro_assumptions_missing_tag_returns_none():
    assert parse_maestro_assumptions("no tags") is None


# ---------------------------------------------------------------------------
# detect_input_format
# ---------------------------------------------------------------------------


def test_detect_input_format_stride_opening_tag():
    assert (
        detect_input_format("<component_description>text</component_description>")
        == "stride_structured"
    )


def test_detect_input_format_stride_closing_tag_only():
    assert detect_input_format("blah </component_description>") == "stride_structured"


def test_detect_input_format_maestro_opening_tag():
    text = "<maestro_component_description>content</maestro_component_description>"
    assert detect_input_format(text) == "maestro_structured"


def test_detect_input_format_plain_text():
    assert detect_input_format("A web service that handles user authentication") == "plain"


def test_detect_input_format_empty_string():
    assert detect_input_format("") == "plain"


# ---------------------------------------------------------------------------
# format_structured_description_for_prompt
# ---------------------------------------------------------------------------


def test_format_stride_description_contains_name():
    result = parse_stride_component_description(STRIDE_COMPONENT_TEXT)
    assert result is not None
    formatted = format_structured_description_for_prompt(result)
    assert "Payment Service" in formatted


def test_format_stride_description_contains_purpose():
    result = parse_stride_component_description(STRIDE_COMPONENT_TEXT)
    assert result is not None
    formatted = format_structured_description_for_prompt(result)
    assert "Handles card transactions" in formatted


def test_format_stride_description_contains_dependencies_section():
    result = parse_stride_component_description(STRIDE_COMPONENT_TEXT)
    assert result is not None
    formatted = format_structured_description_for_prompt(result)
    assert "**Dependencies:**" in formatted


def test_format_maestro_description_contains_mission_alignment():
    result = parse_maestro_component_description(MAESTRO_COMPONENT_TEXT)
    assert result is not None
    formatted = format_structured_description_for_prompt(result)
    assert "Mission Alignment" in formatted


# ---------------------------------------------------------------------------
# format_structured_assumptions_for_prompt
# ---------------------------------------------------------------------------


def test_format_stride_assumptions_contains_security_controls_section():
    result = parse_stride_assumptions(STRIDE_ASSUMPTIONS_TEXT)
    assert result is not None
    formatted = format_structured_assumptions_for_prompt(result)
    assert "Security Controls Already in Place" in formatted


def test_format_stride_assumptions_contains_items():
    result = parse_stride_assumptions(STRIDE_ASSUMPTIONS_TEXT)
    assert result is not None
    formatted = format_structured_assumptions_for_prompt(result)
    assert "TLS 1.3 on all endpoints" in formatted


def test_format_maestro_assumptions_contains_mission_constraints():
    result = parse_maestro_assumptions(MAESTRO_ASSUMPTIONS_TEXT)
    assert result is not None
    formatted = format_structured_assumptions_for_prompt(result)
    assert "Mission Constraints" in formatted


def test_format_maestro_assumptions_contains_agentic_section():
    result = parse_maestro_assumptions(MAESTRO_ASSUMPTIONS_TEXT)
    assert result is not None
    formatted = format_structured_assumptions_for_prompt(result)
    assert "Agentic" in formatted


def test_format_assumptions_skips_empty_sections():
    """Sections with no items should not appear in the formatted output."""
    from backend.models.extended import StrideAssumptions

    empty_assumptions = StrideAssumptions(
        security_controls=["TLS"],
        in_scope=[],
        out_of_scope=[],
        constraints=[],
        operational_considerations=[],
        focus_areas=[],
    )
    formatted = format_structured_assumptions_for_prompt(empty_assumptions)
    assert "Security Controls" in formatted
    # Sections with no items should not produce headers
    assert "Areas Considered In-Scope" not in formatted
