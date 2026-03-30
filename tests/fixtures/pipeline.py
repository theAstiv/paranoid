"""Canned pipeline responses for a Document Sharing Web Application.

All responses satisfy Pydantic validation constraints:
- Threat descriptions: 35-50 words
- Mitigations: 2-5 items per threat
- DREAD scores: 0-10 per dimension
"""

from backend.models.enums import AssetType, StrideCategory
from backend.models.extended import AttackTree, CodeContext, CodeFile, CodeSummary, TestSuite
from backend.models.state import (
    Asset,
    AssetsList,
    DataFlow,
    DreadScore,
    FlowsList,
    GapAnalysis,
    SummaryState,
    Threat,
    ThreatsList,
    ThreatSource,
    TrustBoundary,
)


def make_code_context() -> CodeContext:
    """Realistic code context for the document sharing web application."""
    return CodeContext(
        repository="/home/user/document-sharing-app",
        files=[
            CodeFile(
                path="backend/routes/documents.py",
                language="python",
                content=(
                    "from fastapi import APIRouter, Depends, HTTPException, UploadFile\n"
                    "from sqlalchemy.orm import Session\n"
                    "from backend.auth import get_current_user\n"
                    "from backend.models import Document, User\n"
                    "from backend.database import get_db\n\n"
                    "router = APIRouter()\n\n"
                    "@router.post('/api/documents')\n"
                    "async def upload_document(\n"
                    "    file: UploadFile,\n"
                    "    db: Session = Depends(get_db),\n"
                    "    current_user: User = Depends(get_current_user)\n"
                    ") -> dict:\n"
                    "    # No file size validation - potential DoS\n"
                    "    content = await file.read()\n"
                    "    doc = Document(owner_id=current_user.id, filename=file.filename, content=content)\n"
                    "    db.add(doc)\n"
                    "    db.commit()\n"
                    "    return {'id': doc.id, 'filename': doc.filename}\n\n"
                    "@router.get('/api/documents/{doc_id}')\n"
                    "async def get_document(\n"
                    "    doc_id: int,\n"
                    "    db: Session = Depends(get_db),\n"
                    "    current_user: User = Depends(get_current_user)\n"
                    ") -> dict:\n"
                    "    # Missing authorization check - IDOR vulnerability\n"
                    "    doc = db.query(Document).filter(Document.id == doc_id).first()\n"
                    "    if not doc:\n"
                    "        raise HTTPException(status_code=404, detail='Document not found')\n"
                    "    return {'id': doc.id, 'filename': doc.filename, 'owner_id': doc.owner_id}\n"
                ),
            ),
            CodeFile(
                path="backend/routes/search.py",
                language="python",
                content=(
                    "from fastapi import APIRouter, Depends, Query\n"
                    "from sqlalchemy.orm import Session\n"
                    "from backend.auth import get_current_user\n"
                    "from backend.models import Document, User\n"
                    "from backend.database import get_db\n\n"
                    "router = APIRouter()\n\n"
                    "@router.get('/api/documents/search')\n"
                    "async def search_documents(\n"
                    "    q: str = Query(...),\n"
                    "    db: Session = Depends(get_db),\n"
                    "    current_user: User = Depends(get_current_user)\n"
                    ") -> list[dict]:\n"
                    "    # SQL injection vulnerability - string concatenation\n"
                    "    query = f\"SELECT * FROM documents WHERE filename LIKE '%{q}%'\"\n"
                    "    results = db.execute(query).fetchall()\n"
                    "    return [{'id': r.id, 'filename': r.filename} for r in results]\n"
                ),
            ),
            CodeFile(
                path="backend/auth.py",
                language="python",
                content=(
                    "from fastapi import Depends, HTTPException\n"
                    "from fastapi.security import HTTPBearer\n"
                    "from jose import jwt, JWTError\n"
                    "from sqlalchemy.orm import Session\n"
                    "from backend.models import User\n"
                    "from backend.database import get_db\n\n"
                    "SECRET_KEY = 'supersecret123'  # Hardcoded secret\n"
                    "ALGORITHM = 'HS256'\n"
                    "security = HTTPBearer()\n\n"
                    "def get_current_user(\n"
                    "    token: str = Depends(security),\n"
                    "    db: Session = Depends(get_db)\n"
                    ") -> User:\n"
                    "    try:\n"
                    "        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])\n"
                    "        user_id: str = payload.get('sub')\n"
                    "        if user_id is None:\n"
                    "            raise HTTPException(status_code=401, detail='Invalid token')\n"
                    "    except JWTError:\n"
                    "        raise HTTPException(status_code=401, detail='Invalid token')\n"
                    "    user = db.query(User).filter(User.id == int(user_id)).first()\n"
                    "    if user is None:\n"
                    "        raise HTTPException(status_code=401, detail='User not found')\n"
                    "    return user\n"
                ),
            ),
        ],
    )


