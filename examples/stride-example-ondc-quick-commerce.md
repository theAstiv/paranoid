# STRIDE Example: ONDC Quick-Commerce Buyer App

This example demonstrates threat modeling for a 10-minute grocery delivery application participating in the ONDC network as a Buyer App. Uses the STRIDE framework with structured XML-tagged input. The Beckn / ONDC signing model is in scope; seller and logistics participants are out of scope but their misbehaviour is modelled as an external threat.

---

## Component Description

```xml
<component_description>
```

**Name:** ONDC Buyer App for Hyperlocal Grocery (10-minute delivery)

**Purpose:** Mobile-first buyer app that lets users search groceries across multiple ONDC seller nodes within a 5 km radius, place orders that get routed through the ONDC gateway, track delivery via partner logistics providers, and pay through a hosted UPI intent flow. Backend acts as a registered ONDC Buyer App (BAP) and signs every Beckn request, verifies every signed response.

**Technology Stack:**
- **Language(s):** Go 1.22 (backend), Kotlin (Android), Swift (iOS), TypeScript (Next.js web)
- **Framework(s):** Echo (Go HTTP), gRPC for internal services, Next.js, Jetpack Compose, SwiftUI
- **Libraries / SDKs:** Beckn signing library (Ed25519 over BLAKE2), ONDC Registry client, libsodium, opentelemetry-go, sqlx, pgx
- **Cloud Infrastructure:** GCP Mumbai (asia-south1), GKE, Cloud SQL Postgres, Memorystore Redis, Cloud Storage, Cloud Armor
- **Cloud Platforms:** GCP only (DPDP data residency)

**Interfaces and Protocols:**
- Inbound Interfaces:
  - HTTPS REST API - Buyer app endpoints (`POST /api/search`, `POST /api/cart`, `POST /api/order`)
  - HTTPS REST API - ONDC callback endpoints (`POST /bap/on_search`, `POST /bap/on_select`, `POST /bap/on_init`, `POST /bap/on_confirm`, `POST /bap/on_status`, `POST /bap/on_track`)
  - HTTPS webhook - Payment status from UPI intent flow provider (`POST /webhooks/pay/status`)
- Outbound Interfaces:
  - HTTPS REST signed Beckn requests to ONDC Gateway (`/search`, `/select`, `/init`, `/confirm`, `/status`, `/track`, `/cancel`)
  - HTTPS REST to ONDC Registry for participant lookup (`/lookup`)
  - HTTPS REST to hosted UPI intent flow provider (Razorpay / Cashfree)
  - Cloud Pub/Sub for internal event fan-out
  - Stackdriver for logs and traces

**Data Handled:**
- **Sensitive Data Types:** Buyer name, phone, delivery address (lat/long + flat number), order items, order amount, masked UPI VPA returned by payment provider, signed Beckn payloads (contain delivery PII for the active order)
- **Storage Mechanisms:** Cloud SQL Postgres (orders, users, address book — field-level KMS for address), Memorystore Redis (search cache 5 min TTL, idempotency keys), Cloud Storage (signed payload archive for dispute resolution, KMS encrypted, 90-day retention)

**Trust Level:**
- **Internal/External:** Internet-exposed (consumer app); ONDC participants are mutually authenticated via signed messages; UPI intent flow provider is a trusted third party
- **Authentication / Authorization Used:** OTP-based phone login, JWT (15 min access + 30 day refresh), device binding (token bound to refresh token), all outbound Beckn requests signed with the BAP's Ed25519 private key, all inbound callbacks signed by the originating participant and verified before processing

