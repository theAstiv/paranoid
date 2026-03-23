# Testing Guide for Paranoid Threat Modeling

This guide will help you test the threat modeling pipeline before continuing development.

## Quick Start

### 1. Set Up Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and add your API key for your preferred provider:

```bash
# For Anthropic (Claude) - Recommended
ANTHROPIC_API_KEY=sk-ant-api03-xxx

# OR for OpenAI
OPENAI_API_KEY=sk-xxx

# OR for Ollama (local, no API key needed)
OLLAMA_BASE_URL=http://localhost:11434
DEFAULT_PROVIDER=ollama
```

### 2. Install Dependencies

Make sure all Python dependencies are installed:

```bash
pip install -e .
```

### 3. Run the Test Pipeline

Execute the test script:

```bash
python test_pipeline.py
```

## What the Test Does

The test script runs a complete threat modeling pipeline on a sample web application:

- **System**: Document sharing web application with React frontend, Node.js backend, PostgreSQL database
- **Framework**: STRIDE threat modeling
- **Iterations**: 3 (configurable in .env)

### Pipeline Steps Tested

1. **Summarize** - Generates system summary
2. **Extract Assets** - Identifies assets and entities
3. **Extract Flows** - Maps data flows and trust boundaries
4. **Generate Threats** (Iteration 1) - Initial threat catalog
5. **Gap Analysis** (Iteration 1) - Identifies coverage gaps
6. **Generate Threats** (Iteration 2) - Improved threats based on gaps
7. **Gap Analysis** (Iteration 2) - Re-evaluates coverage
8. **Generate Threats** (Iteration 3) - Final threat refinement
9. **Complete** - Pipeline summary

### Expected Output

```
================================================================================
PARANOID THREAT MODELING PIPELINE - TEST
================================================================================

✓ Configuration loaded
  Provider: anthropic
  Model: claude-sonnet-4-20250514
  Max Iterations: 3

✓ Provider initialized: anthropic

Test Scenario: Document Sharing Web Application
...

================================================================================
STARTING PIPELINE EXECUTION
================================================================================

▶ summarize: Generating system summary...
✓ summarize: Summary generated: 156 chars
    Summary: A cloud-based document sharing system with React frontend, Node.js API...

▶ extract_assets: Identifying assets and entities...
✓ extract_assets: Identified 8 assets/entities
    Assets: 8

▶ extract_flows: Extracting data flows and trust boundaries...
✓ extract_flows: Identified 12 flows, 5 boundaries
    Flows: 12, Boundaries: 5

▶ generate_threats [Iteration 1]: Generating threats...
✓ generate_threats [Iteration 1]: Generated 10 threats
    Threats: 10

▶ gap_analysis [Iteration 1]: Analyzing threat coverage gaps...
✓ gap_analysis [Iteration 1]: Gap identified: Missing threats for...
    Decision: CONTINUE - Gap: Missing threats for...

▶ generate_threats [Iteration 2]: Generating threats...
✓ generate_threats [Iteration 2]: Generated 12 threats
    Threats: 12

...

================================================================================
PIPELINE COMPLETE
================================================================================
  Iterations: 3
  Total Threats: 15
  Duration: 45.23s
  Stop Reason: max_iterations
================================================================================

✓ Test completed successfully!
```

## Troubleshooting

### Import Errors

If you see import errors, make sure you're running from the project root:

```bash
cd c:\Users\Lenovo\Documents\github\paranoid
python test_pipeline.py
```

### API Key Errors

If you see authentication errors:

1. Check that your `.env` file exists and has the correct API key
2. Verify the API key is valid and has not expired
3. For Anthropic, ensure your key starts with `sk-ant-api03-`
4. For OpenAI, ensure your key starts with `sk-`

### Provider Errors

If you see provider initialization errors:

- **Anthropic**: Make sure you have the `anthropic` package installed
- **OpenAI**: Make sure you have the `openai` package installed
- **Ollama**: Make sure Ollama is running locally (`ollama serve`)

### Timeout Errors

If the pipeline times out:

1. Increase the timeout in `backend/pipeline/runner.py` (default 30 minutes)
2. Reduce iteration count in `.env` (try `DEFAULT_ITERATIONS=1`)
3. Use a faster model (e.g., `claude-haiku-4-20250514` instead of opus)

## Testing Different Scenarios

### Test with MAESTRO (ML/AI Framework)

Edit `test_pipeline.py` line 115:

```python
framework = Framework.MAESTRO  # Changed from STRIDE
```

