"""E2E-2/3 executor: drive the real web API (multipart run, SSE, diagram routes, exports).

Phases, all on one model record and one scratch DB:
  1. create the model, run with 3 diagrams + manifest/lockfile, consume SSE to `complete`
  2. check the list/single diagram routes and the persisted counts against the SSE totals
  3. re-run with no upload: the stored diagrams must reach the pipeline (call log)
  4. re-run uploading a set of 1: the stored set must be replaced
Writes the same run.json/out.json/calls.jsonl shape as run_one.py, plus `web_checks`.
"""

import json
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from tests.bench.config import REPO_ROOT
from tests.bench.matrix import DIAGRAMS, FIXTURE, Arm
from tests.bench.runner import RunOutcome, _kill_tree


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sse_events(
    client: httpx.Client, url: str, files: list, data: dict, timeout_s: float
) -> list[dict]:
    events = []
    with client.stream("POST", url, files=files, data=data, timeout=timeout_s) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


def _files(paths: list[Path], with_manifest: bool) -> list:
    files = [
        ("diagrams", (p.name, p.read_bytes(), "image/png" if p.suffix == ".png" else "text/plain"))
        for p in paths
    ]
    if with_manifest:
        files.append(
            (
                "dependency_manifest",
                ("package.json", (FIXTURE / "package.json").read_bytes(), "application/json"),
            )
        )
        files.append(
            (
                "dependency_lockfile",
                (
                    "package-lock.json",
                    (FIXTURE / "package-lock.json").read_bytes(),
                    "application/json",
                ),
            )
        )
    return files


def _calls_since(calls_path: Path, offset: int) -> list[dict]:
    if not calls_path.is_file():
        return []
    lines = calls_path.read_text(encoding="utf-8").splitlines()[offset:]
    return [json.loads(line) for line in lines if line.strip()]


