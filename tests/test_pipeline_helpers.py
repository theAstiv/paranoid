"""Tests for context-enrichment helpers: extract_technologies, extract_controls.

Verifies extraction from representative descriptions and that the resulting
<detected_technologies> / <existing_controls> XML tags are injected into
the shared context produced by build_shared_context().
"""

from backend.models.enums import Framework
from backend.pipeline.nodes.helpers import (
    build_shared_context,
    extract_controls,
    extract_technologies,
)
from tests.fixtures.pipeline import make_assets, make_flows


# ---------------------------------------------------------------------------
# extract_technologies
# ---------------------------------------------------------------------------


class TestExtractTechnologies:
    def test_detects_common_tech_stack(self):
        desc = "A FastAPI backend using PostgreSQL and Redis, deployed on AWS with S3 for storage."
        result = extract_technologies(desc)
        assert "fastapi" in result
        assert "postgresql" in result or "postgres" in result
        assert "redis" in result
        assert "aws" in result
        assert "s3" in result

    def test_detects_auth_technologies(self):
        desc = "Users authenticate via OAuth2 and JWT tokens; we also support SSO via SAML."
        result = extract_technologies(desc)
        assert any(t in result for t in ("oauth", "jwt", "saml", "sso"))

    def test_detects_ml_keywords(self):
        desc = "An LLM inference service using RAG with a vector database and embedding model."
        result = extract_technologies(desc)
        assert any(t in result for t in ("llm", "rag", "vector", "embedding"))

    def test_empty_description_returns_empty(self):
        assert extract_technologies("") == []

    def test_no_relevant_keywords_returns_empty(self):
        assert extract_technologies("A simple to-do list application.") == []

    def test_max_items_caps_output(self):
        # Dense description that should produce many matches
        desc = (
            "FastAPI, PostgreSQL, Redis, AWS, S3, JWT, OAuth, Docker, Kubernetes, "
            "nginx, Kafka, Elasticsearch, MongoDB, SQLAlchemy, Prisma, GraphQL, "
            "gRPC, TLS, LDAP, SAML, OpenID, Terraform, Vault"
        )
        result = extract_technologies(desc, max_items=5)
        assert len(result) <= 5

    def test_returns_sorted_list(self):
        desc = "Uses PostgreSQL, JWT, and AWS Lambda."
        result = extract_technologies(desc)
        assert result == sorted(result)

    def test_case_insensitive(self):
        result_lower = extract_technologies("uses postgresql and jwt")
        result_upper = extract_technologies("uses PostgreSQL and JWT")
        assert set(result_lower) == set(result_upper)


# ---------------------------------------------------------------------------
# extract_controls
# ---------------------------------------------------------------------------


