#!/usr/bin/env python3
"""Pipeline test script with multiple test scenarios.

Usage:
    1. Copy .env.example to .env
    2. Add your API key to .env
    3. Run: python test_pipeline.py

Test scenarios:
    1. Basic STRIDE (plain text input)
    2. STRIDE with structured input (XML templates)
    3. STRIDE+MAESTRO dual framework (AI/ML system)
"""

import asyncio
import sys
from pathlib import Path

from backend.config import Settings
from backend.models.enums import Framework
from backend.pipeline import run_pipeline_for_model
from backend.providers import create_provider


async def test_basic_pipeline():
    """Test the pipeline with a simple web application scenario."""
    print("=" * 80)
    print("PARANOID THREAT MODELING PIPELINE - TEST")
    print("=" * 80)
    print()

    # Load settings
    settings = Settings()
    print("[OK] Configuration loaded")
    print(f"  Provider: {settings.default_provider}")
    print(f"  Model: {settings.default_model}")
    print(f"  Max Iterations: {settings.default_iterations}")
    print()

    # Initialize provider
    try:
        provider = create_provider(
            provider_type=settings.default_provider,
            model=settings.default_model,
            api_key=(
                settings.anthropic_api_key
                if settings.default_provider == "anthropic"
                else settings.openai_api_key
                if settings.default_provider == "openai"
                else None
            ),
            base_url=settings.ollama_base_url if settings.default_provider == "ollama" else None,
        )
        print(f"[OK] Provider initialized: {settings.default_provider}")
        print()
    except Exception as e:
        print(f"[ERROR] Failed to initialize provider: {e}")
        print()
        print("Please check your .env file and ensure:")
        if settings.default_provider == "anthropic":
            print("  - ANTHROPIC_API_KEY is set")
        elif settings.default_provider == "openai":
            print("  - OPENAI_API_KEY is set")
        elif settings.default_provider == "ollama":
            print("  - Ollama is running at OLLAMA_BASE_URL")
        sys.exit(1)

    # Test scenario: Simple web application
    test_description = """
A web application that allows users to upload and share documents.
The system has:
- Frontend: React SPA hosted on AWS S3 + CloudFront
- Backend: Node.js API running on AWS Lambda
- Database: PostgreSQL RDS instance
- Storage: S3 bucket for document uploads
- Authentication: JWT tokens with Auth0

Users can:
- Register and login
- Upload documents (PDF, DOCX, images)
- Share documents with other users via email links
- Download documents they have access to
"""

    test_assumptions = [
        "Application runs in AWS cloud environment",
        "Users authenticate via Auth0 (OAuth 2.0)",
        "All data at rest is encrypted using AWS KMS",
        "HTTPS is enforced for all communications",
        "No sensitive PII is stored beyond email addresses",
    ]

    print("Test Scenario: Document Sharing Web Application")
    print("-" * 80)
    print(test_description.strip())
    print()
    print("Assumptions:")
    for assumption in test_assumptions:
        print(f"  • {assumption}")
    print()
    print("=" * 80)
    print("STARTING PIPELINE EXECUTION")
    print("=" * 80)
    print()

    # Run pipeline
    model_id = "test-model-001"
    framework = Framework.STRIDE  # Test with STRIDE first

    try:
        async for event in run_pipeline_for_model(
            model_id=model_id,
            description=test_description,
            framework=framework,
            provider=provider,
            architecture_diagram=None,
            assumptions=test_assumptions,
            code_context=None,
            max_iterations=settings.default_iterations,
        ):
            # Print events
            status_icon = {
                "started": "[>>]",
                "completed": "[OK]",
                "failed": "[FAIL]",
                "info": "[INFO]",
            }.get(event.status, "[-]")

            iteration_info = f" [Iteration {event.iteration}]" if event.iteration else ""
            print(f"{status_icon} {event.step.value}{iteration_info}: {event.message}")

            # Print detailed data for completed steps
            if event.status == "completed" and event.data:
                if event.step.value == "summarize":
                    print(f"    Summary: {event.data.get('summary', '')[:100]}...")
                elif event.step.value == "extract_assets":
                    print(f"    Assets: {event.data.get('asset_count', 0)}")
                elif event.step.value == "extract_flows":
                    print(
                        f"    Flows: {event.data.get('flow_count', 0)}, Boundaries: {event.data.get('boundary_count', 0)}"
                    )
                elif event.step.value == "generate_threats":
                    print(f"    Threats: {event.data.get('threat_count', 0)}")
                elif event.step.value == "gap_analysis":
                    if event.data.get("stop"):
                        print("    Decision: STOP (coverage satisfied)")
                    else:
                        gap_text = event.data.get("gap", "")[:100]
                        print(f"    Decision: CONTINUE - Gap: {gap_text}...")
                elif event.step.value == "complete":
                    print()
                    print("=" * 80)
                    print("PIPELINE COMPLETE")
                    print("=" * 80)
                    print(f"  Iterations: {event.data.get('iterations', 0)}")
                    print(f"  Total Threats: {event.data.get('threat_count', 0)}")
                    print(f"  Duration: {event.data.get('duration_seconds', 0):.2f}s")
                    print(f"  Stop Reason: {event.data.get('stopped_reason', 'unknown')}")
                    print("=" * 80)

            if event.status == "failed":
                print()
                print("=" * 80)
                print("PIPELINE FAILED")
                print("=" * 80)
                print(f"Error: {event.data.get('error', 'Unknown error')}")
                print("=" * 80)
                sys.exit(1)

        print()
        print("[OK] Test completed successfully!")
        print()
        print("Next steps:")
        print("  1. Review the threats generated")
        print("  2. Try different frameworks (STRIDE vs MAESTRO)")
        print("  3. Adjust iteration count in .env")
        print("  4. Test with your own system descriptions")

    except Exception as e:
        print()
        print("=" * 80)
        print("ERROR DURING PIPELINE EXECUTION")
        print("=" * 80)
        print(f"Exception: {type(e).__name__}")
        print(f"Message: {e!s}")
        import traceback

        print()
        print("Traceback:")
        traceback.print_exc()
        print("=" * 80)
        sys.exit(1)


