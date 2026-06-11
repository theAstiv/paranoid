# Threat Modeling Examples

This directory contains comprehensive examples demonstrating the structured XML-tagged input format for threat modeling with **STRIDE** and **MAESTRO** frameworks.

## Examples

### 1. STRIDE Example: E-commerce API Gateway
**File:** [stride-example-api-gateway.md](stride-example-api-gateway.md)

A traditional microservices API Gateway without AI/ML components. Demonstrates:
- ✅ STRIDE component description template
- ✅ STRIDE assumptions template
- ✅ Single framework execution (`has_ai_components=False`)
- ✅ Traditional security threat coverage (spoofing, tampering, etc.)

**Use Case:** Traditional web applications, microservices, APIs, databases, infrastructure

---

### 2. MAESTRO Example: RAG-Powered Customer Support Chatbot
**File:** [maestro-example-rag-chatbot.md](maestro-example-rag-chatbot.md)

An AI-powered customer support system with LLM, RAG pipeline, and tool use. Demonstrates:
- ✅ MAESTRO component description template
- ✅ MAESTRO assumptions template
- ✅ Dual framework execution (`has_ai_components=True`)
- ✅ Combined STRIDE + MAESTRO threat coverage
- ✅ AI/ML-specific threat modeling (prompt injection, RAG poisoning, etc.)

**Use Case:** LLM-powered applications, RAG systems, AI agents, ML pipelines, chatbots

---

### 3. STRIDE Example: UPI P2P + Bill Payments App
**File:** [stride-example-upi-payments.md](stride-example-upi-payments.md)

A consumer UPI payments TPAP operating under RBI / NPCI rails. Demonstrates:
- ✅ India-specific fintech architecture (PSP SDK, VPA, BBPS)
- ✅ RBI/NPCI regulatory scope (DPDP Act, PCI-DSS)
- ✅ Detailed trust boundaries (device binding, mTLS, KMS encryption)

**Use Case:** UPI payment apps, fintech TPAPs, bill payment platforms

---

### 4. STRIDE Example: ONDC Quick Commerce Platform
**File:** [stride-example-ondc-quick-commerce.md](stride-example-ondc-quick-commerce.md)

A seller-side quick commerce platform on the ONDC Beckn network. Demonstrates:
- ✅ ONDC/Beckn protocol security (message signing, registry lookup)
- ✅ Hyperlocal delivery and dark-store logistics
- ✅ Multi-protocol integration (Beckn, REST, WebSocket)

**Use Case:** ONDC buyer/seller apps, quick commerce, Beckn network participants

---

### 5. MAESTRO Example: AI Loan Origination Agent
**File:** [maestro-example-loan-agent.md](maestro-example-loan-agent.md)

A conversational AI loan agent with LLM tool-use, Aadhaar eKYC, RBI Account Aggregator, and CIBIL integration. Demonstrates:
- ✅ Combined STRIDE + MAESTRO analysis
- ✅ Agentic AI threat modeling (prompt injection, tool-argument tampering, reasoning bypass)
- ✅ RBI Digital Lending Guidelines compliance scope

**Use Case:** AI agents with tool use, LLM-powered financial services, regulated AI systems

---

### 6. STRIDE Example: OWASP Juice Shop (Code-as-Input)
**File:** [stride-example-juice-shop.md](stride-example-juice-shop.md)