Then update the test description to an ML/AI system:

```python
test_description = """
A machine learning system for fraud detection...
"""
```

### Test with Custom Iterations

Edit `.env`:

```bash
DEFAULT_ITERATIONS=5  # Increase for more thorough analysis
```

### Test with Architecture Diagram

Update `test_pipeline.py` to include a diagram:

```python
architecture_diagram = """
[Diagram as text or base64 encoded image]
"""
```

## Next Steps After Successful Test

Once the test passes:

1. **Review Output**: Examine the generated threats, assets, and flows
2. **Test Edge Cases**: Try with minimal descriptions, complex systems
3. **Performance Testing**: Test with different iteration counts (1-15)
4. **Framework Comparison**: Run same system through STRIDE and MAESTRO
5. **Continue Development**: Proceed with Phase 7 (Rule Engine)

## Test Results Checklist

- [ ] Pipeline executes without errors
- [ ] All steps complete successfully
- [ ] Threats are generated with proper DREAD scores
- [ ] Iteration loop works correctly
- [ ] Gap analysis provides meaningful feedback
- [ ] SSE events are emitted correctly
- [ ] Total execution time is reasonable (<5 min for 3 iterations)

## Known Limitations (Current Phase)

Since we're in Phase 6 testing:

- ❌ **No RAG retrieval** - Will be added in Phase 6.9
- ❌ **No rule engine fallback** - Will be added in Phase 7
- ❌ **No database persistence** - Will be added in Phase 9
- ❌ **No attack trees/test cases** - Post-approval features
- ❌ **No UI** - Will be added in Phase 10

What **is** working:

- ✅ Complete STRIDE + MAESTRO pipeline
- ✅ Iteration logic with gap analysis
- ✅ All 8 pipeline nodes
- ✅ SSE event streaming
- ✅ Provider abstraction (Anthropic/OpenAI/Ollama)
- ✅ Structured output via Pydantic
- ✅ Prompt templates with DREAD scoring

## Need Help?

If you encounter issues:

1. Check the error message carefully
2. Review the traceback for clues
3. Verify your .env configuration
4. Try with a simpler test case first
5. Check provider API status pages

---

# Testing Structured XML-Tagged Input Templates

## New Feature: Structured Input Parser

The pipeline now supports structured XML-tagged input templates for both STRIDE and MAESTRO frameworks. This provides better context to the LLM and ensures assumptions are respected during gap analysis.

## Quick Validation Test (No API Key Required)

Run the input parser validation test to verify structured input parsing:

```bash
python examples/test_structured_input.py
```

**Expected Output:**
```
================================================================================
TEST 3: Input Parser Validation
================================================================================

Testing STRIDE example parsing...
  Detected format: stride_structured
  [OK] Component name: E-commerce API Gateway
  [OK] Technology stack sections: 5
  [OK] Dependencies: 8
  [OK] Security controls: 7
  [OK] In-scope items: 8
  [OK] Out-of-scope items: 6
  [OK] Focus areas: 7

Testing MAESTRO example parsing...
  Detected format: maestro_structured
  [OK] Component name: Intelligent Customer Support Agent with RAG
  [OK] Mission alignment fields: 3
  [OK] Agent profile sections: 5
  [OK] Assets sections: 3
```

## Example Templates

Two comprehensive examples are provided in `examples/`:

### 1. STRIDE Example (API Gateway)
- **File:** `examples/stride-example-api-gateway.md`
- **Framework:** STRIDE only
- **Use Case:** Traditional microservices, APIs, databases
- **Expected Threats:** ~15-25 STRIDE threats

### 2. MAESTRO Example (RAG Chatbot)
- **File:** `examples/maestro-example-rag-chatbot.md`
- **Framework:** STRIDE + MAESTRO (dual framework)
- **Use Case:** AI/ML systems, LLM agents, RAG pipelines
- **Expected Threats:** ~30-50 total (15-25 STRIDE + 15-25 MAESTRO)

## Testing Dual Framework (STRIDE + MAESTRO)

For systems with AI/ML components, enable dual framework mode:

```python
async for event in run_pipeline_for_model(
    model_id="rag-chatbot-tm-001",
    description=description,
    framework=Framework.STRIDE,  # Primary framework
    provider=provider,
    max_iterations=5,
    has_ai_components=True,  # ← Triggers MAESTRO alongside STRIDE
):
    print(f"[{event.step}] {event.message}")
```

**Result:** The pipeline generates both traditional security threats (STRIDE) AND AI/ML-specific threats (MAESTRO) in a single run.

