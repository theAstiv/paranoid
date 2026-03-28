# Quick Start - Testing the Threat Modeling Pipeline

## Setup (2 minutes)

### Step 1: Create your `.env` file

```bash
cp .env.example .env
```

### Step 2: Add your API key

Edit `.env` and add your API key. Choose ONE provider:

**Option A: Anthropic (Claude) - Recommended**
```bash
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxx
DEFAULT_PROVIDER=anthropic
DEFAULT_MODEL=claude-sonnet-4-20250514
```

**Option B: OpenAI**
```bash
OPENAI_API_KEY=sk-xxxxxxxxx
DEFAULT_PROVIDER=openai
DEFAULT_MODEL=gpt-4-turbo
```

**Option C: Ollama (Local)**
```bash
OLLAMA_BASE_URL=http://localhost:11434
DEFAULT_PROVIDER=ollama
DEFAULT_MODEL=llama3
```

### Step 3: Install dependencies (if not already done)

```bash
pip install -e .
```

## Run the Test

```bash
python test_pipeline.py
```

This will run a complete threat modeling pipeline on a sample document-sharing web application.

## Expected Runtime

- **Claude Sonnet**: ~30-60 seconds (3 iterations)
- **GPT-4**: ~45-90 seconds (3 iterations)
- **Ollama** (local): 2-5 minutes (3 iterations, depends on hardware)

## What You'll See

The test will:

1. ✓ Load configuration and initialize provider
2. ▶ Generate system summary
3. ▶ Extract 8-12 assets/entities
4. ▶ Extract 10-15 data flows and trust boundaries
5. ▶ Generate initial threats (Iteration 1)
6. ▶ Analyze coverage gaps
7. ▶ Improve threats (Iteration 2)
8. ▶ Analyze coverage gaps
9. ▶ Finalize threats (Iteration 3)
10. ✓ Complete with summary

## Success Indicators

You should see:

- ✓ All steps complete without errors
- ✓ 10-20 threats generated across 3 iterations
- ✓ DREAD scores assigned to each threat
- ✓ Severity distribution (Critical/High/Medium/Low)
- ✓ Total runtime under 2 minutes (for Claude/GPT)

## Troubleshooting

### "Authentication failed"
- Check your API key is correct in `.env`
- Verify the key has not expired
- For Anthropic, ensure billing is set up

### "Module not found"
```bash
pip install -e .
```

### "Ollama connection refused"
```bash
# Start Ollama first:
ollama serve

# In another terminal:
python test_pipeline.py
```

### "Import errors"
Make sure you're in the project root:
```bash
cd /path/to/paranoid
python test_pipeline.py
```

## Next Steps

Once the test passes:

1. Review the generated threats in the console output
2. Try adjusting `DEFAULT_ITERATIONS` in `.env` (1-15)
3. Test with your own system description
4. Compare STRIDE vs MAESTRO frameworks
5. Continue with Phase 7 development (Rule Engine)

## Sample Output

```
================================================================================
PARANOID THREAT MODELING PIPELINE - TEST
================================================================================

✓ Configuration loaded
  Provider: anthropic
  Model: claude-sonnet-4-20250514
  Max Iterations: 3

✓ Provider initialized: anthropic

================================================================================
STARTING PIPELINE EXECUTION
================================================================================

▶ summarize: Generating system summary...
✓ summarize: Summary generated: 156 chars

▶ extract_assets: Identifying assets and entities...
✓ extract_assets: Identified 8 assets/entities

▶ extract_flows: Extracting data flows and trust boundaries...
✓ extract_flows: Identified 12 flows, 5 boundaries

▶ generate_threats [Iteration 1]: Generating threats...
✓ generate_threats [Iteration 1]: Generated 10 threats

▶ gap_analysis [Iteration 1]: Analyzing threat coverage gaps...
✓ gap_analysis [Iteration 1]: Gap identified: Missing threats for...

... (2 more iterations) ...

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

## Getting Help

See [TESTING.md](TESTING.md) for detailed troubleshooting and advanced testing scenarios.
