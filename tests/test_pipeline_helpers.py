"""Tests for context-enrichment helpers: extract_technologies, extract_controls.

Verifies extraction from representative descriptions and that the resulting
<detected_technologies> / <existing_controls> XML tags are injected into
the shared context produced by build_shared_context().
"""

from backend.models.dependencies import (
    CapabilityEvidence,
    CapabilityProfile,
    DependencyContext,
    PackageAnalysis,
    PackageRef,
    ResolvedPackage,
)
from backend.models.enums import CapabilityCategory, DiagramFormat, Framework, PathClass, SourceKind
from backend.models.extended import DiagramData
from backend.pipeline.nodes.helpers import (
    build_diagram_parts,
    build_shared_context,
    extract_controls,
    extract_technologies,
    format_dependency_context,
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
            diagrams=None,
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


# ---------------------------------------------------------------------------
# format_dependency_context / <dependency_capabilities> tag injection
# ---------------------------------------------------------------------------


def _notable_package(name="evil-pkg", version="1.0.0") -> PackageAnalysis:
    profile = CapabilityProfile(
        name=name,
        version=version,
        source_kind=SourceKind.NPM_TARBALL,
        evidence=[
            CapabilityEvidence(
                category=CapabilityCategory.DYNAMIC_CODE,
                rule_id="r",
                file="index.js",
                line=1,
                snippet="eval(x)",
                source_kind=SourceKind.NPM_TARBALL,
                path_class=PathClass.SHIPPED,
            )
        ],
        capability_vector=[CapabilityCategory.DYNAMIC_CODE],
        status="ok",
    )
    return PackageAnalysis(
        ref=PackageRef(name=name, version=version),
        resolved=ResolvedPackage(
            name=name, version=version, tarball_url="https://x", integrity="sha512-x"
        ),
        npm_profile=profile,
    )


def _unremarkable_package(name="lodash", version="4.17.21") -> PackageAnalysis:
    profile = CapabilityProfile(
        name=name, version=version, source_kind=SourceKind.NPM_TARBALL, status="ok"
    )
    return PackageAnalysis(
        ref=PackageRef(name=name, version=version),
        resolved=ResolvedPackage(
            name=name, version=version, tarball_url="https://x", integrity="sha512-x"
        ),
        npm_profile=profile,
    )


class TestFormatDependencyContext:
    def test_empty_context_returns_empty_string(self):
        assert format_dependency_context(DependencyContext(packages=[])) == ""

    def test_notable_package_listed_with_its_capabilities(self):
        ctx = DependencyContext(packages=[_notable_package()])
        text = format_dependency_context(ctx)
        assert "evil-pkg@1.0.0" in text
        assert "dynamic_code" in text

    def test_unremarkable_packages_collapse_to_count_line(self):
        ctx = DependencyContext(packages=[_unremarkable_package(), _unremarkable_package("chalk")])
        text = format_dependency_context(ctx)
        assert "lodash" not in text
        assert "2 other direct dependencies scanned" in text

    def test_skipped_packages_reported(self):
        ctx = DependencyContext(
            packages=[_notable_package()], skipped={"weird-pkg": "unresolvable_version_range"}
        )
        text = format_dependency_context(ctx)
        assert "1 dependency not analyzed" in text


class TestBuildSharedContextDependencyTag:
    def test_dependency_capabilities_tag_present_with_notable_findings(self):
        ctx = build_shared_context(
            description="A service",
            architecture_diagram=None,
            assumptions=None,
            assets=make_assets(),
            flows=make_flows(),
            code_summary=None,
            diagrams=None,
            framework=Framework.STRIDE,
            dependency_context=DependencyContext(packages=[_notable_package()]),
        )
        assert "<dependency_capabilities>" in ctx
        assert "evil-pkg@1.0.0" in ctx

    def test_no_dependency_tag_when_context_is_none(self):
        ctx = build_shared_context(
            description="A service",
            architecture_diagram=None,
            assumptions=None,
            assets=make_assets(),
            flows=make_flows(),
            code_summary=None,
            diagrams=None,
            framework=Framework.STRIDE,
        )
        assert "<dependency_capabilities>" not in ctx

    def test_no_dependency_tag_when_context_has_no_notable_packages(self):
        ctx = build_shared_context(
            description="A service",
            architecture_diagram=None,
            assumptions=None,
            assets=make_assets(),
            flows=make_flows(),
            code_summary=None,
            diagrams=None,
            framework=Framework.STRIDE,
            dependency_context=DependencyContext(packages=[]),
        )
        assert "<dependency_capabilities>" not in ctx


# ---------------------------------------------------------------------------
# build_diagram_parts (5a-1)
# ---------------------------------------------------------------------------


def _mermaid(name: str) -> DiagramData:
    return DiagramData(
        format=DiagramFormat.MERMAID,
        source_path=f"{name}.mmd",
        mermaid_source="graph TD\n  A-->B",
        name=name,
    )


def _image(name: str) -> DiagramData:
    return DiagramData(
        format=DiagramFormat.PNG,
        source_path=f"{name}.png",
        base64_data="aGVsbG8=",
        media_type="image/png",
        name=name,
    )


class TestBuildDiagramParts:
    def test_empty_returns_empty(self):
        text, images = build_diagram_parts(None)
        assert text == ""
        assert images == []

    def test_mixed_types_order_indices_and_image_count(self):
        diagrams = [_mermaid("flow"), _image("arch1"), _image("arch2")]
        text, images = build_diagram_parts(diagrams, with_images=True)

        # Order and diagram-level index/of reflect position among ALL diagrams.
        assert text.index('name="flow"') < text.index('name="arch1"')
        assert text.index('name="arch1"') < text.index('name="arch2"')
        assert 'index="1" of="3"' in text
        assert 'index="2" of="3"' in text
        assert 'index="3" of="3"' in text

        # Mermaid source is inlined; images get a vision placeholder.
        assert "graph TD" in text
        assert "[Provided as vision image 1 of 2]" in text
        assert "[Provided as vision image 2 of 2]" in text

        # Only the 2 image diagrams produce ImageContent entries, in order.
        assert len(images) == 2
        assert images[0].source == "arch1"
        assert images[1].source == "arch2"

    def test_with_images_false_uses_unsupported_placeholder_and_no_images(self):
        diagrams = [_mermaid("flow"), _image("arch")]
        text, images = build_diagram_parts(diagrams, with_images=False)

        assert "graph TD" in text
        assert "[image not sent: provider does not support images]" in text
        assert "[Provided as vision image" not in text
        assert images == []

    def test_single_diagram_name_attribute_escaped(self):
        d = _mermaid("a")
        d.name = 'a"b<c>d&e'  # bypass sanitization to test the XML escaper directly
        text, _ = build_diagram_parts([d])
        assert "<c>" not in text
        assert "&quot;" in text or "&lt;" in text


def test_build_shared_context_with_two_mermaid_diagrams():
    """build_shared_context inlines both Mermaid diagrams' source, each in
    its own named/indexed <architecture_diagram> block."""
    diagrams = [_mermaid("flow"), _mermaid("deployment")]
    ctx = build_shared_context(
        description="A service",
        architecture_diagram=None,
        assumptions=None,
        assets=make_assets(),
        flows=make_flows(),
        code_summary=None,
        diagrams=diagrams,
        framework=Framework.STRIDE,
    )

    assert 'name="flow"' in ctx
    assert 'name="deployment"' in ctx
    assert ctx.index('name="flow"') < ctx.index('name="deployment"')
    assert ctx.count("graph TD") == 2
    # No image placeholder text — these are Mermaid, not PNG/JPEG.
    assert "vision image" not in ctx
