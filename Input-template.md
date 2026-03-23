# Threat Modeling Templates

---

## STRIDE Templates

### Component Description Template

```xml
<component_description>
```

**Name:** [Name of the component]

**Purpose:** [Brief explanation of what the component does]

**Technology Stack:**
- **Language(s):** [e.g., Python, Node.js]
- **Framework(s):** [e.g., Django, React, Express]
- **Libraries / SDKs:** [e.g., pandas, AWS SDK, Redis]
- **Cloud Infrastructure:** [e.g., Docker, Kubernetes, bare-metal]
- **Cloud Platforms:** [e.g., Azure, AWS, GCP, any managed/unmanaged services in them]

**Interfaces and Protocols:**
- Inbound Interfaces:
  - [e.g., HTTP API - POST /login]
  - [e.g., gRPC call - Authenticate()]
- Outbound Interfaces:
  - [e.g., Calls to external payment service over HTTPS]
  - [e.g., Publishes events to Kafka topic]

**Data Handled:**
- **Sensitive Data Types:** [e.g., PII, credentials, tokens]
- **Storage Mechanisms:** [e.g., PostgreSQL, MongoDB, flat files]

**Trust Level:**
- **Internal/External:** [Is this internal-facing, internet-exposed, etc.]
- **Authentication / Authorization Used:** [e.g., OAuth2, mTLS, JWT, Role-based Access Control]

**Dependencies:**
- [e.g., External APIs, Third-party SDKs, Internal services]

```xml
</component_description>
```

---

### Assumptions Template

```xml
<assumptions>
```

**Security Controls Already in Place:**
- [e.g., All internal services use mTLS]
- [e.g., Web Application Firewall (WAF) protects internet-exposed endpoints]
- [e.g., Database is encrypted at rest with managed KMS]

**Areas Considered In-Scope:**
- [e.g., API Gateway to App Server communication]
- [e.g., User authentication and session management]
- [e.g., Data access control and RBAC enforcement]

**Areas Considered Out-of-Scope:**
- [e.g., Third-party integrations (assumed trusted)]
- [e.g., Underlying IaaS security of cloud provider]
- [e.g., Employee laptops or endpoints]

**Known Constraints or Limitations:**
- [e.g., No runtime protection tools currently deployed]
- [e.g., Uses legacy encryption algorithm due to compliance dependency]
- [e.g., No rate limiting currently enforced]

**Development or Operational Considerations:**
- [e.g., Service is under active development — threat mitigations must not hinder rapid iteration]
- [e.g., Runs in multi-tenant environment]

**Threat Modeling Focus Areas:**
- [e.g., Data integrity between services]
- [e.g., Insider misuse of elevated privileges]
- [e.g., Availability of background processing jobs]

```xml
</assumptions>
```

---

## MAESTRO Templates

> MAESTRO (Mission, Assets, Actors, Exposure, Security Controls, Threat Scenarios, Risk & Residual) is a threat modeling framework oriented around AI/ML systems and agentic pipelines. It structures analysis around the operational mission of a system, the agents and assets involved, and the unique risks introduced by autonomy, model behavior, and multi-agent trust chains.

---

### Component Description Template

```xml
<maestro_component_description>
```

**Name:** [Name of the AI component, agent, or pipeline stage]

**Mission Alignment:**
- **Operational Mission:** [What business or operational goal does this component serve?]
- **Autonomy Level:** [e.g., Fully automated, Human-in-the-loop, Human-on-the-loop]
- **Decision Authority:** [What decisions can this component make without human approval?]

**Agent / Model Profile:**
- **Model(s) Used:** [e.g., GPT-4o, Claude 3, fine-tuned BERT, custom classifier]
- **Hosting:** [e.g., Self-hosted, API-based (OpenAI, Anthropic), on-device]
- **Modalities:** [e.g., Text, Code, Vision, Audio, Tool use]
- **Tool Access:** [e.g., Web search, code execution, database read/write, file system, external APIs]
- **Memory / State:** [e.g., Stateless per request, vector store, session memory, long-term user profile]

**Technology Stack:**
- **Orchestration Framework:** [e.g., LangChain, AutoGen, CrewAI, custom]
- **Language(s) / Runtime:** [e.g., Python 3.11, Node.js]
- **Infrastructure:** [e.g., Kubernetes, serverless, edge deployment]
- **Supporting Services:** [e.g., Vector DB (Pinecone), message queue (Kafka), cache (Redis)]