The OWASP Juice Shop intentionally vulnerable e-commerce app. Designed for `--code` flag demos with the [juice-shop/juice-shop](https://github.com/juice-shop/juice-shop) repository.
- ✅ Code-as-input workflow (`--code` flag)
- ✅ OWASP Top 10 coverage (SQLi, XSS, IDOR, XXE, broken auth)
- ✅ Every security audience already knows this app

**Use Case:** Security training demos, code-backed threat modeling, OWASP vulnerability discovery

---

### 7. STRIDE Example: Razorpay Payment Integration (Code-as-Input)
**File:** [stride-example-razorpay-integration.md](stride-example-razorpay-integration.md)

A merchant payment backend integrating with Razorpay. Designed for `--code` flag demos with the [razorpay/razorpay-python](https://github.com/razorpay/razorpay-python) SDK.
- ✅ Code-as-input workflow (`--code` flag)
- ✅ Payment gateway security (HMAC webhook verification, signature validation)
- ✅ Multi-tenant SaaS payment isolation

**Use Case:** Payment gateway integrations, webhook security, fintech backends

---

### 8. STRIDE Example: Frappe Lending (Code-as-Input)
**File:** [stride-example-frappe-lending.md](stride-example-frappe-lending.md)

A full-lifecycle loan management system on the Frappe framework. Designed for `--code` flag demos with the [frappe/lending](https://github.com/frappe/lending) repository.
- ✅ Code-as-input workflow (`--code` flag)
- ✅ Financial workflow security (loan approval bypass, interest manipulation, NPA suppression)
- ✅ RBI NBFC regulatory compliance scope

**Use Case:** Loan management systems, ERP lending modules, Frappe/ERPNext apps

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -e .
```

### 2. Set API Key

```bash
export ANTHROPIC_API_KEY="your-key-here"
```

### 3. Run Examples

#### Test Input Parser (No API Calls)

```bash
python examples/test_structured_input.py
```

#### Run STRIDE Example (API Gateway)

```bash
paranoid run examples/stride-example-api-gateway.md
```

#### Run MAESTRO Example (RAG Chatbot)

```bash
paranoid run examples/maestro-example-rag-chatbot.md --maestro
```

#### Run Examples with Architecture Diagrams (`--diagram`)

Combine text descriptions with visual architecture diagrams for richer threat coverage:

```bash
# STRIDE Example with diagram
paranoid run examples/stride-example-api-gateway.md \
  --diagram examples/stride-api-gateway-architecture.mmd

# MAESTRO Example with diagram
paranoid run examples/maestro-example-rag-chatbot.md \
  --maestro \
  --diagram examples/maestro-rag-chatbot-architecture.mmd
```

**Available diagram files:**
- [`stride-api-gateway-architecture.mmd`](stride-api-gateway-architecture.mmd) - E-commerce API Gateway architecture
- [`maestro-rag-chatbot-architecture.mmd`](maestro-rag-chatbot-architecture.mmd) - RAG chatbot AI pipeline
- [`stride-upi-payments-architecture.mmd`](stride-upi-payments-architecture.mmd) - UPI TPAP architecture
- [`stride-ondc-quick-commerce-architecture.mmd`](stride-ondc-quick-commerce-architecture.mmd) - ONDC seller platform architecture
- [`maestro-loan-agent-architecture.mmd`](maestro-loan-agent-architecture.mmd) - AI loan agent pipeline

**Supported formats:**
- `.mmd` (Mermaid) - Works with all providers (Anthropic, OpenAI, Ollama)
- `.png`, `.jpg` - Vision API (Anthropic all models, OpenAI gpt-4o/gpt-4o-mini only)

#### Run Examples with Code Context (`--code`)

Point Paranoid at a cloned repository for code-backed threat discovery:

```bash
# Juice Shop — discover OWASP Top 10 from source
git clone --depth 1 https://github.com/juice-shop/juice-shop.git /tmp/juice-shop
paranoid run examples/stride-example-juice-shop.md \
  --code /tmp/juice-shop --iterations 5

# Razorpay SDK — analyse webhook/signature verification
git clone --depth 1 https://github.com/razorpay/razorpay-python.git /tmp/razorpay-python
paranoid run examples/stride-example-razorpay-integration.md \
  --code /tmp/razorpay-python --iterations 5

# Frappe Lending — inspect loan workflows and permission model
git clone --depth 1 https://github.com/frappe/lending.git /tmp/frappe-lending
paranoid run examples/stride-example-frappe-lending.md \
  --code /tmp/frappe-lending --iterations 5
```

Or add code sources via the web UI (Settings → Code Sources → Add source) and select them in the wizard.

---

## Template Format

### Component Description

Use XML tags to structure your component description:

**STRIDE Template:**
```xml
<component_description>
**Name:** [Component name]
**Purpose:** [What it does]
**Technology Stack:**
- **Language(s):** [Programming languages]
- **Framework(s):** [Frameworks]
...
</component_description>
```

**MAESTRO Template:**
```xml
<maestro_component_description>
**Name:** [AI component name]
**Mission Alignment:**
- **Operational Mission:** [Business goal]
- **Autonomy Level:** [Human-in-the-loop, etc.]
...
</maestro_component_description>
```

### Assumptions

**STRIDE Assumptions:**
```xml
<assumptions>
**Security Controls Already in Place:**
- [Existing control 1]
- [Existing control 2]

**Areas Considered In-Scope:**
- [In-scope area 1]
- [In-scope area 2]

**Areas Considered Out-of-Scope:**
- [Out-of-scope area 1]

**Threat Modeling Focus Areas:**
- [Focus area 1]
- [Focus area 2]
</assumptions>
```

**MAESTRO Assumptions:**
```xml
<maestro_assumptions>
**Mission Constraints:**
- [Constraint 1]

**AI-Specific Controls in Place:**
- [AI control 1]
- [AI control 2]

**Agentic / AI-Specific Considerations:**
- [AI consideration 1]
- [AI consideration 2]

**Threat Modeling Focus Areas:**
- [AI-specific focus 1]
- [AI-specific focus 2]
</maestro_assumptions>
```

---

## Expected Outputs

### STRIDE-Only Example
- **~15-25 threats** across all STRIDE categories
- Severity distribution: Critical (1-2), High (3-5), Medium (5-8), Low (2-3)
- Focus on traditional security: authentication, authorization, injection, DoS

### STRIDE+MAESTRO Example
- **~30-50 threats total**
  - ~15-25 STRIDE threats (traditional security)
  - ~15-25 MAESTRO threats (AI/ML-specific)
- STRIDE coverage: spoofing, tampering, repudiation, information disclosure, DoS, privilege escalation
- MAESTRO coverage: prompt injection, RAG poisoning, model extraction, cost exhaustion, hallucinations, etc.

---

## Key Features Demonstrated

### 1. Structured Input Parsing
✅ XML-tagged component descriptions
✅ Structured assumptions with sections
✅ Automatic detection and parsing
✅ Backward compatibility with plain text

### 2. Assumption Enforcement
✅ Gap analysis respects in-scope boundaries
✅ Out-of-scope areas explicitly excluded
✅ Focus areas prioritized in threat generation
✅ Security controls prevent redundant threats

### 3. Dual Framework Support
✅ Single flag (`has_ai_components=True`) enables MAESTRO
✅ Both frameworks run in parallel
✅ Merged threat catalog (STRIDE + MAESTRO)
✅ Comprehensive coverage for AI/ML systems

---

## Tips for Creating Your Own Examples

### 1. Be Specific in Component Descriptions
❌ **Bad:** "Uses a database"
✅ **Good:** "PostgreSQL 14.2 with row-level security, encrypted at rest via AWS KMS"

### 2. Define Clear Scope Boundaries
- **In-Scope:** Areas you want threats for
- **Out-of-Scope:** Areas you explicitly DON'T want threats for (underlying IaaS, third-party services, etc.)

### 3. List Existing Security Controls
This prevents the model from suggesting threats that are already mitigated.

❌ **Without controls:** Model suggests "Add TLS encryption"
✅ **With controls:** Model knows TLS is already in place, suggests higher-value threats

### 4. Specify Focus Areas
Guide the model to prioritize specific attack vectors:
- "Authentication bypass vectors"
- "Data exfiltration through model outputs"
- "Cost exhaustion attacks"

### 5. For AI/ML Systems: Enable Dual Framework
Always use `has_ai_components=True` for systems with:
- LLMs (GPT-4, Claude, Llama, etc.)
- RAG pipelines
- ML models
- AI agents with tool use
- Vector databases for embeddings

---

## Troubleshooting

### Parser Not Detecting Structured Input
- ✅ Ensure XML tags are **exactly** as shown: `<component_description>` or `<maestro_component_description>`
- ✅ Check for typos in tag names
- ✅ Tags must be on their own lines

### Gap Analysis Not Respecting Assumptions
- ✅ Verify assumptions are inside `<assumptions>` or `<maestro_assumptions>` tags
- ✅ Check section headers match exactly: `**Areas Considered Out-of-Scope:**`
- ✅ Use bullet points (`- `) for list items

### MAESTRO Not Triggered
- ✅ Set `has_ai_components=True` in pipeline config
- ✅ Use `framework=Framework.STRIDE` as primary (MAESTRO runs alongside automatically)
- ✅ Verify component description uses `<maestro_component_description>` tags

---

## Contributing Examples

Have a great threat modeling example? Submit a PR with:
1. A new markdown file in this directory
2. Comprehensive component description
3. Detailed assumptions
4. Real-world use case
5. Expected threat count/categories

---

## Related Documentation

- [Input-template.md](../Input-template.md) - Template reference
- [README.md](../README.md) - Project overview and quick start
