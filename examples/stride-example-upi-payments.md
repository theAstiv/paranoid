# STRIDE Example: UPI P2P + Bill Payments App

This example demonstrates threat modeling for a consumer UPI payments application using the STRIDE framework with structured XML-tagged input. It models a Third-Party UPI Application Provider (TPAP) operating under RBI / NPCI rails.

---

## Component Description

```xml
<component_description>
```

**Name:** Consumer UPI Payments and Bill Pay App (TPAP)

**Purpose:** Mobile application that lets users link Indian bank accounts via UPI, send and receive money to VPAs or phone numbers, scan QR codes for merchant payments, and pay recurring bills (electricity, gas, FASTag recharge). Acts as a TPAP that routes UPI messages through a licensed PSP bank to the NPCI UPI switch.

**Technology Stack:**
- **Language(s):** Kotlin (Android), Swift (iOS), Python 3.12 (backend), TypeScript (admin console)
- **Framework(s):** FastAPI, Jetpack Compose, SwiftUI, React (admin)
- **Libraries / SDKs:** PSP bank UPI SDK (signs UPI XML inside the SDK against device fingerprint), OkHttp, AlamoFire, fastapi-jwt-auth, SQLAlchemy, fastembed (offline ML for fraud signals)
- **Cloud Infrastructure:** AWS Mumbai (ap-south-1), ECS Fargate, Aurora PostgreSQL, ElastiCache Redis, SQS, CloudFront for static assets
- **Cloud Platforms:** AWS only (DPDP Act data-residency); no cross-region replication

**Interfaces and Protocols:**
- Inbound Interfaces:
  - HTTPS REST API - Customer endpoints (`POST /v1/intent/pay`, `POST /v1/vpa/resolve`, `GET /v1/txn/{id}`)
  - HTTPS REST API - Admin console (`POST /admin/refund-review`, `GET /admin/disputes`)
  - HTTPS webhooks - PSP bank callbacks for txn status (`POST /webhooks/psp/status`)
  - HTTPS webhooks - Biller aggregator BBPS callbacks (`POST /webhooks/bbps/status`)
- Outbound Interfaces:
  - HTTPS REST to PSP bank (`/upi/collect`, `/upi/pay`, `/upi/mandate`) — payload is a signed UPI XML produced by the SDK
  - HTTPS REST to Video KYC vendor (onboarding)
  - HTTPS REST to BBPS biller aggregator (bill fetch + pay)
  - SMS via Karix / Gupshup for OTP and txn alerts
  - Push notifications via FCM and APNs
  - Writes structured logs to AWS CloudWatch

**Data Handled:**
- **Sensitive Data Types:** UPI VPA, masked bank account number, IFSC, PAN (KYC), Aadhaar XML (eKYC artefact), device binding token, transaction amount and counterparty, beneficiary nickname, mobile number, geo-location at payment time
- **Storage Mechanisms:** Aurora PostgreSQL (user + txn, field-level KMS envelope encryption for PAN and account number), Redis (session + idempotency keys, TLS in transit, encryption at rest enabled), S3 (KYC PDFs with bucket-level KMS + Object Lock for 7 years)

**Trust Level:**
- **Internal/External:** Internet-exposed mobile app and admin console; private subnet for backend; private link to PSP bank
- **Authentication / Authorization Used:** Device binding via PSP SDK (NPCI-registered device fingerprint + SIM binding), UPI PIN entered inside SDK and never visible to app, biometric app-unlock, JWT for backend session (15 min access + 7 day refresh), RBAC for admin console with TOTP MFA, mTLS to PSP bank

**Dependencies:**
- PSP bank UPI switch client (critical, no fallback)
- NPCI UPI switch (out-of-scope but on the path)
- Video KYC vendor (onboarding only)
- BBPS biller aggregator (bill payments)
- SMS gateway (OTP, alerts)
- FCM / APNs (push)
- AWS managed services (Aurora, ElastiCache, S3, KMS, Secrets Manager, CloudWatch)

```xml
</component_description>
```

---

## Assumptions

```xml
<assumptions>
```