def make_code_summary() -> CodeSummary:
    """Realistic code summary for the document sharing web application."""
    return CodeSummary(
        tech_stack=[
            "Python 3.11",
            "FastAPI 0.104.1",
            "SQLAlchemy 2.0.23",
            "PostgreSQL 15",
            "python-jose 3.3.0 (JWT)",
        ],
        entry_points=[
            "POST /api/documents",
            "GET /api/documents/{doc_id}",
            "GET /api/documents/search",
            "POST /api/auth/login",
            "POST /api/auth/register",
        ],
        auth_patterns=[
            "JWT-based authentication using python-jose with HS256 algorithm",
            "HTTPBearer token extraction from Authorization header",
            "Hardcoded SECRET_KEY in backend/auth.py ('supersecret123')",
            "No token expiration or refresh mechanism visible",
            "Missing HttpOnly/Secure cookie flags (tokens sent as Bearer)",
        ],
        data_stores=[
            "PostgreSQL database with documents table (id, owner_id, filename, content, created_at)",
            "PostgreSQL database with users table (id, username, password_hash, created_at)",
            "No evidence of encryption at rest for document content column",
        ],
        external_dependencies=[
            "No external API calls detected in provided code samples",
        ],
        security_observations=[
            "CRITICAL: SQL injection in backend/routes/search.py - string concatenation of user input",
            "CRITICAL: Hardcoded JWT secret key in backend/auth.py",
            "HIGH: Missing authorization check in GET /api/documents/{doc_id} - IDOR vulnerability",
            "HIGH: No file size validation in document upload endpoint - DoS risk",
            "MEDIUM: No rate limiting visible on any endpoints",
            "POSITIVE: Password hashing indicated by password_hash column (implementation not shown)",
            "POSITIVE: SQLAlchemy ORM used for most queries (except search endpoint)",
        ],
        raw_summary=(
            "The document sharing application uses a modern Python/FastAPI stack with "
            "PostgreSQL for data persistence and JWT-based authentication. The codebase "
            "exhibits several critical security vulnerabilities: SQL injection via string "
            "concatenation in the search endpoint, a hardcoded JWT secret key, missing "
            "authorization checks enabling insecure direct object reference (IDOR) attacks, "
            "and absent file size validation allowing denial-of-service via large uploads. "
            "Authentication relies on JWT tokens passed as Bearer tokens without evidence of "
            "expiration, refresh mechanisms, or secure cookie attributes. The database schema "
            "stores document content in a PostgreSQL column with no visible encryption at rest. "
            "Positive security controls include the use of SQLAlchemy ORM for most database "
            "operations and apparent password hashing for user credentials. The application "
            "requires immediate remediation of the SQL injection and IDOR vulnerabilities, "
            "proper secrets management, comprehensive authorization checks, and file upload "
            "constraints before production deployment."
        ),
    )


def make_summary() -> SummaryState:
    """35-word system summary for a document sharing web application."""
    return SummaryState(
        summary=(
            "A document sharing web application enabling users to upload, "
            "store, and share files through an API gateway backed by a "
            "PostgreSQL database with role-based access control and "
            "encrypted storage."
        )
    )