class TestExtractControls:
    def test_detects_rate_limiting(self):
        desc = "The API gateway enforces rate limiting on all endpoints."
        assert "rate limiting" in extract_controls(desc)

    def test_detects_mfa(self):
        desc = "All admin users must enable MFA before accessing the dashboard."
        assert "MFA" in extract_controls(desc)

    def test_detects_encryption_at_rest(self):
        desc = "Customer PII is stored with encryption at rest using AES-256."
        assert "encryption at rest" in extract_controls(desc)

    def test_detects_rbac(self):
        desc = "Access to resources is controlled via RBAC with predefined roles."
        assert "RBAC" in extract_controls(desc)

    def test_detects_audit_logging(self):
        desc = "All privileged actions are written to an immutable audit log."
        assert "audit logging" in extract_controls(desc)

    def test_detects_input_validation(self):
        desc = "All user input is sanitized before being passed to the database."
        assert "input validation" in extract_controls(desc)

    def test_detects_least_privilege(self):
        desc = "Service accounts operate under the least privilege principle."
        assert "least privilege" in extract_controls(desc)

    def test_detects_password_hashing(self):
        desc = "Passwords are stored using bcrypt with a work factor of 12."
        assert "password hashing" in extract_controls(desc)

    def test_empty_description_returns_empty(self):
        assert extract_controls("") == []

    def test_no_controls_in_plain_description(self):
        desc = "A web application that shows weather forecasts."
        assert extract_controls(desc) == []

    def test_max_items_caps_output(self):
        desc = (
            "MFA is required. Rate limiting applied. RBAC enforced. Input validation in place. "
            "Encryption at rest. Audit logging enabled. Least privilege principle. "
            "Password hashing with bcrypt. CSRF protection on all forms. "
            "CSP headers set. DDoS protection via CDN. Network segmentation applied. "
            "Zero trust architecture. CORS policy restricted. Secrets managed in Vault."
        )
        result = extract_controls(desc, max_items=5)
        assert len(result) <= 5

    def test_no_duplicates(self):
        desc = "Rate limiting and rate limiting again. Throttling is also applied."
        result = extract_controls(desc)
        assert result.count("rate limiting") == 1

    def test_two_factor_auth_matches_mfa(self):
        desc = "Two-factor authentication is mandatory."
        assert "MFA" in extract_controls(desc)

    def test_2fa_matches_mfa(self):
        desc = "Users must complete 2FA before logging in."
        assert "MFA" in extract_controls(desc)

    def test_throttling_matches_rate_limiting(self):
        desc = "API throttling is configured at 100 req/s."
        assert "rate limiting" in extract_controls(desc)


# ---------------------------------------------------------------------------
# build_shared_context tag injection
# ---------------------------------------------------------------------------


class TestBuildSharedContextEnrichment:
    """Verify the two new XML tags reach the assembled shared context string."""

    def _make_context(self, description: str) -> str:
        return build_shared_context(
            description=description,
            architecture_diagram=None,
            assumptions=None,
            assets=make_assets(),
            flows=make_flows(),
            code_summary=None,
            diagram_data=None,
            framework=Framework.STRIDE,
        )

    def test_detected_technologies_tag_present_when_techs_found(self):
        ctx = self._make_context("A FastAPI service with PostgreSQL and JWT auth.")
        assert "<detected_technologies>" in ctx
        assert "</detected_technologies>" in ctx

    def test_existing_controls_tag_present_when_controls_found(self):
        ctx = self._make_context("Rate limiting is enforced. Users require MFA.")
        assert "<existing_controls>" in ctx
        assert "</existing_controls>" in ctx

    def test_detected_technologies_contains_extracted_keywords(self):
        ctx = self._make_context("A FastAPI backend using PostgreSQL.")
        assert "fastapi" in ctx
        assert "postgresql" in ctx or "postgres" in ctx

    def test_existing_controls_contains_extracted_labels(self):
        ctx = self._make_context("Passwords are stored using bcrypt. RBAC is enforced.")
        assert "password hashing" in ctx
        assert "RBAC" in ctx

    def test_no_tech_tags_when_description_has_no_tech(self):
        ctx = self._make_context("A service that manages to-do items for teams.")
        assert "<detected_technologies>" not in ctx

    def test_no_controls_tag_when_description_has_no_controls(self):
        ctx = self._make_context("A web application for managing bookmarks.")
        assert "<existing_controls>" not in ctx

    def test_tags_appear_before_assets_section(self):
        ctx = self._make_context("FastAPI app with RBAC enforced.")
        tech_pos = ctx.find("<detected_technologies>")
        assets_pos = ctx.find("<identified_assets_and_entities>")
        # Tags may or may not be present; if both present, techs come first
        if tech_pos != -1 and assets_pos != -1:
            assert tech_pos < assets_pos

    def test_tags_appear_after_description_section(self):
        ctx = self._make_context("FastAPI app with RBAC enforced.")
        desc_pos = ctx.find("<description>")
        tech_pos = ctx.find("<detected_technologies>")
        if tech_pos != -1:
            assert desc_pos < tech_pos
