"""Prompt for code summarization node.

Produces a structured CodeSummary from raw CodeContext for downstream pipeline steps.
"""


def code_summary_prompt() -> str:
    """Generate prompt for summarize_code() pipeline node.

    Returns:
        Prompt instructing LLM to produce security-focused code summary
    """
    return """<instruction>
You are a security engineer reviewing source code for threat modeling. Analyze the provided code context and produce a structured security summary.

Review the code in <code_context> and extract the following:

1. **Technology Stack**: Languages, frameworks, libraries, and infrastructure (e.g., "Python/FastAPI", "PostgreSQL", "Redis", "Docker")

2. **Entry Points**: HTTP routes, API endpoints, CLI commands, message queue consumers, scheduled tasks. Format as "METHOD /path" for HTTP or descriptive name for others.

3. **Authentication & Authorization Patterns**: How the system authenticates users and enforces access control. Look for JWT, OAuth, session tokens, API keys, RBAC, middleware guards. Note both what IS implemented and what appears MISSING.

4. **Data Stores**: Databases, caches, file storage, message queues. Include what data they hold if visible (e.g., "PostgreSQL - users table with password hashes").

5. **External Dependencies**: Third-party APIs, services, SDKs the code calls. Note how credentials are managed (env vars, config files, hardcoded).

6. **Security Observations**: Specific findings from the code that are relevant to threat modeling:
   - Positive: parameterized SQL queries, input validation, rate limiting, encryption at rest
   - Negative: hardcoded secrets, SQL string concatenation, missing auth on endpoints, pickle deserialization of untrusted data, eval() usage, disabled CSRF protection
   - Neutral: notable architectural patterns that affect attack surface

7. **Raw Summary**: A 150-200 word free-text summary of the codebase's security posture, suitable for inclusion in a threat model document.

Output your analysis as a structured JSON object matching the CodeSummary schema.
</instruction>"""
