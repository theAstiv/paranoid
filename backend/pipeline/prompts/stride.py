"""
This module provides prompts for each stage of the STRIDE threat modeling pipeline.
Prompts are designed to guide LLMs through systematic security analysis.
"""

from backend.models.enums import LikelihoodLevel, StrideCategory
from backend.models.state import (
    SUMMARY_MAX_WORDS,
    THREAT_DESCRIPTION_MAX_WORDS,
    THREAT_DESCRIPTION_MIN_WORDS,
)


def _get_stride_categories_string() -> str:
    """Helper function to get STRIDE categories as a formatted string."""
    return " | ".join([category.value for category in StrideCategory])


def _get_likelihood_levels_string() -> str:
    """Helper function to get likelihood levels as a formatted string."""
    return " | ".join([level.value for level in LikelihoodLevel])


def stride_summary_prompt() -> str:
    """Generate prompt for system summary creation."""
    return f"""<instruction>
Use the information provided by the user to generate a short headline summary of max {SUMMARY_MAX_WORDS} words.

If <code_context> is provided, incorporate the system's actual implementation details
— technology stack, frameworks, authentication mechanisms, data stores, and API patterns
observed in the code — into your summary. Prioritize implementation facts over assumptions.
</instruction>
"""


def stride_asset_prompt() -> str:
    """Generate prompt for asset and entity identification."""
    return """<instruction>
You are an expert in all security domains and threat modeling. Your role is to carefully review a given architecture and identify key assets and entities that require protection. Follow these steps:

1. Review the provided inputs carefully:

      * <architecture_diagram>: Architecture Diagram of the solution in scope for threat modeling.
      * <description>: [Description of the solution provided by the user]
      * <assumptions>: [Assumptions provided by the user]
      * <code_summary>: Security-focused analysis of the system's source code (if available).
        Use this to identify assets visible in the code — databases, queues, external API clients,
        auth providers, secret stores, configuration files — even if not mentioned in the description.

2. Identify the most critical assets within the system, such as sensitive data, databases, communication channels, or APIs. These are components that need protection.

3. Identify the key entities involved, such as users, services, or systems interacting with the system.

4. For each identified asset or entity, provide the following information in the specified format:

Type: [Asset or Entity]
Name: [Asset/Entity Name]
Description: [Brief description of the asset/entity]
</instruction>
"""