**Security Controls Already in Place:**
- TLS 1.3 enforced for all client and server-to-server traffic
- mTLS between backend and PSP bank
- UPI PIN is captured inside the PSP SDK and never reaches our app process memory
- Device binding tied to SIM + device fingerprint per NPCI common library spec
- Field-level KMS envelope encryption on PII columns (PAN, account number, Aadhaar reference)
- Idempotency keys enforced on all payment intents (24h Redis TTL)
- AWS WAF in front of API Gateway with managed rules (OWASP, bot-control)
- Rate limit: 5 outgoing payments / min / user, 60 / hour / device
- Admin console behind VPN + TOTP MFA + IP allowlist
- Secrets in AWS Secrets Manager with 30-day rotation
- CloudTrail + GuardDuty enabled; CloudWatch logs retained 90 days
- All bank statements, KYC docs encrypted at rest with KMS CMK

**Areas Considered In-Scope:**
- Mobile client request signing, JWT and session handling
- Idempotency and double-spend prevention on UPI intents
- Authorization for refund / dispute / admin endpoints
- Webhook authenticity (PSP bank callbacks, BBPS callbacks)
- VPA resolution abuse (enumeration of registered VPAs)
- KYC flow (video KYC vendor handoff, Aadhaar XML handling)
- Beneficiary tampering and on-screen confirmation integrity
- Logging hygiene (no PIN, no full PAN, no Aadhaar in logs)
- Push and SMS spoofing of transaction alerts
- Fraud signals pipeline (device anomaly, velocity, geo)

**Areas Considered Out-of-Scope:**
- NPCI UPI switch internals
- Remitter and beneficiary bank core banking systems
- PSP bank's HSM and signing keys (managed by PSP)
- AWS shared-responsibility infrastructure
- Mobile OS-level vulnerabilities (rooted device detection is in-scope, OS CVEs are not)
- Physical security of data centers
- Video KYC vendor's internal ML models

**Known Constraints or Limitations:**
- VPA-to-name lookup is exposed pre-auth for UX reasons (legitimate UPI behaviour, but enables enumeration)
- Transaction alerts via SMS rely on operator delivery (no read-receipt guarantee)
- Admin console refunds are reversible only within T+1 NPCI window
- Beneficiary nicknames are user-controlled strings rendered in confirmation screen
- Webhook secrets per PSP partner are shared symmetric HMAC (not asymmetric)
- 4-digit UPI PIN per NPCI spec (cannot increase entropy)

**Development or Operational Considerations:**
- RBI regulated as TPAP; periodic NPCI audits
- DPDP Act 2023 compliance, no cross-border data transfer
- PCI-DSS scope is reduced (no card data) but in-scope for tokenised bill-pay
- Bug bounty program runs on staging mirror
- Mobile app released fortnightly; backend daily; blue-green deploy with 5-min rollback
- 24x7 SOC + on-call rotation

**Threat Modeling Focus Areas:**
- Beneficiary tampering between confirmation screen and signed UPI XML
- Replay or substitution of PSP bank webhook callbacks
- VPA enumeration and harvest of user identity
- Idempotency-key collision or bypass leading to double debit
- Session theft on rooted / jailbroken devices
- Authorization bypass on admin refund endpoint
- Sensitive data leakage via logs, crash reports, or error responses
- SMS / push spoofing leading to social-engineering fraud
- Privilege escalation from customer support role to refund-approver role
- Information disclosure through detailed error responses on `/vpa/resolve`

```xml
</assumptions>
```

---

## How to Use This Example

```bash
paranoid run examples/stride-example-upi-payments.md \
  --iterations 5 \
  --diagram examples/stride-upi-payments-architecture.mmd \
  --output upi-payments-threats.json
```

### Expected Output

The pipeline will generate threats covering all STRIDE categories:

- **Spoofing**: PSP webhook forgery, VPA enumeration, push/SMS alert spoofing
- **Tampering**: Beneficiary swap between confirmation and signed XML, idempotency-key replay, log tampering
- **Repudiation**: Missing signed audit trail for refund approvals, insufficient device-binding evidence
- **Information Disclosure**: VPA resolution oracle, verbose error responses, KYC artefact exposure in logs
- **Denial of Service**: Rate-limit bypass per device fingerprint, biller-callback flooding
- **Elevation of Privilege**: Customer-support role gaining refund-approver capability, admin JWT scope confusion

---

## Notes

- This system sits behind RBI / NPCI rails — model the TPAP boundary, not the switch
- DPDP Act and PCI-DSS scope are real compliance pressures; weight findings accordingly
- VPA resolution is intentionally pre-auth — treat enumeration as a UX-vs-security trade
