"""End-to-end pipeline tests with real LLM calls and real inputs.

These tests validate the full pipeline with:
- Real Anthropic API calls (requires ANTHROPIC_API_KEY)
- Real diagram files from examples/ (PNG + Mermaid)
- Real code extraction via context-link MCP server
- Real GitHub repos cloned to temp directories

Run:
    pytest tests/test_pipeline_e2e.py -v

Skip condition: auto-skips if ANTHROPIC_API_KEY not set.
Cleanup: all temp files (repos, binary) auto-deleted after session.
"""

import logging
import os
import platform
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values

from backend.models.enums import DiagramFormat, Framework
from backend.pipeline.runner import PipelineEvent, PipelineStep, run_pipeline_for_model
from backend.providers import create_provider
from cli.input.diagram_loader import load_diagram_file


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load .env values for skip guard — dotenv_values reads the file directly
# without depending on pydantic-settings or os.environ
# ---------------------------------------------------------------------------
_dotenv = dotenv_values(Path(__file__).parent.parent / ".env")
_api_key = _dotenv.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not _api_key or _api_key.startswith("sk-ant-xxx"),
    reason="E2E tests require a real ANTHROPIC_API_KEY (set in .env or environment)",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
CONTEXT_LINK_VERSION = "1.0.0"
CONTEXT_LINK_BASE_URL = (
    f"https://github.com/context-link-mcp/context-link/releases/download/v{CONTEXT_LINK_VERSION}"
)

# Repos for code-as-input tests (small, well-known, public)
STRIDE_REPO_URL = "https://github.com/gothinkster/flask-realworld-example-app.git"
MAESTRO_REPO_URL = "https://github.com/pixegami/rag-tutorial-v2.git"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_example(filename: str) -> str:
    """Read an example markdown file as a description string."""
    path = EXAMPLES_DIR / filename
    return path.read_text(encoding="utf-8")


