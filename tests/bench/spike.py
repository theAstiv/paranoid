"""Phase 0 capability spike (SB1, SB2, SB3, SB4, SB5) for every Bedrock slot set in bench.env.

Raw boto3 Converse calls (so provider-side error text is visible verbatim), then the
real BedrockProvider path. Each check is one tiny call; the whole spike is a few
thousand tokens per model. Writes <out_dir>/spike-<date>.md and spike-<date>.json.
"""

import asyncio
import io
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from tests.bench.config import ResolvedModel


class _Probe(BaseModel):
    value: str
    count: int


class _Threats(BaseModel):
    threats: list[str]


_TOOL = {
    "toolSpec": {
        "name": "respond",
        "description": "Respond with structured JSON conforming to the provided schema.",
        "inputSchema": {"json": _Probe.model_json_schema()},
    }
}
_SAY = [{"role": "user", "content": [{"text": "Return value='ok' and count=1."}]}]


def _png_bytes() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (160, 80), (255, 255, 255))
    ImageDraw.Draw(img).rectangle([10, 10, 150, 70], outline=(0, 0, 0), width=3)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _call(client, **kwargs) -> dict:
    started = time.time()
    try:
        resp = client.converse(**kwargs)
        blocks = [
            next(iter(b)) for b in resp.get("output", {}).get("message", {}).get("content", [])
        ]
        return {
            "ok": True,
            "stop_reason": resp.get("stopReason"),
            "blocks": blocks,
            "usage": resp.get("usage"),
            "seconds": round(time.time() - started, 2),
        }
    except Exception as exc:  # the verbatim error text is the result we want
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {str(exc)[:400]}",
            "seconds": round(time.time() - started, 2),
        }


def probe_model(client, model: ResolvedModel) -> dict:
    mid = model.model_id
    base = {"modelId": mid, "inferenceConfig": {"maxTokens": 256}}
    checks = {
        "text": _call(
            client,
            **base,
            messages=[{"role": "user", "content": [{"text": "Reply with the single word OK."}]}],
        ),
        "system_block": _call(
            client,
            **base,
            system=[{"text": "You answer in one word."}],
            messages=[{"role": "user", "content": [{"text": "Say OK."}]}],
        ),
        "temperature": _call(
            client,
            modelId=mid,
            inferenceConfig={"maxTokens": 64, "temperature": 0.0},
            messages=[{"role": "user", "content": [{"text": "Say OK."}]}],
        ),
        "max_tokens_32768": _call(
            client,
            modelId=mid,
            inferenceConfig={"maxTokens": 32768},
            messages=[{"role": "user", "content": [{"text": "Say OK."}]}],
        ),
        "forced_tool": _call(
            client,
            **base,
            messages=_SAY,
            toolConfig={"tools": [_TOOL], "toolChoice": {"tool": {"name": "respond"}}},
        ),
        "auto_tool": _call(
            client,
            **base,
            messages=_SAY,
            system=[{"text": "Answer by calling the `respond` tool."}],
            toolConfig={"tools": [_TOOL], "toolChoice": {"auto": {}}},
        ),
        "image": _call(
            client,
            **base,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": {"format": "png", "source": {"bytes": _png_bytes()}}},
                        {"text": "What shape is in the image? One word."},
                    ],
                }
            ],
        ),
    }
    if model.family == "claude":
        checks["effort_field"] = _call(
            client,
            **base,
            messages=[{"role": "user", "content": [{"text": "Say OK."}]}],
            additionalModelRequestFields={"output_config": {"effort": "medium"}},
        )
    return checks


async def provider_path(model: ResolvedModel, region: str, profile: str) -> dict:
    from backend.providers.bedrock import BedrockProvider

    out = {}
    provider = BedrockProvider(model=model.model_id, region=region, profile=profile)
    for name, (prompt, schema) in {
        "structured_probe": ("Return value='ok' and count=1.", _Probe),
        "threat_prompt": (
            "List three STRIDE threats for a public image-upload API that calls partner-registered webhooks.",
            _Threats,
        ),
    }.items():
        started = time.time()
        try:
            result = await provider.generate_structured(prompt, schema, max_tokens=1024)
            out[name] = {
                "ok": True,
                "result": result.model_dump(),
                "seconds": round(time.time() - started, 2),
            }
        except Exception as exc:
            out[name] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {str(exc)[:400]}",
                "seconds": round(time.time() - started, 2),
            }
    return out


def list_account_models(region: str, profile: str) -> dict:
    import boto3

    session = boto3.Session(profile_name=profile or None, region_name=region or None)
    ctl = session.client("bedrock")
    out: dict = {}
    try:
        out["foundation_models"] = [
            {
                "id": m["modelId"],
                "input": m.get("inputModalities"),
                "output": m.get("outputModalities"),
                "inference_types": m.get("inferenceTypesSupported"),
            }
            for m in ctl.list_foundation_models()["modelSummaries"]
        ]
    except Exception as exc:
        out["foundation_models_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    try:
        out["inference_profiles"] = [
            p["inferenceProfileId"]
            for p in ctl.list_inference_profiles()["inferenceProfileSummaries"]
        ]
    except Exception as exc:
        out["inference_profiles_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return out


def _cell(check: dict | None) -> str:
    if check is None:
        return "-"
    if check["ok"]:
        return f"ok ({check.get('stop_reason', '')})" if check.get("stop_reason") else "ok"
    return "FAIL"


def render(results: dict) -> str:
    cols = [
        "text",
        "system_block",
        "temperature",
        "max_tokens_32768",
        "forced_tool",
        "auto_tool",
        "image",
        "effort_field",
        "structured_probe",
        "threat_prompt",
    ]
    lines = [
        f"# Bedrock spike - {datetime.now(UTC).date().isoformat()}",
        "",
        "| Slot | Model ID | " + " | ".join(cols) + " |",
        "|---|---|" + "---|" * len(cols),
    ]
    errors = []
    for slot, r in results["models"].items():
        merged = {**r["converse"], **r["provider"]}
        lines.append(
            f"| {slot} | `{r['model_id']}` | "
            + " | ".join(_cell(merged.get(c)) for c in cols)
            + " |"
        )
        errors += [
            f"- **{slot} / {c}**: `{merged[c]['error']}`"
            for c in cols
            if merged.get(c) and not merged[c]["ok"]
        ]
    if errors:
        lines += ["", "## Errors (verbatim)", "", *errors]
    return "\n".join(lines) + "\n"


def run_spike(models: list[ResolvedModel], region: str, profile: str, out_dir: Path) -> Path:
    import boto3

    session = boto3.Session(profile_name=profile or None, region_name=region or None)
    client = session.client("bedrock-runtime")
    results: dict = {
        "date": datetime.now(UTC).date().isoformat(),
        "region": region,
        "account_models": list_account_models(region, profile),
        "models": {},
    }
    for model in models:
        if model.provider != "bedrock":
            continue
        print(f"probing {model.slot} ({model.model_id})")
        results["models"][model.slot] = {
            "model_id": model.model_id,
            "converse": probe_model(client, model),
            "provider": asyncio.run(provider_path(model, region, profile)),
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"spike-{datetime.now(UTC).date().isoformat()}"
    stem.with_suffix(".json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8"
    )
    report = stem.with_suffix(".md")
    report.write_text(render(results), encoding="utf-8")
    return report
