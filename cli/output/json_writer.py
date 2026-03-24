"""JSON export functionality for CLI.

Aggregates pipeline events and exports to structured JSON with two formats:
- Simple: Events + execution metadata (lightweight)
- Full: Complete Pydantic models + events (comprehensive)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.models.enums import Framework
from backend.models.state import AssetsList, FlowsList, ThreatsList
from backend.pipeline.runner import PipelineEvent, PipelineStep
from cli.errors import OutputWriteError


def _format_timestamp(timestamp: datetime | float | None) -> str | None:
    """Convert timestamp to ISO format string.

    Args:
        timestamp: Datetime object, Unix timestamp (float), or None

    Returns:
        ISO format string or None
    """
    if timestamp is None:
        return None
    if isinstance(timestamp, datetime):
        return timestamp.isoformat()
    # Handle float/int Unix timestamps
    return datetime.fromtimestamp(timestamp).isoformat()


class JSONWriter:
    """Aggregates pipeline events and exports to JSON."""

    def __init__(self, model_id: str, input_file: Path, framework: Framework):
        """Initialize JSON writer.

        Args:
            model_id: Unique model identifier
            input_file: Input file path
            framework: Framework used (STRIDE or MAESTRO)
        """
        self.model_id = model_id
        self.input_file = input_file
        self.framework = framework
        self.events: list[PipelineEvent] = []
        self.start_time = datetime.now()

        # Track pipeline artifacts
        self.summary: str | None = None
        self.assets: AssetsList | None = None
        self.flows: FlowsList | None = None
        self.threats: ThreatsList | None = None

        # Track execution metadata
        self.iterations_completed = 0
        self.total_threats = 0
        self.asset_count = 0
        self.flow_count = 0
        self.stopped_reason: str | None = None

    def add_event(self, event: PipelineEvent) -> None:
        """Add pipeline event to aggregation.

        Args:
            event: Pipeline event to add
        """
        self.events.append(event)

        # Extract artifacts from completed steps
        if event.status == "completed" and event.data:
            if event.step == PipelineStep.SUMMARIZE:
                if "summary" in event.data:
                    self.summary = event.data["summary"]

            elif event.step == PipelineStep.EXTRACT_ASSETS:
                if "assets" in event.data:
                    self.assets = event.data["assets"]
                if "asset_count" in event.data:
                    self.asset_count = event.data["asset_count"]

            elif event.step == PipelineStep.EXTRACT_FLOWS:
                if "flows" in event.data:
                    self.flows = event.data["flows"]
                if "flow_count" in event.data:
                    self.flow_count = event.data["flow_count"]

            elif event.step == PipelineStep.GENERATE_THREATS:
                if "threats" in event.data:
                    # In dual framework mode, only accumulate the COMBINED event
                    # to avoid double-counting STRIDE + MAESTRO separately
                    framework = event.data.get("framework")
                    if framework in (None, "COMBINED"):
                        # Accumulate threats from each iteration
                        if self.threats is None:
                            self.threats = event.data["threats"]
                        else:
                            # Merge threat lists
                            self.threats.threats.extend(event.data["threats"].threats)

                # Update total count (only count COMBINED or single-framework events)
                if "threat_count" in event.data:
                    framework = event.data.get("framework")
                    if framework in (None, "COMBINED"):
                        self.total_threats = event.data["threat_count"]

            elif event.step == PipelineStep.GAP_ANALYSIS:
                if event.iteration:
                    self.iterations_completed = event.iteration

            elif event.step == PipelineStep.COMPLETE:
                # Extract final stats
                if "total_threats" in event.data:
                    self.total_threats = event.data["total_threats"]
                if "iterations_completed" in event.data:
                    self.iterations_completed = event.data["iterations_completed"]
                if "stopped_reason" in event.data:
                    self.stopped_reason = event.data["stopped_reason"]

    def export_simple(self, output_path: Path) -> None:
        """Export simple JSON format (lightweight, no events or full models).

        Args:
            output_path: Path to write JSON file

        Raises:
            OutputWriteError: If export fails
        """
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        # Build simple JSON structure (lightweight threats, no events, no full Pydantic models)
        simplified_threats = None
        if self.threats:
            simplified_threats = [
                {
                    "name": threat.name,
                    "category": threat.stride_category if hasattr(threat, "stride_category") else None,
                    "target": threat.target,
                    "impact": threat.impact,
                    "likelihood": threat.likelihood,
                    "mitigation_count": len(threat.mitigations),
                }
                for threat in self.threats.threats
            ]

        data = {
            "version": "1.0.0",
            "model_id": self.model_id,
            "created_at": self.start_time.isoformat(),
            "config": {
                "framework": self.framework.value,
                "input_file": self.input_file.name,
            },
            "execution": {
                "status": "completed",
                "iterations_completed": self.iterations_completed,
                "duration_seconds": round(duration, 1),
                "stopped_reason": self.stopped_reason or "max_iterations",
                "total_threats": self.total_threats,
                "asset_count": self.asset_count,
                "flow_count": self.flow_count,
            },
            "summary": self.summary,
            "threats": simplified_threats,
        }

        # Write to file
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            raise OutputWriteError(
                f"Failed to write JSON output\n\n"
                f"Output path: {output_path}\n"
                f"Error: {e}"
            ) from e

    def export_full(self, output_path: Path) -> None:
        """Export full JSON format (complete Pydantic models + events).

        Args:
            output_path: Path to write JSON file

        Raises:
            OutputWriteError: If export fails
        """
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        # Build full JSON structure (includes all Pydantic models)
        data = {
            "version": "1.0.0",
            "model_id": self.model_id,
            "created_at": self.start_time.isoformat(),
            "config": {
                "framework": self.framework.value,
                "input_file": self.input_file.name,
            },
            "execution": {
                "status": "completed",
                "iterations_completed": self.iterations_completed,
                "duration_seconds": round(duration, 1),
                "stopped_reason": self.stopped_reason or "max_iterations",
                "total_threats": self.total_threats,
                "asset_count": self.asset_count,
                "flow_count": self.flow_count,
            },
            "summary": self.summary,
            # Complete Pydantic model dumps
            "assets": self.assets.model_dump(mode="json") if self.assets else None,
            "flows": self.flows.model_dump(mode="json") if self.flows else None,
            "threats": self.threats.model_dump(mode="json") if self.threats else None,
            # Event history
            "events": [
                {
                    "step": event.step.value if isinstance(event.step, PipelineStep) else event.step,
                    "status": event.status,
                    "message": event.message,
                    "iteration": event.iteration,
                    "timestamp": _format_timestamp(event.timestamp),
                }
                for event in self.events
            ],
        }

        # Write to file
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            raise OutputWriteError(
                f"Failed to write JSON output\n\n"
                f"Output path: {output_path}\n"
                f"Error: {e}"
            ) from e


def get_default_output_path(input_file: Path) -> Path:
    """Get default output path based on input file name.

    Args:
        input_file: Input file path

    Returns:
        Default output path: {input_basename}_threats.json
    """
    return input_file.parent / f"{input_file.stem}_threats.json"