def run_web(arm: Arm, run_dir: Path, env: dict[str, str], timeout_s: float) -> RunOutcome:
    run_dir.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    env = {**env, "ALLOWED_ORIGINS": origin, "PARANOID_REQUIRE_AUTH": "false"}
    if arm.main is not None and arm.fast is not None:
        env["FAST_MODEL_BEDROCK" if arm.main.provider == "bedrock" else "FAST_MODEL_OPENAI"] = (
            arm.fast.model_id
        )
    calls_path = run_dir / "calls.jsonl"
    started = time.time()
    meta: dict = {"arm": arm.id, "started": started, "exports": {}}
    checks: dict[str, object] = {}
    events: list[dict] = []

    with (
        (run_dir / "stdout.log").open("w", encoding="utf-8") as out,
        (run_dir / "stderr.log").open("w", encoding="utf-8") as err,
    ):
        proc = subprocess.Popen(
            [sys.executable, "-m", "tests.bench.web_server", str(calls_path), str(port)],
            cwd=REPO_ROOT,
            env=env,
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
            # Own process group, so _kill_tree's killpg reaches the server (POSIX).
            start_new_session=platform.system() != "Windows",
        )
        try:
            with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=60) as client:
                deadline = time.time() + 120
                while time.time() < deadline:
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(1)
                else:
                    raise RuntimeError("server did not become healthy within 120 s")

                model = client.post(
                    "/api/models/",
                    json={
                        "title": f"bench {arm.id}",
                        "description": (FIXTURE / "description.md").read_text(encoding="utf-8"),
                        "provider": arm.main.provider if arm.main else "ollama",
                        "model": arm.main.model_id if arm.main else "offline",
                        "iteration_count": arm.iterations,
                        "scoring_method": arm.scoring,
                    },
                ).json()
                mid = model["id"]
                meta["model_id"] = mid
                run_url = f"/api/models/{mid}/run"
                form = {
                    "assumptions": "[]",
                    "has_ai_components": "false",
                    "deps_source_mode": arm.deps_source,
                }

                # 1. first run with 3 diagrams + manifest
                events = _sse_events(
                    client,
                    run_url,
                    _files(DIAGRAMS, with_manifest=True),
                    {**form, "diagram_names": json.dumps([d.stem for d in DIAGRAMS])},
                    timeout_s,
                )
                complete = next((e for e in events if e["step"] == "complete"), None)
                checks["sse_complete"] = complete is not None
                total = (complete or {}).get("data", {}).get("total_threats")

                # 2. persisted state vs SSE, diagram routes
                threats = client.get(f"/api/models/{mid}/threats").json()
                threats = threats.get("threats", threats) if isinstance(threats, dict) else threats
                checks["persisted_threats_match_sse"] = total is not None and len(threats) == total
                listed = client.get(f"/api/models/{mid}/diagrams").json()
                checks["three_diagrams_listed_in_order"] = [d["name"] for d in listed] == [
                    d.stem for d in DIAGRAMS
                ]
                png = next((d for d in listed if d["kind"] == "png"), None)
                checks["list_omits_image_bytes"] = (
                    bool(png) and png.get("content") is None and png.get("has_content") is False
                )
                if png:
                    single = client.get(f"/api/models/{mid}/diagrams/{png['id']}").json()
                    checks["single_route_returns_bytes"] = bool(single.get("content"))
                checks["dependencies_listed"] = (
                    len(client.get(f"/api/models/{mid}/dependencies").json()) > 0
                )
                for fmt in arm.exports:
                    resp = client.get(
                        f"/api/export/{mid}", params={"format": "json" if fmt == "simple" else fmt}
                    )
                    suffix = {
                        "simple": ".json",
                        "sarif": ".sarif",
                        "markdown": ".md",
                        "pdf": ".pdf",
                    }[fmt]
                    path = run_dir / f"export-{fmt}{suffix}"
                    if resp.status_code == 200:
                        path.write_bytes(resp.content)
                        meta["exports"][fmt] = path.name
                    else:
                        meta["exports"][fmt] = f"ERROR HTTP {resp.status_code}"

                # 3. re-run with no upload: stored diagrams reused
                offset = (
                    len(calls_path.read_text(encoding="utf-8").splitlines())
                    if calls_path.is_file()
                    else 0
                )
                rerun = _sse_events(client, run_url, [], form, timeout_s)
                checks["rerun_complete"] = any(e["step"] == "complete" for e in rerun)
                rerun_calls = _calls_since(calls_path, offset)
                tags = max((len(c.get("diagram_tags", [])) for c in rerun_calls), default=0)
                checks["rerun_reused_stored_diagrams"] = tags == len(DIAGRAMS)

                # 4. upload a set of 1: replaces the stored 3
                one = [DIAGRAMS[1]]
                _sse_events(
                    client,
                    run_url,
                    _files(one, with_manifest=False),
                    {**form, "diagram_names": json.dumps([one[0].stem])},
                    timeout_s,
                )
                after = client.get(f"/api/models/{mid}/diagrams").json()
                checks["upload_replaces_set"] = [d["name"] for d in after] == [one[0].stem]
            meta["exit_code"] = 0
        except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as exc:
            meta["exit_code"] = 1
            meta["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        finally:
            # Teardown must never block the suite (10-09: a failed killpg left wait() hanging).
            try:
                _kill_tree(proc)
                proc.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired) as exc:
                meta.setdefault("teardown_error", f"{type(exc).__name__}: {exc}")

    complete = next((e for e in events if e["step"] == "complete"), {})
    data = complete.get("data") or {}
    out_json = {
        "execution": {
            "status": "completed" if complete else "failed",
            "iterations_completed": data.get("iterations_completed"),
            "duration_seconds": data.get("duration_seconds"),
            "stopped_reason": data.get("stopped_reason"),
            "total_threats": data.get("total_threats"),
        },
        "events": [
            {k: e.get(k) for k in ("step", "status", "message", "iteration")} for e in events
        ],
    }
    (run_dir / "out.json").write_text(json.dumps(out_json, indent=2), encoding="utf-8")
    meta["finished"] = time.time()
    meta["web_checks"] = checks
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return RunOutcome(exit_code=meta["exit_code"], timed_out=False, seconds=time.time() - started)
