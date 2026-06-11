# STRIDE Example: Razorpay Payment Integration Backend

This example demonstrates threat modeling for a Python backend service that integrates with the Razorpay payment gateway for UPI, card, and netbanking payments. Designed for use with the `--code` flag pointing at the [razorpay/razorpay-python](https://github.com/razorpay/razorpay-python) SDK repository, so Paranoid can analyse the SDK's webhook verification, signature validation, and API call patterns alongside the structured description.

---

## Component Description

```xml
<component_description>
```

**Name:** Merchant Payment Service — Razorpay Integration Backend

**Purpose:** Server-side payment orchestration service that creates Razorpay orders, processes payment callbacks, verifies webhook signatures, handles refunds, and manages subscription billing for a multi-tenant SaaS platform. Customers initiate payments via UPI intent, UPI collect, cards, or netbanking on the frontend; this service owns the server-side lifecycle from order creation through settlement reconciliation.

**Technology Stack:**
- **Language(s):** Python 3.12 (backend), TypeScript (checkout frontend)
- **Framework(s):** Django 5.x (REST API), Django REST Framework, Celery (async webhook processing and reconciliation)
- **Libraries / SDKs:** razorpay-python SDK (official — handles HMAC signature generation, API authentication, webhook verification via `razorpay.Utility.verify_webhook_signature`), requests, pyjwt, django-environ, psycopg2-binary
- **Database:** PostgreSQL 16 (orders, payments, refunds, subscriptions, tenant config)
- **Cloud Infrastructure:** AWS Mumbai (ap-south-1), ECS Fargate, RDS PostgreSQL (Multi-AZ), ElastiCache Redis (Celery broker + idempotency), S3 (invoice PDFs), CloudFront (frontend)
- **Message Queue:** SQS + Celery for webhook processing and settlement reconciliation

**Interfaces and Protocols:**
- Inbound Interfaces:
  - HTTPS REST API — Checkout (`POST /api/v1/orders/create`, `POST /api/v1/payments/verify`, `GET /api/v1/orders/{id}/status`)
  - HTTPS REST API — Refunds (`POST /api/v1/refunds/create`, `GET /api/v1/refunds/{id}`)
  - HTTPS REST API — Subscriptions (`POST /api/v1/subscriptions/create`, `POST /api/v1/subscriptions/{id}/cancel`)
  - HTTPS webhook — Razorpay event callbacks (`POST /webhooks/razorpay/` — events: `payment.authorized`, `payment.captured`, `payment.failed`, `refund.processed`, `subscription.charged`, `settlement.processed`)
  - HTTPS REST API — Admin/ops (`GET /api/v1/admin/reconciliation`, `POST /api/v1/admin/manual-capture`)
- Outbound Interfaces:
  - HTTPS REST to Razorpay API (`api.razorpay.com` — order creation, payment capture, refund initiation, fetch payment details)
  - HTTPS to downstream billing microservice (invoice generation)
  - SQS for async webhook processing
  - SMTP for payment confirmation and refund notification emails

**Data Handled:**
- **Sensitive Data Types:** Razorpay API key ID + secret (server-side only), webhook secret, customer email, phone number, order amounts, payment IDs, Razorpay signatures, partial card details (last 4 digits + network from Razorpay callback — never full PAN), UPI VPA (from payment entity), bank account details for refund routing, subscription plan and billing cycle, tenant API keys
- **Storage Mechanisms:** PostgreSQL (orders, payments, refunds — amount and status; never raw card data), Redis (idempotency keys with 24h TTL, Celery task results), S3 (invoice PDFs encrypted with SSE-S3)

**Trust Level:**
- **Internal/External:** Internet-exposed checkout API and webhook endpoint; admin behind VPN
- **Authentication / Authorization Used:** JWT for customer sessions (15-min access, 7-day refresh), Razorpay key_id + key_secret for API auth (HTTP Basic), HMAC-SHA256 webhook signature verification (razorpay-python `verify_webhook_signature`), tenant-scoped API keys for multi-tenant isolation, Django admin with MFA for ops console, IP allowlist on admin endpoints

**Dependencies:**
- Razorpay API (`api.razorpay.com`) — critical, no fallback
- razorpay-python SDK — handles signature computation, API calls, webhook verification
- PostgreSQL (RDS Multi-AZ)
- Redis (ElastiCache)
- SQS (webhook queue)
- AWS managed services (KMS, Secrets Manager, CloudWatch)

```xml
</component_description>
```

---

## Assumptions

```xml
<assumptions>
```

**Security Controls Already in Place:**
- TLS 1.2+ enforced on all client and server-to-server traffic
- Razorpay API credentials stored in AWS Secrets Manager with 90-day rotation
- Webhook signature verified on every callback using `razorpay.Utility.verify_webhook_signature(body, signature, secret)`
- Payment verification after checkout uses `razorpay.Utility.verify_payment_signature(params_dict)` to validate `razorpay_order_id + razorpay_payment_id + razorpay_signature`
- Idempotency keys enforced on order creation and refund initiation (24h Redis TTL)
- AWS WAF with OWASP managed rules on ALB
- Rate limiting: 30 req/min per customer on checkout, 100 req/min on webhook endpoint
- Admin endpoints behind VPN + MFA + IP allowlist
- Django CSRF protection enabled on non-API views
- Secrets never logged — custom logging filter strips `key_secret`, `webhook_secret`, and `razorpay_signature` fields
- All database queries via Django ORM (parameterised)
- Multi-tenant isolation via tenant_id foreign key on all payment tables + middleware enforcement

**Areas Considered In-Scope:**
- Webhook signature bypass or replay (HMAC verification in razorpay-python SDK)
- Payment verification bypass after Razorpay checkout (signature validation)
- Order amount tampering between frontend and backend (price manipulation)
- Refund abuse: unauthorised refund initiation, refund-to-different-account
- Idempotency key collision or manipulation leading to duplicate charges
- Razorpay API credential exposure (key_secret in logs, error responses, source control)
- Multi-tenant isolation: tenant A accessing tenant B's orders/payments/refunds
- Race conditions on payment capture (double-capture, capture-after-refund)
- Webhook endpoint abuse: replay attacks, out-of-order event processing, denial-of-service
- Subscription billing manipulation: cancel-and-resubscribe to reset billing cycle, plan downgrade without proration
- Admin endpoint authorisation: manual-capture without proper approval, reconciliation data exfiltration

**Areas Considered Out-of-Scope:**
- Razorpay's internal infrastructure and PCI-DSS compliance
- Card network (Visa, Mastercard, RuPay) processing internals
- UPI switch and NPCI internals
- Issuing and acquiring bank systems
- AWS shared-responsibility infrastructure
- End-user device security
- Frontend JavaScript supply chain

**Known Constraints or Limitations:**
- Razorpay webhook delivery is at-least-once — handler must be idempotent
- Webhook events can arrive out of order (`payment.captured` before `payment.authorized`)
- Razorpay API has rate limits (undisclosed exact numbers); aggressive retry can trigger 429
- Payment capture must happen within Razorpay's authorization window (default 5 days for cards, immediate for UPI)
- Refund processing time depends on payment method (UPI instant, cards 5-7 days)
- The razorpay-python SDK uses HTTP Basic auth — key_secret is base64-encoded in the Authorization header, not encrypted
- Webhook secret is shared symmetric (single HMAC key per account, not per-endpoint)
- Settlement reconciliation depends on daily Razorpay settlement files (T+2 for domestic cards)

**Development or Operational Considerations:**
- Multi-tenant SaaS — each tenant has their own Razorpay sub-account or route account
- PCI-DSS scope is limited to SAQ-A (no card data touches our servers — Razorpay hosted checkout)
- Razorpay test mode (key_id starts with `rzp_test_`) used in staging; live mode (`rzp_live_`) in production
- Webhook retry: Razorpay retries failed webhooks up to 24h — handler must handle retries gracefully
- Settlement reconciliation runs as a nightly Celery beat task

**Threat Modeling Focus Areas:**
- Webhook signature verification bypass (timing attacks on HMAC comparison, secret leakage)
- Payment verification bypass after checkout (forged or replayed `razorpay_signature`)
- Order amount manipulation between client-side Razorpay checkout and server-side order record
- Refund endpoint abuse: IDOR (refunding another tenant's payment), amount tampering, unauthorised initiation
- Razorpay API credential exposure in logs, error responses, or environment variable dumps
- Multi-tenant payment data leakage across tenant boundaries
- Race condition between concurrent capture and refund requests on the same payment
- Webhook replay attacks using previously valid signatures
- Idempotency bypass leading to duplicate payment creation or duplicate refund
- Subscription plan manipulation: upgrading without payment, extending trial period
- Test-mode key usage in production (key_id prefix confusion)

```xml
</assumptions>
```

---

## How to Use This Example

### With Code Context (Recommended)

```bash
# First, add the Razorpay Python SDK as a code source in the UI, or clone locally:
git clone --depth 1 https://github.com/razorpay/razorpay-python.git /tmp/razorpay-python

paranoid run examples/stride-example-razorpay-integration.md \
  --code /tmp/razorpay-python \
  --iterations 5 \
  --output razorpay-threats.json
```

### Without Code Context

```bash
paranoid run examples/stride-example-razorpay-integration.md \
  --iterations 3 \
  --output razorpay-threats.json
```

### Expected Output

The pipeline will generate threats covering all STRIDE categories, with code-backed evidence when `--code` is used:

- **Spoofing**: Webhook signature forgery (HMAC bypass), forged payment verification signatures, test-mode credential in production
- **Tampering**: Order amount manipulation between frontend and backend, refund amount tampering, idempotency key collision to duplicate charges, subscription plan parameter tampering
- **Repudiation**: Missing audit trail for manual captures, refund approvals without signed evidence, webhook processing gaps
- **Information Disclosure**: API key_secret in error responses or logs, payment details across tenant boundary, Razorpay dashboard token exposure, partial card data aggregation
- **Denial of Service**: Webhook endpoint flooding, Razorpay API rate limit exhaustion via retry storms, SQS queue poisoning with malformed events
- **Elevation of Privilege**: Cross-tenant payment access (IDOR), customer initiating admin-only manual capture, refund-to-attacker-account via parameter injection

---

## Notes

- The razorpay-python SDK is small (~50 files) and indexes in seconds — ideal for a quick demo
- Code context lets Paranoid inspect the actual HMAC verification implementation, API authentication pattern, and webhook handling — producing threats grounded in real code paths
- Pair this with the UPI Payments sample description for a combined UPI + payment-gateway threat model
