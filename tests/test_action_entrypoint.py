"""action/entrypoint.sh: inputs → `paranoid run` arguments, with a stub `paranoid`.

Runs the real script under bash, with a fake `paranoid` on PATH that records its
arguments, so no provider, network or Docker image is involved.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


_ENTRYPOINT = Path(__file__).resolve().parent.parent / "action" / "entrypoint.sh"
_BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    _BASH is None or "system32" in _BASH.lower(), reason="needs a POSIX bash (not WSL's)"
)


@pytest.fixture
def action(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "system.md").write_text("A web app")
    (workspace / "apps").mkdir()
    (workspace / "apps" / "package.json").write_text("{}")
    (workspace / "apps" / "package-lock.json").write_text("{}")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "args.txt"
    stub = bin_dir / "paranoid"
    stub.write_bytes(b'#!/bin/bash\nprintf "%s\\n" "$@" > "$ARGS_FILE"\n')
    stub.chmod(0o755)

    # The checkout may have CRLF line endings on Windows; bash needs LF.
    script = tmp_path / "entrypoint.sh"
    script.write_bytes(_ENTRYPOINT.read_bytes().replace(b"\r\n", b"\n"))

    def run(**inputs: str) -> tuple[subprocess.CompletedProcess, list[str], dict]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUT_")}
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
            ARGS_FILE=str(args_file),
            GITHUB_WORKSPACE=str(workspace),
            GITHUB_OUTPUT=str(tmp_path / "github_output"),
            INPUT_DESCRIPTION_FILE="system.md",
            INPUT_API_KEY="sk-test",
        )
        env.update({f"INPUT_{k.upper()}": v for k, v in inputs.items()})
        if args_file.exists():
            args_file.unlink()
        result = subprocess.run(  # noqa: S603 - fixed script, test-controlled args
            [_BASH, str(script)], env=env, capture_output=True, text=True, check=False
        )
        args = args_file.read_text().splitlines() if args_file.exists() else []
        return result, args, env

    run.workspace = workspace
    return run


def _value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_defaults_pass_scoring_and_no_dependency_flags(action):
    result, args, _ = action()
    assert result.returncode == 0, result.stderr
    assert _value(args, "--scoring-method") == "dread"
    assert "--manifest" not in args
    assert not any(a.startswith("--fast-model") for a in args)


def test_manifest_lockfile_and_deps_source_reach_the_cli(action):
    result, args, _ = action(
        manifest="apps/package.json",
        lockfile="apps/package-lock.json",
        deps_source="both",
        scoring_method="both",
    )
    assert result.returncode == 0, result.stderr
    assert _value(args, "--manifest").endswith("/apps/package.json")
    assert _value(args, "--lockfile").endswith("/apps/package-lock.json")
    assert _value(args, "--deps-source") == "both"
    assert _value(args, "--scoring-method") == "both"


def test_lockfile_without_manifest_is_rejected(action):
    result, args, _ = action(lockfile="apps/package-lock.json")
    assert result.returncode == 1
    assert "requires 'manifest'" in result.stdout
    assert args == []


def test_missing_manifest_file_is_rejected(action):
    result, args, _ = action(manifest="apps/nope.json")
    assert result.returncode == 1
    assert "Dependency file not found" in result.stdout
    assert args == []


def test_fast_model_value_and_none(action):
    _, args, _ = action(fast_model="claude-haiku-5-5")
    assert _value(args, "--fast-model") == "claude-haiku-5-5"
    _, args, _ = action(fast_model="none")
    assert "--fast-model=" in args


def test_bedrock_needs_no_api_key(action):
    result, args, _ = action(provider="bedrock", api_key="", aws_region="us-east-2")
    assert result.returncode == 0, result.stderr
    assert _value(args, "--provider") == "bedrock"


def test_anthropic_still_requires_an_api_key(action):
    result, _, _ = action(api_key="")
    assert result.returncode == 1
    assert "'api-key' is required" in result.stdout