def make_assets() -> AssetsList:
    """4 assets representing core components of the document sharing app."""
    return AssetsList(
        assets=[
            Asset(
                type=AssetType.ASSET,
                name="Web Application",
                description="Svelte frontend serving the document management UI",
            ),
            Asset(
                type=AssetType.ASSET,
                name="PostgreSQL Database",
                description="Primary data store for user accounts and document metadata",
            ),
            Asset(
                type=AssetType.ASSET,
                name="API Gateway",
                description="FastAPI backend handling authentication and request routing",
            ),
            Asset(
                type=AssetType.ENTITY,
                name="End User",
                description="Authenticated user accessing the document sharing platform",
            ),
        ]
    )


def make_flows() -> FlowsList:
    """3 data flows, 2 trust boundaries, 2 threat sources."""
    return FlowsList(
        data_flows=[
            DataFlow(
                flow_description="User submits authentication credentials via HTTPS",
                source_entity="End User",
                target_entity="API Gateway",
            ),
            DataFlow(
                flow_description="API Gateway queries user records and document metadata",
                source_entity="API Gateway",
                target_entity="PostgreSQL Database",
            ),
            DataFlow(
                flow_description="Web Application renders document list from API response",
                source_entity="API Gateway",
                target_entity="Web Application",
            ),
        ],
        trust_boundaries=[
            TrustBoundary(
                purpose="Network boundary between public internet and internal services",
                source_entity="End User",
                target_entity="API Gateway",
            ),
            TrustBoundary(
                purpose="Application boundary between API layer and data layer",
                source_entity="API Gateway",
                target_entity="PostgreSQL Database",
            ),
        ],
        threat_sources=[
            ThreatSource(
                category="External Attacker",
                description="Unauthenticated attacker targeting the public API surface",
                example="Script kiddie scanning for exposed endpoints",
            ),
            ThreatSource(
                category="Malicious Insider",
                description="Authenticated user attempting privilege escalation",
                example="Employee accessing documents outside their authorization scope",
            ),
        ],
    )


def _make_dread(
    damage: int = 7,
    repro: int = 6,
    exploit: int = 5,
    users: int = 8,
    discover: int = 6,
) -> DreadScore:
    return DreadScore(
        damage=damage,
        reproducibility=repro,
        exploitability=exploit,
        affected_users=users,
        discoverability=discover,
    )


