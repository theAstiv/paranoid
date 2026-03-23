"""BDD test case generation prompts for security testing.

This module provides prompts for generating Gherkin/BDD-style test cases
that validate security controls and threat mitigations.
"""


def test_case_prompt() -> str:
    """Generate prompt for BDD test case creation in Gherkin format."""
    return """
<task>
You are an expert in security testing and behavior-driven development (BDD). Your goal is to create comprehensive Gherkin-style test cases for a given security threat that validate the effectiveness of security controls and mitigations.
</task>

<instructions>

1. Review the threat information:
   * <threat_name>: The threat to be tested
   * <threat_description>: How the threat manifests
   * <target>: Asset or component under threat
   * <mitigations>: Security controls to validate

2. Gherkin Syntax:

   Feature: [Security control or mitigation being tested]

   Scenario: [Specific test scenario]
     Given [preconditions and context]
     When [action or attack attempt]
     Then [expected security outcome]
     And [additional verifications]

3. Test Case Categories (3-5 scenarios per threat):

   A. **Positive Security Tests**: Verify controls don't block valid usage
   B. **Negative Security Tests**: Verify mitigations prevent the threat
   C. **Detection Tests**: Verify logging captures attack indicators
   D. **Resilience Tests**: Verify system degrades gracefully under attack
   E. **Bypass Tests**: Test that evasion techniques still fail

4. Security Testing Specificity:

   **For STRIDE Threats:**
   - Spoofing: Test authentication controls
   - Tampering: Test integrity checks, input validation
   - Repudiation: Test audit logging
   - Information Disclosure: Test access controls
   - Denial of Service: Test rate limiting, resource quotas
   - Elevation of Privilege: Test authorization, least privilege

   **For ML/AI Threats:**
   - Model Security: Test access controls, rate limits
   - LLM Security: Test prompt filtering, output sanitization
   - Privacy: Test differential privacy, PII filtering

5. Include Concrete Examples:
   - Specific attack payloads
   - Expected HTTP status codes
   - Log entry formats
   - Error messages

6. Format Structure:

   Feature: [Mitigation Name]

     As a security tester
     I want to verify [control works]
     So that [threat is prevented/detected]

     Background:
       Given [common preconditions]

     Scenario: [Test name]
       Given [context]
       When [attack action]
       Then [security outcome]
       And [verification]

7. Scenario Naming:
   Use descriptive names indicating what is tested and expected outcome.

   Good examples:
   - "SQL injection blocked by parameterized queries"
   - "Rate limiting prevents brute force"
   - "Unauthorized access logged and rejected"

8. ML/AI-Specific Test Examples:

   Scenario: Model extraction prevented by rate limiting
     Given ML model API with 100 queries/minute limit
     When attacker submits 1000 queries in 1 minute
     Then requests throttled after 100 queries
     And 429 status returned
     And security event logged

   Scenario: Prompt injection filtered
     Given LLM with prompt filtering enabled
     When user submits "Ignore previous instructions"
     Then prompt is sanitized
     And safe response generated
     And injection attempt logged

9. Output Format:
   Provide complete Gherkin feature file with 3-5 scenarios, concrete assertions, and clear Given-When-Then structure.

10. Quality Checklist:
    * [ ] Each scenario tests specific mitigation
    * [ ] Scenarios are independent
    * [ ] Gherkin syntax is valid
    * [ ] Assertions are specific and measurable
    * [ ] Both positive and negative cases covered
    * [ ] Attack payloads are realistic

</instructions>
"""
