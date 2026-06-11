# STRIDE Example: Frappe Lending — Loan Management System

This example demonstrates threat modeling for a loan management system built on the Frappe framework. Designed for use with the `--code` flag pointing at the [frappe/lending](https://github.com/frappe/lending) repository, so Paranoid can analyse loan origination workflows, interest calculations, repayment schedules, NPA classification logic, and access control patterns directly from source code.

---

## Component Description

```xml
<component_description>
```

**Name:** Frappe Lending — Loan Origination, Disbursement, and Recovery Platform

**Purpose:** Full-lifecycle loan management system for NBFCs, microfinance institutions, and lending DSAs operating under RBI regulations. Handles loan product configuration, applicant onboarding, credit appraisal, loan disbursement, EMI repayment tracking, interest accrual, penal charge computation, NPA (Non-Performing Asset) classification, write-off, and recovery. Built as a Frappe app extending ERPNext's accounting module for GL integration.

**Technology Stack:**
- **Language(s):** Python 3.11+ (server-side business logic, DocType controllers), JavaScript (client-side form scripts, list views), Jinja2 (print format templates, email templates)
- **Framework(s):** Frappe Framework 15.x (full-stack web framework — ORM, REST API, WebSocket, permissions, workflow engine, background jobs), ERPNext (accounting integration — General Ledger, Journal Entry, Payment Entry)
- **Libraries / SDKs:** MariaDB (via Frappe ORM), Redis (caching, Frappe realtime, background job queue via RQ), wkhtmltopdf (PDF generation for loan agreements, demand notices, NOC letters), frappe.utils for date arithmetic, interest computation
- **Database:** MariaDB 10.6+ (all DocTypes stored as database tables with Frappe's standard metadata columns)
- **Infrastructure:** Self-hosted or Frappe Cloud; Nginx reverse proxy, Gunicorn workers, Redis queues, MariaDB

**Interfaces and Protocols:**
- Inbound Interfaces:
  - HTTPS REST API — Frappe standard CRUD (`/api/resource/Loan Application`, `/api/resource/Loan`, `/api/resource/Loan Disbursement`, `/api/resource/Loan Repayment`)
  - HTTPS REST API — Whitelisted methods (`/api/method/lending.loan_management.doctype.loan.loan.make_repayment_entry`, `/api/method/lending.loan_management.doctype.loan_disbursement.loan_disbursement.get_disbursal_amount`)
  - HTTPS — Frappe Desk UI (full CRUD, workflow transitions, reports, dashboards)
  - HTTPS — Frappe Portal (borrower self-service: view loan status, download statements)
  - WebSocket — Frappe Realtime (background job progress, document update notifications)
- Outbound Interfaces:
  - HTTPS to payment gateway (for auto-debit / eNACH mandate processing, via ERPNext Payment Gateway integration)
  - SMTP for EMI reminders, overdue notices, and disbursement confirmations
  - PDF generation for loan agreements, demand notices, NOC (No Objection Certificate)
  - GL postings to ERPNext accounting (Journal Entry for interest accrual, disbursement, repayment, write-off)

**Data Handled:**
- **Sensitive Data Types:** Applicant PAN, Aadhaar number (KYC), bank account number + IFSC (disbursement and repayment), income documents, credit bureau report references, loan amount and outstanding balance, interest rates (fixed and floating), repayment schedule with EMI breakdowns, overdue amounts and penal interest, NPA classification status, guarantor details, collateral valuations, digital signatures on loan agreements
- **Storage Mechanisms:** MariaDB (all DocTypes — Loan Application, Loan, Loan Disbursement, Loan Repayment, Loan Interest Accrual, Loan Write Off, Loan Security Pledge), filesystem for uploaded KYC documents and signed agreements (`/private/files/`), Redis for session cache and background job state

**Trust Level:**
- **Internal/External:** Frappe Desk (internal staff — loan officers, credit managers, recovery agents, finance team, admins); Frappe Portal (external — borrowers with limited self-service); API (internal microservices and payment gateway webhooks)
- **Authentication / Authorization Used:** Frappe built-in auth (email + password, optional TOTP MFA), session-based (cookie + CSRF token), Frappe's role-based permission system (DocType-level CRUD + field-level read/write per role), workflow state transitions gated by role (e.g., only Credit Manager can approve, only Finance can disburse), API key + secret for server-to-server, OAuth2 bearer tokens for portal

**Dependencies:**
- Frappe Framework (core — ORM, permissions, workflow, background jobs)
- ERPNext (accounting — GL, Journal Entry, Payment Entry, Company)
- MariaDB (data persistence)
- Redis (cache, realtime, background queue)
- Nginx (reverse proxy, TLS termination)
- wkhtmltopdf (PDF generation)
- Payment gateway (eNACH / auto-debit integration)

```xml
</component_description>
```

---

## Assumptions

```xml
<assumptions>
```

**Security Controls Already in Place:**
- TLS 1.2+ via Nginx for all client traffic
- Frappe CSRF token on all state-changing requests from Desk and Portal
- Role-based access control (RBAC) on every DocType — Loan Officer, Credit Manager, Disbursement Officer, Recovery Agent, Finance Manager, System Manager
- Workflow state transitions enforce role gates (e.g., Loan Application: Draft → Submitted [Loan Officer] → Approved [Credit Manager] → Disbursed [Finance])
- Field-level permissions: PAN and Aadhaar fields readable only by Credit Manager and above
- Frappe's ORM generates parameterised queries (no raw SQL in application code by default)
- Private file access (`/private/files/`) requires authenticated session with read permission on the linked DocType
- Background jobs (interest accrual, NPA classification) run under a system user with audit trail
- Frappe standard audit log: all DocType create/update/delete operations logged with user, timestamp, and field-level diff
- Password policy: minimum 8 characters, configurable complexity, bcrypt hashing
- Session timeout: configurable idle timeout (default 6 hours for Desk, 1 hour for Portal)

**Areas Considered In-Scope:**
- Privilege escalation within Frappe RBAC: Loan Officer approving their own loan, Recovery Agent modifying loan terms
- Workflow bypass: skipping approval steps via direct API calls or DocType submission
- Interest calculation tampering: modifying rate or accrual schedule after loan approval
- Disbursement fraud: changing beneficiary bank account between approval and disbursement
- Repayment manipulation: backdating repayment entries, inflating amounts, misallocating between principal and interest
- NPA classification bypass: suppressing overdue flags to avoid provisioning requirements
- Write-off abuse: writing off recoverable loans prematurely, re-opening written-off loans
- KYC document access: unauthorised download of PAN, Aadhaar, income docs via file URL guessing
- Portal exposure: borrower accessing other borrowers' loan details via IDOR
- Collateral valuation tampering: inflating pledged asset value to approve higher loan amounts
- GL posting integrity: Journal Entry amounts mismatching loan ledger (reconciliation gaps)
- Background job tampering: modifying interest accrual batch parameters, skipping penal charge computation
- Print format injection: Jinja2 template injection in loan agreement or demand notice templates
- API endpoint abuse: bulk data exfiltration via Frappe's `/api/resource` list endpoints with crafted filters

**Areas Considered Out-of-Scope:**
- Frappe Framework core vulnerabilities (assumed patched and up-to-date)
- MariaDB, Redis, Nginx infrastructure-level security
- Operating system and container runtime
- Payment gateway internals (eNACH mandates, bank APIs)
- Credit bureau integration internals (CIBIL, Experian, CRIF)
- Physical security of branch offices

**Known Constraints or Limitations:**
- Frappe's `/api/resource` endpoint exposes list views for any DocType the user has read permission on — filter injection can widen result sets
- File URL paths follow a predictable pattern (`/private/files/{hash}_{filename}`) — access control is enforced but URL is guessable
- Workflow transitions can be bypassed by users with `Submit` permission if the workflow is not strictly configured
- Frappe's `frappe.get_doc` and `frappe.get_list` respect permissions by default, but `frappe.db.sql` (raw SQL) does not — any raw query in custom code is a privilege escalation risk
- Interest accrual runs as a scheduled job under Administrator — errors in the job affect all active loans
- Print format templates use Jinja2 with access to Frappe's Python API — unsanitised user input in template context is an SSTI risk
- Loan amendments (rate changes, tenure extension) create new versions but the old version's GL entries must be reversed — incomplete reversal creates accounting discrepancies
- Multi-company setup: loan accounts must be isolated per Company; shared cost centres can leak financial data across entities

**Development or Operational Considerations:**
- RBI NBFC regulations: Fair Practices Code, NPA classification norms (90-day overdue = Sub-standard), provisioning requirements, KYC/AML compliance
- Indian Accounting Standards (Ind AS 109): Expected Credit Loss (ECL) provisioning based on NPA stage
- DPDP Act 2023: borrower PII must be deletable on request (except where RBI retention mandates apply)
- Loan officer incentive structures may create pressure to approve borderline applications — system controls must enforce policy regardless of user intent
- Frappe's permission system is powerful but misconfiguration is common — a single missing role restriction on a DocType can expose all records
- Bench updates (Frappe/ERPNext upgrades) can reset custom permissions if not carefully managed

**Threat Modeling Focus Areas:**
- Workflow bypass: direct submission of Loan Disbursement without prior Loan Application approval
- Beneficiary account tampering: changing bank account + IFSC between loan approval and disbursement DocType creation
- Interest rate manipulation: modifying `rate_of_interest` field on Loan DocType after credit committee approval
- Repayment misallocation: applying a repayment to interest instead of overdue principal to avoid NPA classification
- NPA classification suppression: backdating a repayment entry to bring a loan within the 90-day window
- KYC document exfiltration: accessing `/private/files/` via predictable URLs or bulk download via API
- Portal IDOR: borrower accessing another borrower's loan statement or repayment schedule
- Collateral valuation inflation: Credit Manager modifying Loan Security Pledge valuation without independent appraisal
- GL reconciliation gap: disbursement GL entry posted but loan status not updated (or vice versa)
- Jinja2 SSTI in print format templates: attacker-controlled input rendered in loan agreement PDF
- Frappe API bulk exfiltration: crafted `/api/resource/Loan?filters=[]&limit_page_length=0` to dump all loan records
- Background job manipulation: modifying the interest accrual scheduled task parameters to skip penal charges

```xml
</assumptions>
```

---

## How to Use This Example

### With Code Context (Recommended)

```bash
# First, add the Frappe Lending repo as a code source in the UI, or clone locally:
git clone --depth 1 https://github.com/frappe/lending.git /tmp/frappe-lending

paranoid run examples/stride-example-frappe-lending.md \
  --code /tmp/frappe-lending \
  --iterations 5 \
  --output frappe-lending-threats.json
```

### Without Code Context

```bash
paranoid run examples/stride-example-frappe-lending.md \
  --iterations 3 \
  --output frappe-lending-threats.json
```

### Expected Output

The pipeline will generate threats covering all STRIDE categories, with code-backed evidence when `--code` is used:

- **Spoofing**: Portal session hijacking, API key theft for server-to-server calls, loan officer impersonation via shared credentials
- **Tampering**: Interest rate modification post-approval, beneficiary account swap before disbursement, repayment backdating to avoid NPA, collateral valuation inflation, GL entry amount mismatch
- **Repudiation**: Workflow approval without audit trail (direct API submission), write-off without documented recovery attempts, interest waiver without committee approval record
- **Information Disclosure**: KYC document exfiltration via file URL, bulk loan data dump via API, portal IDOR exposing other borrowers' details, credit bureau report leakage in error responses
- **Denial of Service**: Interest accrual batch failure affecting all active loans, bulk API calls exhausting Gunicorn workers, Redis queue poisoning stalling background jobs
- **Elevation of Privilege**: Loan Officer self-approving via workflow bypass, Recovery Agent modifying loan terms, Portal user escalating to Desk access, raw SQL in custom code bypassing Frappe permissions

---

## Notes

- Frappe Lending is a real production loan management system used by Indian NBFCs — the threat model maps to actual regulatory requirements (RBI NBFC norms, Ind AS 109, DPDP Act)
- The codebase has rich business logic (interest accrual, NPA classification, write-off workflows) that Paranoid's code context can directly inspect
- Frappe's permission system is the primary security boundary — misconfiguration is the most common real-world vulnerability in Frappe apps