def make_stride_threats() -> ThreatsList:
    """6 STRIDE threats (one per category), with DREAD scores and 35-50 word descriptions."""
    return ThreatsList(
        threats=[
            Threat(
                name="Session Token Forgery",
                stride_category=StrideCategory.SPOOFING,
                description=(
                    "An attacker could forge or steal session tokens to impersonate "
                    "legitimate users and gain unauthorized access to the document sharing "
                    "platform. By intercepting authentication cookies or exploiting weak "
                    "token generation, the attacker bypasses identity verification "
                    "controls entirely."
                ),
                target="API Gateway",
                impact="high",
                likelihood="medium",
                dread=_make_dread(damage=8, repro=6, exploit=5, users=9, discover=5),
                mitigations=[
                    "Implement cryptographically secure token generation with sufficient entropy",
                    "Set HttpOnly, Secure, and SameSite flags on session cookies",
                    "Enforce short token expiration with sliding window renewal",
                ],
            ),
            Threat(
                name="SQL Injection in Document Search",
                stride_category=StrideCategory.TAMPERING,
                description=(
                    "An attacker could inject malicious SQL statements through the document "
                    "search endpoint to modify or corrupt stored document metadata and user "
                    "records in the PostgreSQL database. This exploitation of insufficient "
                    "input validation could alter access control lists and document "
                    "ownership records."
                ),
                target="PostgreSQL Database",
                impact="critical",
                likelihood="medium",
                dread=_make_dread(damage=9, repro=7, exploit=6, users=8, discover=7),
                mitigations=[
                    "Use parameterized queries exclusively for all database operations",
                    "Apply input validation and sanitization on all user-provided search terms",
                    "Implement database-level permissions restricting application user privileges",
                ],
            ),
            Threat(
                name="Unsigned API Request Repudiation",
                stride_category=StrideCategory.REPUDIATION,
                description=(
                    "Users could deny performing document deletion or sharing actions "
                    "because the system lacks comprehensive audit logging with tamper-proof "
                    "records. Without cryptographic signatures on critical operations, "
                    "users can plausibly repudiate file modifications and access "
                    "permission changes."
                ),
                target="API Gateway",
                impact="medium",
                likelihood="medium",
                dread=_make_dread(damage=5, repro=8, exploit=4, users=6, discover=4),
                mitigations=[
                    "Implement append-only audit logging for all document operations",
                    "Add cryptographic signatures to critical API request records",
                ],
            ),
            Threat(
                name="Document Metadata Leakage via Error Messages",
                stride_category=StrideCategory.INFORMATION_DISCLOSURE,
                description=(
                    "Verbose error messages from the API gateway could expose sensitive "
                    "document metadata, database schema details, and internal file paths "
                    "to unauthorized users. Stack traces and debug information returned "
                    "in production responses reveal system architecture enabling "
                    "targeted attacks."
                ),
                target="API Gateway",
                impact="medium",
                likelihood="high",
                dread=_make_dread(damage=6, repro=9, exploit=8, users=7, discover=9),
                mitigations=[
                    "Return generic error messages to clients in production mode",
                    "Log detailed errors server-side only with structured logging",
                    "Implement error response sanitization middleware",
                ],
            ),
            Threat(
                name="Document Upload Denial of Service",
                stride_category=StrideCategory.DENIAL_OF_SERVICE,
                description=(
                    "An attacker could exhaust server resources by uploading extremely "
                    "large files or flooding the upload endpoint with concurrent requests. "
                    "Without proper rate limiting and file size constraints, the document "
                    "storage service becomes unavailable to legitimate users attempting "
                    "normal operations."
                ),
                target="Web Application",
                impact="high",
                likelihood="high",
                dread=_make_dread(damage=7, repro=9, exploit=8, users=9, discover=8),
                mitigations=[
                    "Enforce maximum file size limits on upload endpoints",
                    "Implement per-user rate limiting on upload and API requests",
                    "Deploy request queuing with backpressure mechanisms",
                ],
            ),
            Threat(
                name="Insecure Direct Object Reference for Documents",
                stride_category=StrideCategory.ELEVATION_OF_PRIVILEGE,
                description=(
                    "An authenticated user could access or modify documents belonging to "
                    "other users by manipulating document identifiers in API requests. "
                    "Predictable sequential document IDs combined with missing authorization "
                    "checks on individual resource access enable horizontal privilege "
                    "escalation across user accounts."
                ),
                target="API Gateway",
                impact="critical",
                likelihood="high",
                dread=_make_dread(damage=9, repro=8, exploit=7, users=8, discover=7),
                mitigations=[
                    "Use non-sequential UUIDs for all document identifiers",
                    "Implement per-request authorization checks verifying document ownership",
                    "Add row-level security policies in the database layer",
                ],
            ),
        ]
    )


