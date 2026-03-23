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
# Edit test_structured_input.py and uncomment:
# await test_stride_only()

python examples/test_structured_input.py
```

#### Run MAESTRO Example (RAG Chatbot)

```bash
# Edit test_structured_input.py and uncomment:
# await test_stride_maestro_dual()

python examples/test_structured_input.py
```

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
- [CLAUDE.md](../.claude/rules/CLAUDE.md) - Project guidelines
- [RULES.md](../.claude/rules/RULES.md) - Coding conventions