async def test_structured_stride():
    """Test STRIDE with structured XML-tagged input."""
    print("=" * 80)
    print("STRUCTURED INPUT TEST - STRIDE (API Gateway)")
    print("=" * 80)
    print()

    # Load settings
    settings = Settings()
    print("[OK] Configuration loaded")
    print(f"  Provider: {settings.default_provider}")
    print(f"  Model: {settings.default_model}")
    print(f"  Max Iterations: {settings.default_iterations}")
    print()

    # Initialize provider
    try:
        provider = create_provider(
            provider_type=settings.default_provider,
            model=settings.default_model,
            api_key=(
                settings.anthropic_api_key
                if settings.default_provider == "anthropic"
                else settings.openai_api_key
                if settings.default_provider == "openai"
                else None
            ),
            base_url=settings.ollama_base_url if settings.default_provider == "ollama" else None,
        )
        print(f"[OK] Provider initialized: {settings.default_provider}")
        print()
    except Exception as e:
        print(f"[ERROR] Failed to initialize provider: {e}")
        sys.exit(1)

    # Load structured example
    example_path = Path(__file__).parent / "examples" / "stride-example-api-gateway.md"
    if not example_path.exists():
        print(f"[ERROR] Example file not found: {example_path}")
        print("Please ensure examples/stride-example-api-gateway.md exists")
        sys.exit(1)

    with open(example_path, encoding="utf-8") as f:
        structured_description = f.read()

    print("Test Scenario: E-commerce API Gateway (Structured Input)")
    print("-" * 80)
    print("Input format: XML-tagged structured template")
    print("Framework: STRIDE only")
    print("Has AI components: No")
    print()
    print("=" * 80)
    print("STARTING PIPELINE EXECUTION")
    print("=" * 80)
    print()

    # Run pipeline
    try:
        async for event in run_pipeline_for_model(
            model_id="test-structured-stride-001",
            description=structured_description,  # Structured XML input
            framework=Framework.STRIDE,
            provider=provider,
            max_iterations=settings.default_iterations,
            has_ai_components=False,  # STRIDE only
        ):
            _print_event(event)

        print()
        print("[OK] Structured STRIDE test completed successfully!")

    except Exception as e:
        _print_error(e)
        sys.exit(1)


