# STRIDE Example: E-commerce API Gateway

This example demonstrates threat modeling for a traditional microservices API Gateway using the STRIDE framework with structured XML-tagged input.

---

## Component Description

```xml
<component_description>
```

**Name:** E-commerce API Gateway

**Purpose:** Central entry point for all client requests to the e-commerce platform. Routes authenticated requests to backend microservices (user service, product catalog, order service, payment service). Handles rate limiting, request validation, and response aggregation.

**Technology Stack:**
- **Language(s):** Node.js (v18), TypeScript
- **Framework(s):** Express.js, AWS API Gateway (REST API)
- **Libraries / SDKs:** AWS SDK v3, express-rate-limit, joi (validation), jsonwebtoken (JWT), winston (logging)
- **Cloud Infrastructure:** Docker containers on AWS ECS Fargate
- **Cloud Platforms:** AWS (API Gateway, ECS, ALB, Route53, CloudFront)

**Interfaces and Protocols:**
- Inbound Interfaces:
  - HTTPS REST API - Public endpoints (GET /products, POST /orders, etc.)
  - HTTPS REST API - Admin endpoints (POST /admin/users, DELETE /admin/products)
  - WebSocket - Real-time order status updates (wss://api.example.com/ws)
- Outbound Interfaces:
  - gRPC calls to User Service (AuthenticateUser, GetUserProfile)
  - HTTP REST calls to Product Catalog Service
  - HTTP REST calls to Order Service
  - HTTP REST calls to Payment Service (Stripe API)
  - Publishes events to AWS SNS (order.created, payment.processed)
  - Writes logs to AWS CloudWatch

**Data Handled:**
- **Sensitive Data Types:** User credentials (JWTs), PII (names, addresses, emails), payment tokens (Stripe), session cookies, API keys (admin)
- **Storage Mechanisms:** Redis ElastiCache (session store), AWS Secrets Manager (API keys), AWS Parameter Store (config)

**Trust Level:**
- **Internal/External:** Internet-exposed (public API), private subnet communication with backend services
- **Authentication / Authorization Used:** JWT-based authentication (OAuth 2.0), Role-based access control (RBAC) for admin endpoints, mTLS for service-to-service communication

**Dependencies:**
- AWS API Gateway
- AWS ECS Fargate
- Redis ElastiCache (session store)
- AWS Secrets Manager
- Backend microservices (User, Product, Order, Payment)
- Stripe API (external payment processor)
- AWS SNS (event notifications)
- AWS CloudWatch (logging and monitoring)

```xml
</component_description>
```

---

## Assumptions

```xml
<assumptions>
```

**Security Controls Already in Place:**
- AWS WAF protects API Gateway with OWASP Top 10 rules enabled
- TLS 1.3 enforced for all HTTPS connections
- Backend microservices communicate over mTLS
- Database encryption at rest using AWS KMS
- API Gateway logs all requests to CloudWatch with 90-day retention
- DDoS protection via AWS Shield Standard
- Secrets rotation enabled for database credentials (30-day cycle)

**Areas Considered In-Scope:**
- API Gateway request validation and authentication
- JWT token handling and session management
- Authorization checks for admin endpoints
- Communication between API Gateway and backend microservices
- Rate limiting and abuse prevention
- Input validation and injection attack prevention
- Logging and monitoring for security events
- Error handling and information leakage

**Areas Considered Out-of-Scope:**
- Security of backend microservices' internal logic (separate threat models)
- AWS infrastructure security (assumed secure per shared responsibility model)
- Stripe API security (third-party, assumed secure)
- Employee workstations and development environments
- Physical security of AWS data centers
- CDN security (CloudFront configuration is separate)

**Known Constraints or Limitations:**
- No rate limiting currently enforced per user (only per IP address)
- JWT tokens have 24-hour expiration (no token refresh mechanism)
- No automated API key rotation for admin endpoints
- Session data in Redis is not encrypted at rest
- Admin endpoints use same authentication as user endpoints (no MFA)
- Error messages may expose internal service names
- No request/response payload size limits enforced

**Development or Operational Considerations:**
- Service is under active development — new endpoints added weekly
- Deployed via CI/CD pipeline (GitHub Actions) with automated testing
- Blue-green deployment strategy with 5-minute rollback window
- On-call rotation for security incidents (24/7 coverage)
- PCI-DSS compliance required for payment data handling
- GDPR compliance required for EU customer data

**Threat Modeling Focus Areas:**
- Authentication bypass vectors (JWT vulnerabilities, session hijacking)
- Authorization flaws (privilege escalation, IDOR)
- Injection attacks (SQL injection via user input, NoSQL injection)
- API abuse (rate limiting bypass, resource exhaustion)
- Information disclosure (error messages, logging sensitive data)
- Man-in-the-middle attacks on service-to-service communication
- Session management vulnerabilities (fixation, hijacking)

```xml
</assumptions>
```

---

## How to Use This Example

### Option 1: Command Line (CLI)

```bash
paranoid run examples/stride-example-api-gateway.md \
  --iterations 5 \
  --output stride-api-gateway-threats.json
```

### Option 2: Python API

```python
from backend.pipeline.runner import run_pipeline_for_model
from backend.providers.anthropic import AnthropicProvider
from backend.models.enums import Framework

# Read the structured input
with open("examples/stride-example-api-gateway.md", "r") as f:
    description = f.read()

# Initialize provider
provider = AnthropicProvider(api_key="your-api-key")

# Run pipeline
async for event in run_pipeline_for_model(
    model_id="api-gateway-tm-001",
    description=description,
    framework=Framework.STRIDE,
    provider=provider,
    max_iterations=5,
    has_ai_components=False,  # No AI/ML components
):
    print(f"[{event.step}] {event.status}: {event.message}")
```

### Expected Output

The pipeline will generate threats covering all STRIDE categories:

- **Spoofing**: JWT token forgery, session hijacking, admin credential theft
- **Tampering**: Request/response manipulation, MITM on service calls, log tampering
- **Repudiation**: Missing audit trails, insufficient logging, non-repudiation gaps
- **Information Disclosure**: Error message leakage, log exposure, session data exposure
- **Denial of Service**: Rate limit bypass, resource exhaustion, distributed DoS
- **Elevation of Privilege**: Admin endpoint authorization bypass, role escalation, IDOR

Each threat will include:
- DREAD score (Damage, Reproducibility, Exploitability, Affected Users, Discoverability)
- Severity classification (Critical/High/Medium/Low)
- Specific mitigations (Preventive, Detective, Containment)

---

## Notes

- The structured template format provides rich context to the LLM
- Assumptions ensure gap analysis respects in-scope/out-of-scope boundaries
- Focus areas guide the model to prioritize specific threat vectors
- Security controls prevent redundant threat suggestions
