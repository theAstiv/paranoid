"""One pipeline run, in its own subprocess: `python -m tests.bench.run_one <run_dir> <arm.json>`.

The parent (runner.py) sets the environment (scratch DB_PATH, provider settings)
before launching this process, so backend settings are read fresh. This module:
wraps every provider's generate_structured to log one line per LLM call, runs
`paranoid run`, exports the extra formats from the saved model (no LLM spend),
and writes run.json. stdout/stderr are captured to files by the parent.
"""

import json
import os
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from tests.bench.matrix import (
    DIAGRAMS,
    FIXTURE,
    MAESTRO_DESCRIPTION,
    MAESTRO_DIAGRAM,
    PROBE_TERMS,
    Arm,
)


_TAG = re.compile(r"<architecture_diagram([^>]*)>")


def build_run_args(arm: Arm, run_dir: Path) -> list[str]:
    """The `paranoid run` argument list for an arm (pure; unit-tested)."""
    if arm.inputs == "maestro":
        args = ["run", str(MAESTRO_DESCRIPTION), "-d", str(MAESTRO_DIAGRAM)]
    else:
        args = ["run", str(FIXTURE / "description.md")]
        if arm.inputs in ("full", "full_no_diagrams"):
            args += [
                "--manifest",
                str(FIXTURE / "package.json"),
                "--lockfile",
                str(FIXTURE / "package-lock.json"),
                "--deps-source",
                arm.deps_source,
            ]
        if arm.inputs in ("full", "diagrams_only"):
            for diagram in DIAGRAMS:
                args += ["-d", str(diagram)]

    if arm.main is None:
        # Degraded arms: a provider that can't be reached, so the run exercises the
        # rule-engine fallback with zero spend (OLLAMA_BASE_URL points at a dead port).
        args += ["--provider", "ollama", "--model", "offline"]
    else:
        args += ["--provider", arm.main.provider, "--model", arm.main.model_id]
        fast = arm.fast or arm.main
        args += ["--fast-model", fast.model_id]
    for step, choice in sorted(arm.step_models.items()):
        args += ["--step-model", f"{step}={choice}"]

    args += ["-n", str(arm.iterations), "--scoring-method", arm.scoring]
    if arm.enrich:
        args.append("--enrich")
    if arm.stride_maestro:
        args.append("--stride-maestro")
    if arm.code_repo:
        args += ["--code", arm.code_repo]
    args += ["--format", "full", "-o", str(run_dir / "out.json")]
    return args


def _install_call_logger(calls_path: Path) -> None:
    """Wrap every provider class's generate_structured to append one JSON line per call."""
    import importlib

    for module_name in ("anthropic", "openai", "ollama", "bedrock"):
        try:
            module = importlib.import_module(f"backend.providers.{module_name}")
        except ImportError:  # optional extras (e.g. boto3 for bedrock) not installed
            continue
        for attr in dir(module):
            cls = getattr(module, attr)
            if not (
                isinstance(cls, type)
                and attr.endswith("Provider")
                and cls.__module__ == module.__name__
            ):
                continue
            if not hasattr(cls, "generate_structured") or getattr(
                cls.generate_structured, "_bench_wrapped", False
            ):
                continue
            cls.generate_structured = _wrap(cls.generate_structured, module_name, calls_path)


def _wrap(original, provider_name: str, calls_path: Path):
    async def logged(
        self,
        prompt,
        response_model,
        temperature=0.0,
        max_tokens=None,
        images=None,
        shared_context=None,
    ):
        text = (prompt or "") + "\n" + (shared_context or "")
        started = time.time()
        error = None
        try:
            return await original(
                self,
                prompt,
                response_model,
                temperature=temperature,
                max_tokens=max_tokens,
                images=images,
                shared_context=shared_context,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            raise
        finally:
            record = {
                "provider": provider_name,
                "model": getattr(self, "model", None),
                "response_model": getattr(response_model, "__name__", str(response_model)),
                "images": len(images or []),
                "image_sources": [getattr(i, "source", None) for i in (images or [])],
                "diagram_tags": [t for t in _TAG.findall(text) if "name=" in t],
                "probe_terms_in_prompt": {
                    k: bool(re.search(p, text, re.I)) for k, p in PROBE_TERMS.items()
                },
                "seconds": round(time.time() - started, 2),
                "error": error,
            }
            with calls_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

    logged._bench_wrapped = True
    return logged


def _saved_model_id(db_path: Path) -> str | None:
    if not db_path.is_file():
        return None
    with closing(sqlite3.connect(db_path)) as conn, conn:
        row = conn.execute(
            "SELECT id FROM threat_models ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return row[0] if row else None


def main(run_dir: Path, arm: Arm) -> int:
    from cli.main import cli

    run_dir.mkdir(parents=True, exist_ok=True)
    calls_path = run_dir / "calls.jsonl"
    _install_call_logger(calls_path)

    meta: dict = {"arm": arm.id, "started": time.time(), "args": build_run_args(arm, run_dir)}
    exit_code = 0
    try:
        cli(meta["args"], standalone_mode=False)
    except SystemExit as exc:  # click raises SystemExit for --strict and similar exits
        exit_code = int(exc.code or 0)
    except Exception as exc:  # recorded, not re-raised: the parent reads run.json
        exit_code = 1
        meta["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    meta["finished"] = time.time()

    model_id = _saved_model_id(run_dir / "paranoid.db")
    meta["model_id"] = model_id
    meta["exports"] = {}
    for fmt in arm.exports:
        if model_id is None:
            break
        suffix = {"simple": ".json", "sarif": ".sarif", "markdown": ".md", "pdf": ".pdf"}[fmt]
        path = run_dir / f"export-{fmt}{suffix}"
        try:
            cli(
                ["models", "export", model_id, "--format", fmt, "-o", str(path)],
                standalone_mode=False,
            )
            meta["exports"][fmt] = path.name
        except (SystemExit, Exception) as exc:
            meta["exports"][fmt] = f"ERROR {type(exc).__name__}: {str(exc)[:200]}"

    meta["exit_code"] = exit_code
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    _run_dir = Path(sys.argv[1])
    _arm = Arm.model_validate_json(Path(sys.argv[2]).read_text(encoding="utf-8"))
    _code = main(_run_dir, _arm)
    # A lingering aiosqlite thread can keep the interpreter alive after the CLI
    # finishes (10-09), so exit hard, after flushing what the parent reads.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_code)