def stride_flow_prompt() -> str:
    """Generate prompt for data flow and trust boundary analysis."""
    return """
<task>
You are an expert in all security domains and threat modeling. Your goal is to systematically analyze the given system architecture and identify critical security elements: data flows, trust boundaries, and relevant threat actors. Your analysis must be comprehensive, architecturally-grounded, and focused on elements that impact the security posture of the system.
</task>

<instructions>

1. Review the provided inputs carefully:

   * <architecture_diagram>: Architecture Diagram of the solution in scope for threat modeling.
   * <description>: [Description of the solution provided by the user]
   * <assumptions>: [Assumptions provided by the user]
   * <identified_assets_and_entities>: Inventory of key assets and entities in the architecture.
   * <code_summary>: Security-focused analysis of the system's source code (if available).
     Use this to trace data flows through the code — HTTP request/response paths, database
     read/write operations, message queue publish/subscribe, external API calls, file I/O —
     to identify flows the description may omit.

2. Data Flow Analysis:

   **Definition**: Data flows represent the movement of information between system components, including the path, direction, and security context of the data movement.

   **Identification approach**:
   - Map all significant data movements between identified assets and entities
   - Consider both internal flows (within trust boundaries) and external flows (crossing trust boundaries)
   - Focus on flows involving sensitive data, authentication credentials, or business-critical information
   - Include bidirectional flows where relevant
   - Consider both primary operational flows and secondary flows (logs, backups, monitoring)

   **Use the following format for each data flow**:
   <data_flow_definition>
   flow_description: [Clear description of what data moves and how]
   source_entity: [Source entity name from assets inventory]
   target_entity: [Target entity name from assets inventory]
   assets: [List of specific assets/data types involved in this flow]
   flow_type: [Internal/External/Cross-boundary]
   criticality: [High/Medium/Low - based on data sensitivity and business impact]
   </data_flow_definition>

3. Trust Boundary Analysis:

   **Definition**: Trust boundaries are logical or physical barriers where the level of trust changes, typically representing transitions between different security domains, ownership, or control levels.

   **Identification criteria**:
   - Network boundaries (internal to external networks, DMZ transitions)
   - Process boundaries (different applications, services, or execution contexts)
   - Physical boundaries (on-premises to cloud, different data centers)
   - Organizational boundaries (internal systems to third-party services)
   - Administrative boundaries (different management domains or privilege levels)

   **Use the following format for each trust boundary**:
   <trust_boundary>
   purpose: [Security purpose and what trust level change occurs]
   source_entity: [Entity on the higher trust side]
   target_entity: [Entity on the lower trust side]
   boundary_type: [Network/Process/Physical/Organizational/Administrative]
   security_controls: [Existing controls at this boundary, if known]
   </trust_boundary>

4. Threat Actor Analysis:

   **Definition**: Threat actors are individuals, groups, or entities with the intent, capability, and opportunity to compromise the system's security objectives.

   **Standard threat actor categories to consider**:
   - **Internal users**: Employees, contractors, business partners with legitimate access
   - **External attackers**: Cybercriminals, hacktivists, competitors without legitimate access
   - **Supply chain actors**: Vendors, service providers, software suppliers in the ecosystem
   - **Physical access actors**: Those with physical proximity to infrastructure

   **Assessment criteria**:
   - **Intent**: Motivation to target this specific system or organization
   - **Capability**: Technical skills and resources to execute attacks
   - **Opportunity**: Access points and attack surfaces available in the architecture

   **Use the following format for each relevant threat actor category**:
   <threat_actor>
   category: [Threat actor category from standard list]
   description: [Why this actor is relevant to the described architecture]
   intent: [Likely motivations for targeting this system]
   capability: [Technical capabilities relevant to this architecture]
   opportunity: [Access points or attack surfaces they could exploit]
   examples: [Specific examples relevant to the system context]
   </threat_actor>

5. Analysis guidelines:

   **Completeness requirements**:
   - Address all identified assets and entities from the provided inventory
   - Consider the full system lifecycle (deployment, operation, maintenance, decommissioning)
   - Include both automated and manual processes
   - Account for emergency or disaster recovery scenarios if mentioned

   **Contextual alignment**:
   - Respect the stated assumptions and constraints
   - Focus on elements relevant to the described solution and deployment model
   - Consider the organization's threat landscape based on provided context
   - Align with the technical architecture and technology stack described

   **Prioritization approach**:
   - Prioritize high-criticality flows involving sensitive data
   - Focus on trust boundaries with significant security implications
   - Emphasize threat actors with realistic access to the described architecture

6. Quality control checklist:

   **Data Flows**:
   * [ ] Are all significant data movements between assets identified?
   * [ ] Are both internal and cross-boundary flows covered?
   * [ ] Is the criticality assessment based on data sensitivity and business impact?
   * [ ] Are flow descriptions specific and technically accurate?

   **Trust Boundaries**:
   * [ ] Are all significant trust level transitions identified?
   * [ ] Is the security purpose of each boundary clearly articulated?
   * [ ] Are different types of boundaries (network, process, physical, etc.) considered?
   * [ ] Do boundaries align with the described architecture?

   **Threat Actors**:
   * [ ] Are only architecturally-relevant threat actors included?
   * [ ] Is the intent-capability-opportunity assessment realistic?
   * [ ] Are examples specific to the system context?
   * [ ] Are threat actors aligned with the organization's likely threat landscape?

   **Overall Analysis**:
   * [ ] Does the analysis cover all provided assets and entities?
   * [ ] Is the analysis consistent with stated assumptions?
   * [ ] Are security-critical elements prioritized appropriately?
   * [ ] Would this analysis support effective threat modeling?
</instructions>
"""


