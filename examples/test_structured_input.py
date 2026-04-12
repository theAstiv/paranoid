"""Test script demonstrating structured XML-tagged input for threat modeling.

This script runs two test cases:
1. STRIDE-only threat modeling (API Gateway example)
2. STRIDE+MAESTRO dual framework (RAG Chatbot example)

Usage:
    # Set environment variable first
    export ANTHROPIC_API_KEY="your-key-here"

    # Run the test
    python examples/test_structured_input.py
"""

import asyncio
from pathlib import Path

from backend.models.enums import Framework
from backend.pipeline.runner import run_pipeline_for_model
from backend.providers.anthropic import AnthropicProvider


async def test_stride_only():
    """Test STRIDE-only threat modeling with structured input."""
    print("\n" + "=" * 80)
    print("TEST 1: STRIDE-Only Threat Modeling (API Gateway)")
    print("=" * 80 + "\n")

    # Read the STRIDE example
    example_path = Path(__file__).parent / "stride-example-api-gateway.md"
    with open(example_path, encoding="utf-8") as f:
        description = f.read()

    # Initialize provider
    import os

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set")
        return

    provider = AnthropicProvider(api_key=api_key)

    # Run pipeline
    print("Starting STRIDE pipeline...")
    print(f"Input length: {len(description)} characters")
    print("Framework: STRIDE only")
    print("Has AI components: False\n")

    threats_generated = 0
    iteration_count = 0

    async for event in run_pipeline_for_model(
        model_id="test-api-gateway-001",
        description=description,
        framework=Framework.STRIDE,
        provider=provider,
        max_iterations=3,
        has_ai_components=False,  # STRIDE only
    ):
        step = event.step.value if hasattr(event.step, "value") else event.step
        status = event.status

        if step == "generate_threats" and status == "completed":
            threats_generated = event.data.get("threat_count", 0)
            iteration_count = event.iteration or 0
            print(f"  [OK] Iteration {iteration_count}: Generated {threats_generated} threats")

        elif step == "gap_analysis" and status == "completed":
            gap_detected = not event.data.get("stop", False)
            if gap_detected:
                gap_preview = event.data.get("gap", "")[:100]
                print(f"  --> Gap detected: {gap_preview}...")
            else:
                print("  [OK] Gap analysis satisfied - catalog complete")

        elif step == "complete":
            if status == "completed":
                total_threats = event.data.get("threat_count", 0)
                iterations = event.data.get("iterations", 0)
                duration = event.data.get("duration_seconds", 0)
                print("\n[SUCCESS] Pipeline complete!")
                print(f"   Total threats: {total_threats}")
                print(f"   Iterations: {iterations}")
                print(f"   Duration: {duration:.1f}s")
            elif status == "failed":
                error = event.data.get("error", "Unknown error")
                print(f"\n[FAIL] Pipeline failed: {error}")


async def test_stride_maestro_dual():
    """Test STRIDE+MAESTRO dual framework with structured input."""
    print("\n" + "=" * 80)
    print("TEST 2: STRIDE+MAESTRO Dual Framework (RAG Chatbot)")
    print("=" * 80 + "\n")

    # Read the MAESTRO example
    example_path = Path(__file__).parent / "maestro-example-rag-chatbot.md"
    with open(example_path, encoding="utf-8") as f:
        description = f.read()

    # Initialize provider
    import os

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set")
        return

    provider = AnthropicProvider(api_key=api_key)

    # Run pipeline
    print("Starting STRIDE+MAESTRO dual framework pipeline...")
    print(f"Input length: {len(description)} characters")
    print("Framework: STRIDE + MAESTRO (dual)")
    print("Has AI components: True\n")

    stride_threats = 0
    maestro_threats = 0
    total_threats = 0
    iteration_count = 0

    async for event in run_pipeline_for_model(
        model_id="test-rag-chatbot-001",
        description=description,
        framework=Framework.STRIDE,  # Primary framework
        provider=provider,
        max_iterations=3,
        has_ai_components=True,  # Triggers MAESTRO alongside STRIDE
    ):
        step = event.step.value if hasattr(event.step, "value") else event.step
        status = event.status

        if step == "generate_threats" and status == "completed":
            threat_count = event.data.get("threat_count", 0)
            framework_type = event.data.get("framework")
            iteration_count = event.iteration or 0

            if framework_type == "STRIDE":
                stride_threats = threat_count
                print(
                    f"  [OK] Iteration {iteration_count}: Generated {stride_threats} STRIDE threats"
                )
            elif framework_type == "MAESTRO":
                maestro_threats = threat_count
                print(
                    f"  [OK] Iteration {iteration_count}: Generated {maestro_threats} MAESTRO threats"
                )
            else:
                # Combined count
                total_threats = threat_count

        elif step == "generate_threats" and status == "info":
            # This is the combined threat count message
            total_threats = event.data.get("threat_count", 0)
            print(
                f"  --> Combined: {total_threats} total threats (STRIDE: {stride_threats}, MAESTRO: {maestro_threats})"
            )

        elif step == "gap_analysis" and status == "completed":
            gap_detected = not event.data.get("stop", False)
            if gap_detected:
                gap_preview = event.data.get("gap", "")[:100]
                print(f"  --> Gap detected: {gap_preview}...")
            else:
                print("  [OK] Gap analysis satisfied - catalog complete")

        elif step == "complete":
            if status == "completed":
                total_threats = event.data.get("threat_count", 0)
                iterations = event.data.get("iterations", 0)
                duration = event.data.get("duration_seconds", 0)
                print("\n[SUCCESS] Pipeline complete!")
                print(f"   Total threats: {total_threats}")
                print(f"   STRIDE threats: ~{stride_threats * iterations}")
                print(f"   MAESTRO threats: ~{maestro_threats * iterations}")
                print(f"   Iterations: {iterations}")
                print(f"   Duration: {duration:.1f}s")
            elif status == "failed":
                error = event.data.get("error", "Unknown error")
                print(f"\n[FAIL] Pipeline failed: {error}")