def make_maestro_threats() -> ThreatsList:
    """3 MAESTRO-relevant threats for AI/ML components."""
    return ThreatsList(
        threats=[
            Threat(
                name="Prompt Injection via Document Content",
                stride_category=StrideCategory.TAMPERING,
                description=(
                    "An attacker could embed adversarial instructions within uploaded "
                    "documents that are processed by the AI summarization component. "
                    "These injected prompts could manipulate the language model into "
                    "revealing system prompts, bypassing content filters, or generating "
                    "misleading document summaries."
                ),
                target="AI Summarization Service",
                impact="high",
                likelihood="medium",
                dread=_make_dread(damage=7, repro=6, exploit=6, users=7, discover=5),
                mitigations=[
                    "Sanitize document content before passing to language model",
                    "Implement output validation against known injection patterns",
                    "Use system prompt hardening with clear instruction boundaries",
                ],
            ),
            Threat(
                name="Model Extraction via API Probing",
                stride_category=StrideCategory.INFORMATION_DISCLOSURE,
                description=(
                    "An adversary could systematically query the document classification "
                    "API with crafted inputs to reconstruct the underlying machine learning "
                    "model parameters and decision boundaries. Repeated probing reveals "
                    "model architecture details enabling development of targeted evasion "
                    "techniques against content filtering."
                ),
                target="ML Classification Endpoint",
                impact="medium",
                likelihood="low",
                dread=_make_dread(damage=6, repro=4, exploit=5, users=5, discover=4),
                mitigations=[
                    "Rate-limit classification API requests per user session",
                    "Add controlled noise to model confidence scores in responses",
                ],
            ),
            Threat(
                name="Training Data Poisoning via Malicious Documents",
                stride_category=StrideCategory.TAMPERING,
                description=(
                    "An attacker could upload carefully crafted documents designed to "
                    "corrupt the training data used for the document classification model. "
                    "By introducing biased or adversarial samples into the training pipeline, "
                    "the attacker degrades model accuracy and introduces systematic "
                    "misclassification of sensitive documents."
                ),
                target="ML Training Pipeline",
                impact="high",
                likelihood="low",
                dread=_make_dread(damage=8, repro=3, exploit=4, users=7, discover=3),
                mitigations=[
                    "Implement data provenance tracking for all training samples",
                    "Use anomaly detection on incoming training data distributions",
                    "Require human review for training data from untrusted sources",
                ],
            ),
        ]
    )


def make_gap_analysis(stop: bool = False) -> GapAnalysis:
    """Gap analysis result. stop=False returns gap text, stop=True signals completion."""
    if stop:
        return make_gap_analysis_stop()
    return GapAnalysis(
        stop=False,
        gap=(
            "The current threat catalog lacks coverage for: "
            "1) Cross-site scripting (XSS) attacks on the document preview renderer, "
            "2) Server-side request forgery (SSRF) via document URL imports, "
            "3) Insufficient logging of administrative actions for compliance. "
            "Consider adding threats for client-side rendering vulnerabilities "
            "and supply chain risks in third-party document parsing libraries."
        ),
    )


def make_gap_analysis_stop() -> GapAnalysis:
    """Gap analysis indicating comprehensive coverage — stop iterating."""
    return GapAnalysis(stop=True, gap=None)


def make_attack_tree() -> AttackTree:
    """Attack tree with Mermaid source for SQL injection threat."""
    return AttackTree(
        threat_name="SQL Injection in Document Search",
        mermaid_source=(
            "graph TD\n"
            '    A["SQL Injection in Document Search"] --> B["Via Search Input"]\n'
            '    A --> C["Via Filter Parameters"]\n'
            '    B --> D["Union-based Injection"]\n'
            '    B --> E["Boolean-blind Injection"]\n'
            '    C --> F["Order-by Injection"]\n'
            '    D --> G["Extract User Credentials"]\n'
            '    E --> H["Enumerate Table Schema"]\n'
            '    F --> I["Determine Column Count"]'
        ),
    )


def make_test_suite() -> TestSuite:
    """Gherkin test suite for SQL injection threat."""
    return TestSuite(
        feature="SQL Injection Prevention in Document Search",
        gherkin_source=(
            "Feature: SQL Injection Prevention in Document Search\n"
            "\n"
            "  Scenario: Search input with SQL injection attempt is rejected\n"
            "    Given a user is authenticated\n"
            '    When the user searches for "documents; DROP TABLE users;--"\n'
            "    Then the API returns a 400 Bad Request\n"
            "    And no SQL is executed beyond the parameterized query\n"
            "\n"
            "  Scenario: Legitimate search returns expected results\n"
            "    Given a user is authenticated\n"
            '    And a document titled "Q4 Report" exists\n'
            '    When the user searches for "Q4 Report"\n'
            "    Then the API returns the matching document\n"
            "    And the response status is 200 OK"
        ),
    )