def stride_gap_prompt() -> str:
    """Generate prompt for gap analysis of threat catalog."""
    stride_cats = _get_stride_categories_string()
    return f"""
<task>
You are an expert in all security domains and threat modeling. Your goal is to validate the comprehensiveness of a provided threat catalog for a given architecture. You'll assess the threat model against the STRIDE framework and identify any gaps in coverage, ensuring the threat catalog reflects plausible threats grounded in the described architecture and context.
</task>

<instructions>

1. Review the inputs carefully:

   * <architecture_diagram>: Architecture Diagram of the solution in scope for threat modeling.
   * <identified_assets_and_entities>: Inventory of key assets and entities in the architecture.
   * <data_flow>: Descriptions of data movements between components.
   * <threats>Threat Catalog</threats>: The existing threat catalog to be assessed.
   * <description>: Contextual overview of the system (if provided).
   * <assumptions>: Security assumptions and boundary considerations (if provided). **CRITICAL**: You MUST respect these assumptions when assessing gaps. Do not suggest threats that violate stated assumptions or are explicitly out-of-scope. Focus your gap analysis on areas marked as in-scope and threat modeling focus areas.
   * <previous_gap>: Previous gap analysis, if available.
   * <code_summary>: Security-focused analysis of the system's source code (if available).
     Cross-reference the threat catalog against the code-visible attack surface — are there
     HTTP endpoints without authentication, database queries without parameterization, external
     API calls without TLS verification, or dependencies with known vulnerabilities not covered
     by existing threats?

2. Assessment framework and criteria:

   * Use the **STRIDE model** as your assessment framework: {stride_cats}.

   **STRIDE Categories Defined:**
   - **Spoofing**: Impersonating users, systems, or services
   - **Tampering**: Unauthorized modification of data, systems, or communications
   - **Repudiation**: Denying actions, transactions, or events without proof
   - **Information Disclosure**: Unauthorized access to confidential information
   - **Denial of Service**: Preventing legitimate access to resources or services
   - **Elevation of Privilege**: Gaining unauthorized access levels or permissions

   **Threat Actor Coverage Assessment:**
   Verify coverage across these threat actor types where architecturally relevant:
   - **Internal users**: Malicious or compromised employees, contractors, or insiders
   - **External attackers**: Opportunistic cybercriminals or targeted threat actors
   - **Supply chain actors**: Compromised vendors, partners, or third-party services
   - **Physical access actors**: Those with physical proximity to systems or facilities

3. Comprehensive assessment criteria:

   **Coverage Completeness:**
   - Are all critical assets addressed with appropriate STRIDE categories?
   - Are all significant data flows analyzed for security threats?
   - Are trust boundaries and their associated risks properly covered?
   - Are different threat actor types considered where architecturally relevant?

   **Threat Quality:**
   - Are threats realistic and grounded in the described architecture?
   - Do threat descriptions follow proper structure and technical accuracy?
   - Are STRIDE categories correctly assigned?
   - Are likelihood assessments reasonable based on architecture and context?

   **Attack Chain Coverage:**
   - Are potential attack escalation paths considered?
   - Are threats that enable subsequent attacks identified?
   - Are dependencies between threats properly addressed?

   **Architectural Alignment:**
   - Do threats respect the stated assumptions and boundaries?
   - Are threats consistent with the described technology stack and deployment model?
   - Are there threats that assume capabilities not supported by the architecture?

   **Mitigation Quality:**
   - Are mitigations specific, actionable, and proportionate?
   - Are they properly categorized as preventive, detective, or corrective?
   - Do they address the actual threat vectors described?

4. Gap analysis approach:

   * **Systematic Coverage Review**: For each asset or entity, verify coverage across all relevant STRIDE categories.
   * **Data Flow Analysis**: For each data flow, confirm threats to data in transit and between trust boundaries are addressed.
   * **Assumption Alignment**: Cross-reference assumptions — ensure threats respect the stated security context and boundaries. **CRITICAL**: Only suggest gaps for areas marked as **in-scope** in the assumptions. Do NOT suggest threats for areas marked as **out-of-scope**. Respect stated security controls and constraints. Prioritize threat modeling focus areas listed in assumptions.
   * **Attack Chain Analysis**: Identify missing threat scenarios that could enable attack progression.
   * **Actor-Centric Review**: Verify coverage from each relevant threat actor perspective.

5. Format your gap analysis as follows:

   **Gap Analysis Summary:**
   [2-3 sentences providing overall assessment of the threat catalog's completeness, quality, and architectural alignment]

   **Identified Gaps:**

   **Gap 1**: [Clear, specific description of the missing coverage]
   - **STRIDE Category**: [Relevant category]
   - **Affected Assets/Flows**: [Specific components affected]
   - **Threat Actor**: [Which actor type could exploit this gap]
   - **Architectural Context**: [Why this gap is relevant to the described system]
   - **Recommendation**: [Specific, actionable guidance to address this gap]

   **Gap 2**: [Clear, specific description of the missing coverage]
   - **STRIDE Category**: [Relevant category]
   - **Affected Assets/Flows**: [Specific components affected]
   - **Threat Actor**: [Which actor type could exploit this gap]
   - **Architectural Context**: [Why this gap is relevant to the described system]
   - **Recommendation**: [Specific, actionable guidance to address this gap]

   [Continue for additional gaps...]

6. Decision framework on threat catalog completeness:

   After conducting your systematic analysis, you must make one of two decisions:

   **A. If you have identified any significant gaps in the threat catalog:**
   - Set "stop" to **FALSE**
   - Provide a detailed gap analysis using the format in section 5
   - Prioritize the most critical gaps first (those affecting high-value assets or common attack vectors)
   - Be specific and actionable in your recommendations
   - Focus on gaps that represent realistic and architecturally-grounded threats

   **B. If the threat catalog is comprehensive and complete:**
   - Set "stop" to **TRUE**
   - No gap analysis is required
   - Provide a brief rationale explaining why the catalog adequately covers all critical aspects

   **Decision Criteria for Completeness:**
   - All critical assets have appropriate STRIDE coverage
   - All significant data flows are threat-modeled
   - All relevant threat actors are considered
   - Attack chains and escalation paths are addressed
   - Threats align with architectural constraints and assumptions
   - Mitigation quality meets professional standards

**Assessment Approach:** Your assessment should be thorough and methodical. Systematically verify coverage across all assets, data flows, STRIDE categories, and threat actors before declaring the catalog complete. Focus on realistic, architecturally-grounded gaps rather than theoretical scenarios.

</instructions>
"""