async def test_input_parser():
    """Test the input parser to verify structured input detection."""
    print("\n" + "=" * 80)
    print("TEST 3: Input Parser Validation")
    print("=" * 80 + "\n")

    from backend.pipeline import input_parser

    # Test STRIDE example
    example_path = Path(__file__).parent / "stride-example-api-gateway.md"
    with open(example_path, encoding="utf-8") as f:
        stride_content = f.read()

    print("Testing STRIDE example parsing...")
    input_format = input_parser.detect_input_format(stride_content)
    print(f"  Detected format: {input_format}")

    component_desc = input_parser.parse_stride_component_description(stride_content)
    if component_desc:
        print(f"  [OK] Component name: {component_desc.name}")
        print(f"  [OK] Technology stack sections: {len(component_desc.technology_stack)}")
        print(f"  [OK] Dependencies: {len(component_desc.dependencies)}")
    else:
        print("  [FAIL] Failed to parse component description")

    assumptions = input_parser.parse_stride_assumptions(stride_content)
    if assumptions:
        print(f"  [OK] Security controls: {len(assumptions.security_controls)}")
        print(f"  [OK] In-scope items: {len(assumptions.in_scope)}")
        print(f"  [OK] Out-of-scope items: {len(assumptions.out_of_scope)}")
        print(f"  [OK] Focus areas: {len(assumptions.focus_areas)}")
    else:
        print("  [FAIL] Failed to parse assumptions")

    # Test MAESTRO example
    print("\nTesting MAESTRO example parsing...")
    example_path = Path(__file__).parent / "maestro-example-rag-chatbot.md"
    with open(example_path, encoding="utf-8") as f:
        maestro_content = f.read()

    input_format = input_parser.detect_input_format(maestro_content)
    print(f"  Detected format: {input_format}")

    component_desc = input_parser.parse_maestro_component_description(maestro_content)
    if component_desc:
        print(f"  [OK] Component name: {component_desc.name}")
        print(f"  [OK] Mission alignment fields: {len(component_desc.mission_alignment)}")
        print(f"  [OK] Agent profile sections: {len(component_desc.agent_profile)}")
        print(f"  [OK] Assets sections: {len(component_desc.assets)}")
    else:
        print("  [FAIL] Failed to parse component description")

    assumptions = input_parser.parse_maestro_assumptions(maestro_content)
    if assumptions:
        print(f"  [OK] Security controls: {len(assumptions.security_controls)}")
        print(f"  [OK] AI-specific controls: {len(assumptions.ai_specific_controls)}")
        print(f"  [OK] Agentic considerations: {len(assumptions.agentic_considerations)}")
        print(f"  [OK] Focus areas: {len(assumptions.focus_areas)}")
    else:
        print("  [FAIL] Failed to parse assumptions")


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("Structured Input Testing Suite")
    print("=" * 80)

    # Test 3: Input parser (fast, no API calls)
    await test_input_parser()

    # Test 1: STRIDE only
    # Uncomment to run (requires API key)
    # await test_stride_only()

    # Test 2: STRIDE + MAESTRO
    # Uncomment to run (requires API key)
    # await test_stride_maestro_dual()

    print("\n" + "=" * 80)
    print("Tests complete!")
    print("=" * 80 + "\n")
    print("To run the full pipeline tests, set ANTHROPIC_API_KEY and uncomment")
    print("the test function calls in main().")


if __name__ == "__main__":
    asyncio.run(main())