**Assets:**
- **Data Assets:** [e.g., Training data, RAG corpora, user conversation history, credentials in context]
- **Model Assets:** [e.g., Model weights, system prompts, fine-tuning datasets]
- **Operational Assets:** [e.g., Tool integrations, API keys, downstream service access]

**Actors:**
- **Human Principals:** [e.g., End users, operators, admins, developers]
- **AI Agents / Sub-agents:** [e.g., Other agents in the pipeline, spawned sub-agents]
- **External Systems:** [e.g., APIs called by the agent, data sources ingested at runtime]

**Interfaces and Protocols:**
- Inbound:
  - [e.g., User prompt over HTTPS REST]
  - [e.g., Agent-to-agent messages via message bus]
  - [e.g., Retrieved documents from vector store]
- Outbound:
  - [e.g., Tool calls to external APIs]
  - [e.g., Code execution in sandbox]
  - [e.g., Writes to database or file system]

**Trust Boundaries:**
- **Trust Level:** [e.g., Internet-exposed, internal-only, multi-tenant]
- **Agent Trust Chain:** [Describe trust relationships between orchestrator and sub-agents]
- **Human Override Mechanism:** [e.g., Approval gate, kill switch, audit log review]
- **Authentication / Authorization:** [e.g., OAuth2 for tool calls, RBAC on data access, JWT for user sessions]

**Dependencies:**
- [e.g., External LLM provider API, internal knowledge base, downstream automation services]

```xml
</maestro_component_description>
```

---

### Assumptions Template

```xml
<maestro_assumptions>
```

**Mission Constraints:**
- [e.g., System must not take irreversible actions without human approval]
- [e.g., Agent output is always reviewed before being surfaced to end users]
- [e.g., Component operates within a regulated environment — outputs may be audited]

**Security Controls Already in Place:**
- [e.g., System prompt is stored server-side and never exposed to users]
- [e.g., Tool calls are sandboxed and cannot access the host filesystem]
- [e.g., All LLM API traffic is routed through an enterprise proxy with logging]
- [e.g., Output is filtered through a content safety classifier before delivery]

**AI-Specific Controls in Place:**
- [e.g., Prompt injection detection layer is active on all user inputs]
- [e.g., Agent is restricted to a pre-approved tool allowlist]
- [e.g., Token budget enforced to prevent runaway agent loops]
- [e.g., Model output is validated against a JSON schema before downstream processing]

**Areas Considered In-Scope:**
- [e.g., Agent prompt construction and injection surface]
- [e.g., Tool call authorization and parameter validation]
- [e.g., Data retrieved from RAG pipeline and its influence on model output]
- [e.g., Multi-agent trust and message integrity between orchestrator and sub-agents]

**Areas Considered Out-of-Scope:**
- [e.g., LLM provider's internal infrastructure and model training security]
- [e.g., Security of underlying cloud IaaS]
- [e.g., Adversarial ML attacks against model weights (no access to weights)]

**Known Constraints or Limitations:**
- [e.g., No runtime anomaly detection on agent tool call sequences]
- [e.g., Agent has broad read access to internal knowledge base — no row-level access control]
- [e.g., No formal input/output audit trail currently implemented]
- [e.g., Agent operates without a human-in-the-loop in production]

**Agentic / AI-Specific Considerations:**
- [e.g., System prompt confidentiality is a key concern — exfiltration via indirect injection is in scope]
- [e.g., Agent can spawn sub-agents — sub-agent behavior is not independently audited]
- [e.g., RAG retrieval sources include user-supplied documents — assumed potentially adversarial]
- [e.g., Agent is permitted to write to external systems — scope of write access must be threat-modeled]
- [e.g., Model version may change without re-evaluation of threat model]

**Development or Operational Considerations:**
- [e.g., Pipeline is under active development — new tools and integrations are added frequently]
- [e.g., Runs in a multi-tenant environment — tenant isolation is a key concern]
- [e.g., Agent personas or system prompt variants are used per deployment — variant management is in scope]

**Threat Modeling Focus Areas:**
- [e.g., Prompt injection via user input or retrieved documents]
- [e.g., Unauthorized tool invocation or parameter manipulation]
- [e.g., Data exfiltration through model output or tool calls]
- [e.g., Agent goal hijacking through adversarial context injection]
- [e.g., Trust escalation between sub-agents in an orchestrated pipeline]
- [e.g., Availability and integrity of the RAG knowledge base]

```xml
</maestro_assumptions>
```