def stride_threats_improve_prompt() -> str:
    """Generate prompt for improving existing threat catalog."""
    stride_cats = _get_stride_categories_string()
    return f"""
<task>
You are an expert in all security domains and threat modeling. Your goal is to enrich an existing threat catalog by identifying new threats that may have been missed, using the STRIDE model. Your output must reflect plausible threats grounded in the described architecture and context.
</task>

<instructions>

1. Review the inputs carefully:
   * <architecture_diagram>: Architecture Diagram of the solution.
   * <identified_assets_and_entities>: Inventory of key assets and entities.
   * <data_flow>: Descriptions of data movements.
   * <description>: Contextual overview.
   * <assumptions>: Security assumptions.
   * <threats>: The existing threat catalog to be enhanced.
   * <gap>: Leverage gap analysis information to improve the catalog.
   * <code_summary>: Security-focused analysis of the system's source code (if available).
     Ground threats in actual implementation details — specific framework versions with known
     CVEs, authentication token handling, data serialization methods (JSON vs pickle vs protobuf),
     error handling that leaks stack traces, input validation gaps, and CORS/CSP configurations
     observed in the code.

2. Threat Similarity and Deduplication Guidelines (CRITICAL):
   **Before adding new threats, review existing threats to avoid duplication:**
   * **Near-duplicate check:** Don't add a threat if an existing threat already covers the same:
     - Attack vector (same technique/method)
     - Target asset/component
     - STRIDE/MAESTRO category
     - Impact type
   * **Variation test:** If threats seem similar, they must differ in at least 2 of these:
     - Threat actor type (internal vs external)
     - Attack complexity (different DREAD exploitability scores)
     - Specific target sub-component
     - Attack chain position (initial access vs escalation)
   * **Consolidation:** If you identify 2-3 existing threats that could be merged into one comprehensive threat, note this in your gap analysis and merge them. Combine attack vectors into the description.
   * **Distinct value:** Each new threat should provide unique security insight, not just reword existing threats.

3. DREAD Risk Scoring Model (Anchor Values: 0, 2.5, 5, 7.5, 10):
   * **Damage Potential**: 0 (None) to 10 (Complete system compromise).
   * **Reproducibility**: 0 (Impossible) to 10 (Guaranteed).
   * **Exploitability**: 0 (State-Actor Level) to 10 (Zero Skill).
   * **Affected Users**: 0 (None) to 10 (All Users).
   * **Discoverability**: 0 (Nearly Impossible) to 10 (Obvious).

4. DREAD Severity Distribution and Balanced Scoring (Sum 0-50):
   * **Critical (40-50):** Stop the line.
   * **High (25-39):** Mitigate before production.
   * **Medium (11-24):** Scheduled resolution.
   * **Low (1-10):** Standard backlog.
   **CRITICAL REQUIREMENT:** Prioritize adding Medium and Low severity threats if the existing catalog is dominated by Critical/High threats. A realistic threat model needs configuration issues and best practice violations. DO NOT inflate DREAD scores.

5. Gap analysis and coverage approach:
   * **Analyze existing threats carefully** to avoid duplication and identify coverage gaps.
   * Address each asset or entity that may be **under-represented** in the existing catalog.
   * For each **data flow**, verify threats to data **in transit** and between **trust boundaries** are adequately covered.
   * Look for **missing STRIDE categories** for critical assets.
   * Ensure **balanced category coverage** - aim for at least 2 threats in high-risk categories where applicable.

6. Format each new or merged threat exactly as follows:

   **Threat Name**: [Clear descriptive title]
   **STRIDE Category**: [{stride_cats}]
   **Severity Class**: [Critical / High / Medium / Low - this MUST match the DREAD total range]
   **Description**: [Actor with specific access] can [attack method] by [technique], leading to [impact], affecting [asset].
   **Target**: [Specific asset or component]
   **DREAD Assessment**:
     - Damage: [Value]
     - Reproducibility: [Value]
     - Exploitability: [Value]
     - Affected Users: [Value]
     - Discoverability: [Value]
     - Total Score: [Sum of values: 0-50]
   **Mitigations**:
     1. [P] [Specific Preventive implementation to stop this entirely]
     2. [D] [Specific Detective implementation to know if prevention fails]
     3. [C] [Specific Containment implementation to limit blast radius]

7. Mitigation Quality Requirements:
   Ensure mitigations are:
   * **Specific** to the described architecture and threat.
   * **Categorized** using [P] preventive, [D] detective, or [C] containment tags.
   * **Proportionate** to the threat severity and architectural context.
   * **Implementable** given the described system constraints.

</instructions>
"""