def _detect_platform() -> tuple[str, str]:
    """Detect OS and architecture for context-link binary download.

    Returns:
        (os_name, arch) tuple matching context-link release naming.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux" or (system == "windows" and "microsoft" in platform.release().lower()):
        os_name = "linux"
    elif system == "darwin":
        os_name = "darwin"
    elif system == "windows":
        os_name = "windows"
    else:
        os_name = system

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        arch = machine

    return os_name, arch


def _download_context_link(dest_dir: Path) -> Path | None:
    """Download context-link binary to dest_dir. Returns binary path or None."""
    os_name, arch = _detect_platform()

    if os_name == "windows" and arch == "amd64":
        asset_name = f"context-link_{CONTEXT_LINK_VERSION}_{os_name}_{arch}.zip"
    else:
        asset_name = f"context-link_{CONTEXT_LINK_VERSION}_{os_name}_{arch}.tar.gz"

    url = f"{CONTEXT_LINK_BASE_URL}/{asset_name}"
    archive_path = dest_dir / asset_name

    logger.info("Downloading context-link from %s", url)
    try:
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            archive_path.write_bytes(resp.content)
    except (httpx.HTTPError, OSError) as e:
        logger.warning("Failed to download context-link: %s", e)
        return None

    # Extract
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(dest_dir)  # noqa: S202 — trusted source (GitHub release)
    else:
        with tarfile.open(archive_path) as tf:
            tf.extractall(dest_dir)  # noqa: S202 — trusted source (GitHub release)

    # Find binary
    binary_name = "context-link.exe" if os_name == "windows" else "context-link"
    binary_path = dest_dir / binary_name
    if not binary_path.exists():
        # Some archives nest in a subdirectory
        for p in dest_dir.rglob(binary_name):
            binary_path = p
            break

    if not binary_path.exists():
        logger.warning("context-link binary not found after extraction")
        return None

    if os_name != "windows":
        binary_path.chmod(0o755)

    logger.info("context-link binary ready at %s", binary_path)
    return binary_path


def _clone_repo(url: str, dest: Path) -> Path | None:
    """Shallow-clone a git repo. Returns repo path or None on failure."""
    logger.info("Cloning %s → %s", url, dest)
    try:
        subprocess.run(  # noqa: S603
            ["git", "clone", "--depth", "1", url, str(dest)],  # noqa: S607
            check=True,
            capture_output=True,
            timeout=120,
        )
        return dest
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Failed to clone %s: %s", url, e)
        return None


async def _collect_events(
    provider,
    description: str,
    framework: Framework,
    *,
    code_context=None,
    diagram_data=None,
    max_iterations: int = 2,
    has_ai_components: bool = False,
) -> list[PipelineEvent]:
    """Run pipeline and collect all events."""
    events = []
    async for event in run_pipeline_for_model(
        model_id="e2e-test",
        description=description,
        framework=framework,
        provider=provider,
        code_context=code_context,
        diagram_data=diagram_data,
        max_iterations=max_iterations,
        has_ai_components=has_ai_components,
    ):
        events.append(event)
        # Log progress for visibility during long runs
        if event.status in ("started", "completed", "failed"):
            logger.info("[%s] %s: %s", event.status.upper(), event.step.value, event.message)
    return events


def _assert_pipeline_completed(events: list[PipelineEvent]) -> dict:
    """Assert core pipeline steps completed and return completion data.

    Returns the data dict from the COMPLETE event for further assertions.
    """
    step_statuses = [(e.step, e.status) for e in events]

    # Core steps must start and complete
    for step in (
        PipelineStep.SUMMARIZE,
        PipelineStep.EXTRACT_ASSETS,
        PipelineStep.EXTRACT_FLOWS,
        PipelineStep.GENERATE_THREATS,
    ):
        assert (step, "started") in step_statuses, f"{step.value} never started"
        assert (step, "completed") in step_statuses, f"{step.value} never completed"

    # Must end with COMPLETE
    final = events[-1]
    assert final.step == PipelineStep.COMPLETE, f"Last event was {final.step}, expected COMPLETE"
    assert final.status == "completed", f"COMPLETE status was {final.status}, expected completed"
    assert final.data is not None, "COMPLETE event missing data"

    # Must have generated at least 1 threat
    threat_count = final.data.get("total_threats", 0)
    assert threat_count > 0, f"No threats generated (total_threats={threat_count})"

    return final.data


# ---------------------------------------------------------------------------
# Session-scoped fixtures (setup once, auto-cleanup)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def context_link_binary(tmp_path_factory):
    """Download context-link binary to a temp dir. Skip tests if unavailable."""
    # First check if already available locally or on PATH
    local_bin = Path("bin/context-link")
    if local_bin.exists():
        return str(local_bin.resolve())

    which_result = shutil.which("context-link")
    if which_result:
        return which_result

    # Download to temp dir
    bin_dir = tmp_path_factory.mktemp("context-link-bin")
    binary = _download_context_link(bin_dir)
    if binary is None:
        pytest.skip("context-link binary not available (download failed)")
    return str(binary)


@pytest.fixture(scope="session")
def stride_repo(tmp_path_factory):
    """Clone a small web app repo for STRIDE code-as-input testing."""
    repo_dir = tmp_path_factory.mktemp("repos") / "stride-app"
    result = _clone_repo(STRIDE_REPO_URL, repo_dir)
    if result is None:
        pytest.skip(f"Failed to clone STRIDE repo: {STRIDE_REPO_URL}")
    return result


@pytest.fixture(scope="session")
def maestro_repo(tmp_path_factory):
    """Clone a small AI/ML repo for MAESTRO code-as-input testing."""
    repo_dir = tmp_path_factory.mktemp("repos") / "maestro-app"
    result = _clone_repo(MAESTRO_REPO_URL, repo_dir)
    if result is None:
        pytest.skip(f"Failed to clone MAESTRO repo: {MAESTRO_REPO_URL}")
    return result


@pytest.fixture
def anthropic_provider():
    """Create a real Anthropic provider using API key from .env."""
    return create_provider(
        provider_type="anthropic",
        model=_dotenv.get("DEFAULT_MODEL", "claude-sonnet-4-20250514"),
        api_key=_api_key,
        max_retries=2,
        timeout=120.0,
    )


# ---------------------------------------------------------------------------
# Test 1: STRIDE + code-as-input
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e2e_stride_code_as_input(anthropic_provider, stride_repo, context_link_binary):
    """Full pipeline: STRIDE framework with real code extraction via context-link."""
    from backend.mcp.client import MCPCodeExtractor

    description = _read_example("stride-example-api-gateway.md")

    # Extract real code context from cloned repo
    async with MCPCodeExtractor(
        project_root=str(stride_repo),
        binary_path=context_link_binary,
        timeout_seconds=120,
    ) as extractor:
        code_context = await extractor.extract_context(
            description=description,
            max_bytes=50_000,
        )

    assert code_context is not None
    assert len(code_context.files) > 0, "No code files extracted"

    # Run pipeline
    events = await _collect_events(
        anthropic_provider,
        description,
        Framework.STRIDE,
        code_context=code_context,
        max_iterations=2,
    )

    completion_data = _assert_pipeline_completed(events)

    # Code-specific: SUMMARIZE_CODE step must have run
    step_statuses = [(e.step, e.status) for e in events]
    assert (PipelineStep.SUMMARIZE_CODE, "completed") in step_statuses, (
        "SUMMARIZE_CODE step did not complete — code context was not processed"
    )

    logger.info(
        "STRIDE+code test passed: %d threats in %d iterations (%.1fs)",
        completion_data.get("total_threats", 0),
        completion_data.get("iterations_completed", 0),
        completion_data.get("duration_seconds", 0),
    )


# ---------------------------------------------------------------------------
# Test 2: MAESTRO + code-as-input
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e2e_maestro_code_as_input(anthropic_provider, maestro_repo, context_link_binary):
    """Full pipeline: MAESTRO framework with real code extraction via context-link."""
    from backend.mcp.client import MCPCodeExtractor

    description = _read_example("maestro-example-rag-chatbot.md")

    # Extract real code context from cloned repo
    async with MCPCodeExtractor(
        project_root=str(maestro_repo),
        binary_path=context_link_binary,
        timeout_seconds=120,
    ) as extractor:
        code_context = await extractor.extract_context(
            description=description,
            max_bytes=50_000,
        )

    assert code_context is not None
    assert len(code_context.files) > 0, "No code files extracted"

    # Run pipeline
    events = await _collect_events(
        anthropic_provider,
        description,
        Framework.MAESTRO,
        code_context=code_context,
        max_iterations=2,
    )

    completion_data = _assert_pipeline_completed(events)

    # Code-specific: SUMMARIZE_CODE step must have run
    step_statuses = [(e.step, e.status) for e in events]
    assert (PipelineStep.SUMMARIZE_CODE, "completed") in step_statuses, (
        "SUMMARIZE_CODE step did not complete — code context was not processed"
    )

    logger.info(
        "MAESTRO+code test passed: %d threats in %d iterations (%.1fs)",
        completion_data.get("total_threats", 0),
        completion_data.get("iterations_completed", 0),
        completion_data.get("duration_seconds", 0),
    )


# ---------------------------------------------------------------------------
# Test 3: STRIDE + PNG diagram
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e2e_stride_png_diagram(anthropic_provider):
    """Full pipeline: STRIDE framework with real PNG architecture diagram."""
    description = _read_example("stride-example-api-gateway.md")
    diagram_data = await load_diagram_file(EXAMPLES_DIR / "stride-api-gateway-architecture.png")

    # Verify diagram loaded correctly
    assert diagram_data.format == DiagramFormat.PNG
    assert diagram_data.base64_data is not None
    assert diagram_data.media_type == "image/png"
    assert diagram_data.size_bytes > 0

    events = await _collect_events(
        anthropic_provider,
        description,
        Framework.STRIDE,
        diagram_data=diagram_data,
        max_iterations=2,
    )

    completion_data = _assert_pipeline_completed(events)

    # No code context — SUMMARIZE_CODE should NOT appear
    step_statuses = [(e.step, e.status) for e in events]
    assert (PipelineStep.SUMMARIZE_CODE, "completed") not in step_statuses

    logger.info(
        "STRIDE+PNG test passed: %d threats in %d iterations (%.1fs)",
        completion_data.get("total_threats", 0),
        completion_data.get("iterations_completed", 0),
        completion_data.get("duration_seconds", 0),
    )


# ---------------------------------------------------------------------------
# Test 4: STRIDE + Mermaid diagram
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e2e_stride_mermaid_diagram(anthropic_provider):
    """Full pipeline: STRIDE framework with real Mermaid architecture diagram."""
    description = _read_example("stride-example-api-gateway.md")
    diagram_data = await load_diagram_file(EXAMPLES_DIR / "stride-api-gateway-architecture.mmd")

    # Verify diagram loaded correctly
    assert diagram_data.format == DiagramFormat.MERMAID
    assert diagram_data.mermaid_source is not None
    assert len(diagram_data.mermaid_source) > 0
    assert diagram_data.base64_data is None  # Mermaid is text, not encoded image

    events = await _collect_events(
        anthropic_provider,
        description,
        Framework.STRIDE,
        diagram_data=diagram_data,
        max_iterations=2,
    )

    completion_data = _assert_pipeline_completed(events)

    # No code context — SUMMARIZE_CODE should NOT appear
    step_statuses = [(e.step, e.status) for e in events]
    assert (PipelineStep.SUMMARIZE_CODE, "completed") not in step_statuses

    logger.info(
        "STRIDE+Mermaid test passed: %d threats in %d iterations (%.1fs)",
        completion_data.get("total_threats", 0),
        completion_data.get("iterations_completed", 0),
        completion_data.get("duration_seconds", 0),
    )


# ---------------------------------------------------------------------------
# Test 5: MAESTRO + PNG diagram
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e2e_maestro_png_diagram(anthropic_provider):
    """Full pipeline: MAESTRO framework with real PNG architecture diagram."""
    description = _read_example("maestro-example-rag-chatbot.md")
    diagram_data = await load_diagram_file(EXAMPLES_DIR / "maestro-rag-chatbot-architecture.png")

    # Verify diagram loaded correctly
    assert diagram_data.format == DiagramFormat.PNG
    assert diagram_data.base64_data is not None
    assert diagram_data.media_type == "image/png"

    events = await _collect_events(
        anthropic_provider,
        description,
        Framework.MAESTRO,
        diagram_data=diagram_data,
        max_iterations=2,
    )

    completion_data = _assert_pipeline_completed(events)

    logger.info(
        "MAESTRO+PNG test passed: %d threats in %d iterations (%.1fs)",
        completion_data.get("total_threats", 0),
        completion_data.get("iterations_completed", 0),
        completion_data.get("duration_seconds", 0),
    )


# ---------------------------------------------------------------------------
# Test 6: MAESTRO + Mermaid diagram
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e2e_maestro_mermaid_diagram(anthropic_provider):
    """Full pipeline: MAESTRO framework with real Mermaid architecture diagram."""
    description = _read_example("maestro-example-rag-chatbot.md")
    diagram_data = await load_diagram_file(EXAMPLES_DIR / "maestro-rag-chatbot-architecture.mmd")

    # Verify diagram loaded correctly
    assert diagram_data.format == DiagramFormat.MERMAID
    assert diagram_data.mermaid_source is not None
    assert len(diagram_data.mermaid_source) > 0
    assert diagram_data.base64_data is None

    events = await _collect_events(
        anthropic_provider,
        description,
        Framework.MAESTRO,
        diagram_data=diagram_data,
        max_iterations=2,
    )

    completion_data = _assert_pipeline_completed(events)

    logger.info(
        "MAESTRO+Mermaid test passed: %d threats in %d iterations (%.1fs)",
        completion_data.get("total_threats", 0),
        completion_data.get("iterations_completed", 0),
        completion_data.get("duration_seconds", 0),
    )