**Dependencies:**
- ONDC Gateway (critical, no fallback)
- ONDC Registry (participant key lookup, cached 1 hour)
- Hosted UPI intent flow provider (Razorpay / Cashfree)
- Seller nodes (sellers' BPP — out of scope, but signed responses are trusted only after verification)
- Logistics nodes (LSP — out of scope, but signed updates are verified)
- GCP managed services (Cloud SQL, Memorystore, Pub/Sub, KMS, Cloud Storage)

```xml
</component_description>
```

---

## Assumptions

```xml
<assumptions>
```

**Security Controls Already in Place:**
- BAP `subscriber_id` registered with ONDC and a valid Ed25519 keypair is held in GCP KMS
- All outbound Beckn requests are signed per ONDC signing spec (`Authorization` header with `keyId`, `algorithm`, `created`, `expires`, `headers`, `signature`)
- All inbound callbacks have signature verified against the sender's public key, fetched from ONDC Registry and cached 1 hour
- Hosted UPI intent flow — buyer never enters UPI PIN on our app; payment provider handles the entire UPI handshake
- TLS 1.3 enforced; HSTS preload submitted
- Cloud Armor WAF in front of all public endpoints with OWASP rules
- Rate limiting: 30 search/min/user, 5 order/min/user, 200 search/min/IP
- Field-level KMS envelope encryption for delivery address columns
- Address shared with logistics participant only for the active delivery window
- Refresh tokens are device-bound (rotated on each refresh; family invalidation on detected reuse)
- Cloud SQL encrypted at rest with CMEK
- Audit logging enabled on KMS key usage

**Areas Considered In-Scope:**
- Beckn message signing and verification on both directions
- ONDC Registry response handling (participant lookup, key rotation)
- Idempotency for `/init` and `/confirm` calls (preventing duplicate orders)
- Address book CRUD and minimisation of address exposure to LSP
- OTP login flow and refresh-token rotation
- Search-cache poisoning surface (cached signed `on_search` responses)
- Cart manipulation and price tampering between `select` and `confirm`
- Payment-status webhook authenticity
- Logging hygiene (no full address, no phone in production logs)
- Dispute-resolution archive integrity

**Areas Considered Out-of-Scope:**
- Seller node (BPP) internal security
- Logistics node (LSP) internal security
- ONDC Gateway internal security
- ONDC Registry internal security
- UPI intent flow provider's UPI handling
- GCP shared-responsibility infrastructure
- Physical security of dark stores
- Mobile OS-level CVEs (root / jailbreak detection is in-scope)

**Known Constraints or Limitations:**
- ONDC participant trust is transitive — a compromised seller can return crafted `on_search` payloads that pass signature verification
- Beckn signing protects integrity but does not encrypt payload; intermediaries see order contents
- Registry lookups are cached 1 hour, so key rotation has a propagation delay
- Address autocomplete is fuzzy (uses Google Places) which can return inaccurate buildings
- 5 km radius is enforced server-side at cart time, not at search time
- Cancellation window is 60 seconds after `confirm` (then non-cancellable)
- Idempotency keys are 24-hour TTL (orders older than 24h cannot be retried)

**Development or Operational Considerations:**
- Active ONDC certification cycle; periodic conformance audits
- DPDP Act 2023 scope (consumer PII, address)
- No PCI scope (hosted UPI flow)
- Mobile app weekly releases; backend daily; canary deploys with progressive rollout
- 24x7 ops with separate incident channel for ONDC dispute escalation

**Threat Modeling Focus Areas:**
- Cart / price tampering between `select` and `confirm` calls
- Forged or replayed signed Beckn responses from a compromised seller / LSP
- Address-book IDOR and over-sharing with LSP
- ONDC Registry response substitution leading to acceptance of attacker key
- Idempotency-key abuse causing duplicate order or duplicate dispatch
- Search-cache poisoning across users on the same dark-store geohash
- Webhook spoofing of payment-status callbacks
- Refresh-token theft on rooted devices
- Information disclosure of buyer PII through verbose error responses on `/lookup` failures
- Privilege escalation from buyer to "ops dispute reviewer" via admin endpoint

```xml
</assumptions>
```

---

## How to Use This Example

```bash
paranoid run examples/stride-example-ondc-quick-commerce.md \
  --iterations 5 \
  --diagram examples/stride-ondc-quick-commerce-architecture.mmd \
  --output ondc-buyer-threats.json
```

### Expected Output

The pipeline will generate threats covering all STRIDE categories:

- **Spoofing**: Forged seller `on_search` signatures, registry response substitution, payment webhook forgery
- **Tampering**: Price / quantity tampering between `select` and `confirm`, address tampering before LSP handover
- **Repudiation**: Insufficient signed-payload archive for ONDC disputes, missing immutable log of cart deltas
- **Information Disclosure**: Address book IDOR, error-response PII leakage, search-cache cross-user leakage
- **Denial of Service**: Search-flood across multiple sellers via single user, registry cache invalidation storms
- **Elevation of Privilege**: Buyer-to-ops-reviewer JWT scope confusion, BAP signing key exposure via misconfigured KMS IAM

---

## Notes

- ONDC trust is mediated by signatures; threats focus on what passes signature verification but is still adversarial
- The Buyer App is the integrity boundary — once a payload is signed by us, treat it as committed
- Address minimisation to LSP is a DPDP-aligned focus area