async def test_dual_framework():
    """Test STRIDE+MAESTRO dual framework with AI/ML system."""
    print("=" * 80)
    print("DUAL FRAMEWORK TEST - STRIDE+MAESTRO (RAG Chatbot)")
    print("=" * 80)
    print()

    # Load settings
    settings = Settings()
    print("[OK] Configuration loaded")
    print(f"  Provider: {settings.default_provider}")
    print(f"  Model: {settings.default_model}")
    print(f"  Max Iterations: {settings.default_iterations}")
    print()

    # Initialize provider
    try:
        provider = create_provider(
            provider_type=settings.default_provider,
            model=settings.default_model,
            api_key=(
                settings.anthropic_api_key
                if settings.default_provider == "anthropic"
                else settings.openai_api_key
                if settings.default_provider == "openai"
                else None
            ),
            base_url=settings.ollama_base_url if settings.default_provider == "ollama" else None,
        )
        print(f"[OK] Provider initialized: {settings.default_provider}")
        print()
    except Exception as e:
        print(f"[ERROR] Failed to initialize provider: {e}")
        sys.exit(1)

    # Load MAESTRO structured example
    example_path = Path(__file__).parent / "examples" / "maestro-example-rag-chatbot.md"
    if not example_path.exists():
        print(f"[ERROR] Example file not found: {example_path}")
        print("Please ensure examples/maestro-example-rag-chatbot.md exists")
        sys.exit(1)

    with open(example_path, encoding="utf-8") as f:
        maestro_description = f.read()

    print("Test Scenario: RAG-Powered Customer Support Chatbot (AI/ML System)")
    print("-" * 80)
    print("Input format: MAESTRO XML-tagged template")
    print("Framework: STRIDE + MAESTRO (dual)")
    print("Has AI components: Yes")
    print()
    print("Expected output:")
    print("  - STRIDE threats (traditional security)")
    print("  - MAESTRO threats (AI/ML-specific)")
    print("  - Combined threat catalog")
    print()
    print("=" * 80)
    print("STARTING DUAL FRAMEWORK PIPELINE")
    print("=" * 80)
    print()

    # Run pipeline with dual framework
    try:
        async for event in run_pipeline_for_model(
            model_id="test-dual-framework-001",
            description=maestro_description,  # MAESTRO structured XML input
            framework=Framework.STRIDE,  # Primary framework
            provider=provider,
            max_iterations=settings.default_iterations,
            has_ai_components=True,  # Triggers MAESTRO alongside STRIDE
        ):
            _print_event(event)

        print()
        print("[OK] Dual framework test completed successfully!")
        print()
        print("The pipeline generated BOTH:")
        print("  [OK] STRIDE threats (spoofing, tampering, etc.)")
        print("  [OK] MAESTRO threats (prompt injection, RAG poisoning, etc.)")

    except Exception as e:
        _print_error(e)
        sys.exit(1)