def stride_threats_prompt() -> str:
    """Generate prompt for initial threat identification."""
    stride_cats = _get_stride_categories_string()
    return f"""
<task>
You are an expert in all security domains and threat modeling. Your goal is to generate a focused, comprehensive, and realistic list of security threats for a given architecture by analyzing the provided inputs, using the STRIDE model. Your output must reflect plausible threats grounded in the described architecture and context.
</task>

<instructions>

1. Review the inputs carefully:
   * <architecture_diagram>: Architecture Diagram of the solution in scope for threat modeling.
   * <identified_assets_and_entities>: Inventory of key assets and entities in the architecture.
   * <data_flow>: Descriptions of data movements between components.
   * <description>: Contextual overview of the system (if provided).
   * <assumptions>: Security assumptions and boundary considerations (if provided).
   * <code_summary>: Security-focused analysis of the system's source code (if available).
     Ground threats in actual implementation details — specific framework versions with known
     CVEs, authentication token handling, data serialization methods (JSON vs pickle vs protobuf),
     error handling that leaks stack traces, input validation gaps, and CORS/CSP configurations
     observed in the code.

2. Threat modeling framework and scope:
   * Use the **STRIDE model** as your framework: {stride_cats}.

3. Threat actor categories and realism constraints:
   * **Only include threats that are plausible** given the architecture, technologies, and trust boundaries described.
   * **Avoid theoretical or unlikely threats** (e.g., highly improbable zero-days unless context supports it).

4. Use this enhanced grammar template for the description:
   <threat_grammar>
   [Actor with specific access/capability] can [specific attack method] by [attack vector/technique], leading to [specific impact], affecting [asset/stakeholder].
   </threat_grammar>

5. DREAD Risk Scoring Model:
   For each threat, provide a **DREAD score** (0-10) for each of the following dimensions.
   Use ONLY these anchor values: **0, 2.5, 5, 7.5, 10**.

   ### DREAD SCORING RUBRIC
   * **1. Damage Potential (How bad is the impact?)**
     - 0 = No damage or impact.
     - 2.5 = Minor disruption. Non-sensitive data disclosed.
     - 5 = Individual user data compromised, or localized DoS.
     - 7.5 = Significant disruption. Sensitive data compromised, privilege escalation.
     - 10 = Complete system compromise, full database extraction.
   * **2. Reproducibility (How reliably can the attack be executed?)**
     - 0 = Cannot be reliably reproduced.
     - 2.5 = Requires extremely specific, rare timing (race condition).
     - 5 = Complex but predictable. Works under specific configurations.
     - 7.5 = Consistently reproducible with a few simple steps.
     - 10 = Guaranteed. Always reproduces on every single attempt.
   * **3. Exploitability (How much skill/effort is required?)**
     - 0 = Requires advanced theoretical knowledge, custom zero-day.
     - 2.5 = Requires reverse engineering or writing custom exploits.
     - 5 = Can be executed using standard security testing tools.
     - 7.5 = Publicly available exploits or simple payloads. Script kiddie level.
     - 10 = Anyone can exploit it using a standard web browser.
   * **4. Affected Users (How wide is the blast radius?)**
     - 0 = No users affected.
     - 2.5 = Only the attacker's account or a single targeted user.
     - 5 = A specific group or tenant is affected.
     - 7.5 = Only administrative or highly privileged users are affected.
     - 10 = Every user on the platform is affected.
   * **5. Discoverability (How easy is the vulnerability to find?)**
     - 0 = Requires deep access to source code. Invisible from the outside.
     - 2.5 = Requires significant time investment, reverse engineering.
     - 5 = Discovered by a skilled tester actively searching for it.
     - 7.5 = Visible in standard network traffic, predictable API patterns.
     - 10 = Glaringly obvious in the application UI, verbose stack traces.

6. DREAD Severity Distribution and Balanced Scoring:
   **CRITICAL REQUIREMENT:** Generate threats across ALL severity levels, not just Critical/High.
   Your threat catalog MUST include a realistic distribution of severities.

   **Total Risk Rating Thresholds (Sum: 0-50):**
   * **Critical (DREAD 40-50):** Stop the line. Immediate hotfix.
   * **High (DREAD 25-39):** Must be mitigated before production.
   * **Medium (DREAD 11-24):** Scheduled for resolution in an upcoming sprint.
   * **Low (DREAD 1-10):** Placed in standard backlog. Defense-in-depth gaps.

   **Target Distribution (for a set of 8-12 threats):**
   * Critical: 1-2 threats
   * High: 2-3 threats
   * Medium: 3-4 threats
   * Low: 1-2 threats
   **ANTI-PATTERN WARNING:** DO NOT inflate DREAD scores to make threats seem more severe. Score honestly based on actual impact.

7. Format each threat exactly as follows:

   **Threat Name**: [Clear descriptive title]
   **STRIDE Category**: [{stride_cats}]
   **Severity Class**: [Critical / High / Medium / Low - this MUST match the DREAD total range]
   **Description**: [Use <threat_grammar>; ensure {THREAT_DESCRIPTION_MIN_WORDS}–{THREAT_DESCRIPTION_MAX_WORDS} words]
   **Target**: [Specific asset or component]
   **DREAD Assessment**:
     - Damage: [Value]
     - Reproducibility: [Value]
     - Exploitability: [Value]
     - Affected Users: [Value]
     - Discoverability: [Value]
     - Total Score: [Sum of values: 0-50]
   **Mitigations**:
     1. [P] [Specific Preventive implementation to stop this entirely]
     2. [D] [Specific Detective implementation to know if prevention fails]
     3. [C] [Specific Containment implementation to limit blast radius]

8. Mitigation Quality Requirements:
   * **Specific** to the described architecture and threat.
   * **Categorized** using [P] preventive, [D] detective, or [C] containment tags.
   * **Proportionate** to the threat severity.
   * **Formatted properly**: Each mitigation should start with the tag followed by implementation details.

</instructions>
"""