## Template Format

See `Input-template.md` for full template reference. Key sections:

### Component Description (STRIDE)
```xml
<component_description>
**Name:** [Component name]
**Purpose:** [What it does]
**Technology Stack:**
- **Language(s):** [Languages]
- **Framework(s):** [Frameworks]
...
</component_description>
```

### Assumptions (STRIDE)
```xml
<assumptions>
**Security Controls Already in Place:**
- [Control 1]
- [Control 2]

**Areas Considered In-Scope:**
- [In-scope area 1]

**Areas Considered Out-of-Scope:**
- [Out-of-scope area 1]

**Threat Modeling Focus Areas:**
- [Focus area 1]
</assumptions>
```

## Verification Checklist

### Input Parser Tests
- [ ] STRIDE component description parsed correctly
- [ ] STRIDE assumptions parsed with all sections
- [ ] MAESTRO component description parsed correctly
- [ ] MAESTRO assumptions parsed with all sections

### Assumption Enforcement Tests
- [ ] Threats respect "Areas Considered Out-of-Scope"
- [ ] Gap analysis does not suggest out-of-scope threats
- [ ] "Security Controls Already in Place" prevent redundant threats
- [ ] "Threat Modeling Focus Areas" are prioritized

### Dual Framework Tests
- [ ] STRIDE threats generated (~15-25)
- [ ] MAESTRO threats generated (~15-25)
- [ ] MAESTRO threats are AI/ML-specific (prompt injection, RAG poisoning, etc.)
- [ ] Gap analysis covers both traditional and AI/ML threats

For full testing documentation, see `examples/README.md`.

## Test Results - End-to-End Validation

### ✅ Dual Framework Pipeline Test (STRIDE + MAESTRO)

**Test Date:** 2026-03-24
**Configuration:**
- Provider: Anthropic
- Model: `claude-sonnet-4-20250514`
- Example: RAG-Powered Customer Support Chatbot
- Framework: STRIDE + MAESTRO (dual)
- Max Iterations: 3

**Execution Results:**
```
================================================================================
PIPELINE COMPLETE
================================================================================
  Iterations: 2 (stopped early - gap satisfied)
  Total Threats: 24 (STRIDE + MAESTRO combined)
  Duration: 213.21s
  Stop Reason: gap_satisfied

Iteration 1:
  - Summarize: ✓ 154 chars
  - Extract assets: ✓ 15 assets/entities
  - Extract flows: ✓ 12 flows, 8 trust boundaries
  - STRIDE threats: ✓ 11 generated
  - MAESTRO threats: ✓ 10 generated
  - Combined: 21 total threats
  - Gap analysis: Continue (coverage gaps identified)

Iteration 2:
  - STRIDE threats: ✓ 12 generated
  - MAESTRO threats: ✓ 12 generated
  - Combined: 24 total threats
  - Gap analysis: STOP (coverage satisfied)
================================================================================
```

**Validation Points:**
- ✅ Structured XML parsing working correctly
- ✅ Dual framework execution (STRIDE + MAESTRO in parallel)
- ✅ Assumption enforcement in gap analysis
- ✅ Iterative refinement with gap-driven stopping
- ✅ All 24 threats properly categorized by framework
- ✅ Pipeline stopped early when coverage was satisfied

### ⚠️ Important Model Configuration Note

**Use Claude Sonnet (or newer) for structured output generation.**

During testing, we discovered that `claude-haiku-4-5-20251001` produces JSON parsing errors when generating complex structured threat outputs. The model struggles with large, deeply nested JSON responses required by the `ThreatsList` Pydantic model.

**Recommended Configuration:**
```bash
# In .env file
DEFAULT_MODEL=claude-sonnet-4-20250514
```

**Models Tested:**
- ❌ `claude-haiku-4-5-20251001` - Fails with "Unterminated string" JSON errors
- ✅ `claude-sonnet-4-20250514` - Works perfectly, validated end-to-end

**Why This Matters:**
- Haiku is optimized for speed and cost, not complex structured outputs
- Sonnet has better instruction following for JSON generation
- The dual framework test generates 20+ threats per iteration = large JSON
- Malformed JSON breaks the pipeline immediately

**Cost Impact:**
- Sonnet is more expensive than Haiku (~5x cost per token)
- But it's required for reliable threat generation
- Consider Haiku only for simple single-framework, low-iteration runs

**Alternative:** For fully local/offline deployments, use Ollama with a capable model (Llama 3 70B or newer).