def _print_event(event):
    """Helper to print pipeline events."""
    status_icon = {
        "started": "[>>]",
        "completed": "[OK]",
        "failed": "[FAIL]",
        "info": "[INFO]",
    }.get(event.status, "[-]")

    iteration_info = f" [Iteration {event.iteration}]" if event.iteration else ""
    print(f"{status_icon} {event.step.value}{iteration_info}: {event.message}")

    # Print detailed data for completed steps
    if event.status == "completed" and event.data:
        if event.step.value == "summarize":
            summary = event.data.get("summary", "")[:100]
            print(f"    Summary: {summary}...")
        elif event.step.value == "extract_assets":
            print(f"    Assets: {event.data.get('asset_count', 0)}")
        elif event.step.value == "extract_flows":
            print(
                f"    Flows: {event.data.get('flow_count', 0)}, Boundaries: {event.data.get('boundary_count', 0)}"
            )
        elif event.step.value == "generate_threats":
            threat_count = event.data.get("threat_count", 0)
            framework_type = event.data.get("framework")
            if framework_type:
                print(f"    Threats: {threat_count} ({framework_type})")
            else:
                print(f"    Threats: {threat_count}")
        elif event.step.value == "gap_analysis":
            if event.data.get("stop"):
                print("    Decision: STOP (coverage satisfied)")
            else:
                gap_text = event.data.get("gap", "")[:100]
                print(f"    Decision: CONTINUE - Gap: {gap_text}...")
        elif event.step.value == "complete":
            print()
            print("=" * 80)
            print("PIPELINE COMPLETE")
            print("=" * 80)
            print(f"  Iterations: {event.data.get('iterations', 0)}")
            print(f"  Total Threats: {event.data.get('threat_count', 0)}")
            print(f"  Duration: {event.data.get('duration_seconds', 0):.2f}s")
            print(f"  Stop Reason: {event.data.get('stopped_reason', 'unknown')}")
            print("=" * 80)

    if event.status == "failed":
        print()
        print("=" * 80)
        print("PIPELINE FAILED")
        print("=" * 80)
        print(f"Error: {event.data.get('error', 'Unknown error')}")
        print("=" * 80)


def _print_error(e):
    """Helper to print error information."""
    print()
    print("=" * 80)
    print("ERROR DURING PIPELINE EXECUTION")
    print("=" * 80)
    print(f"Exception: {type(e).__name__}")
    print(f"Message: {e!s}")
    import traceback

    print()
    print("Traceback:")
    traceback.print_exc()
    print("=" * 80)


async def main():
    """Main test menu."""
    print()
    print("=" * 80)
    print("PARANOID THREAT MODELING PIPELINE - TEST SUITE")
    print("=" * 80)
    print()
    print("Select a test scenario:")
    print()
    print("  1. Basic STRIDE (plain text input)")
    print("     - Simple web application")
    print("     - Traditional threat modeling")
    print()
    print("  2. STRIDE with structured input (XML templates)")
    print("     - E-commerce API Gateway")
    print("     - Component description + assumptions")
    print()
    print("  3. STRIDE+MAESTRO dual framework (AI/ML system)")
    print("     - RAG-powered chatbot")
    print("     - Both traditional and AI-specific threats")
    print()
    print("  4. Run all tests")
    print()

    try:
        choice = input("Enter choice (1-4) [default: 1]: ").strip() or "1"
    except (KeyboardInterrupt, EOFError):
        print("\nTest cancelled.")
        sys.exit(0)

    print()

    if choice == "1":
        await test_basic_pipeline()
    elif choice == "2":
        await test_structured_stride()
    elif choice == "3":
        await test_dual_framework()
    elif choice == "4":
        print("Running all tests...")
        print()
        await test_basic_pipeline()
        print("\n" + "=" * 80 + "\n")
        await test_structured_stride()
        print("\n" + "=" * 80 + "\n")
        await test_dual_framework()
    else:
        print(f"Invalid choice: {choice}")
        print("Please run again and select 1, 2, 3, or 4")
        sys.exit(1)

    print()
    print("=" * 80)
    print("ALL TESTS COMPLETED")
    print("=" * 80)
    print()
    print("Next steps:")
    print("  1. Review the generated threats")
    print("  2. Try different iteration counts in .env")
    print("  3. Create your own structured templates")
    print("  4. Test with real systems from your organization")


if __name__ == "__main__":
    print()
    asyncio.run(main())
