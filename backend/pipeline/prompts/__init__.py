"""Prompt templates for threat modeling pipeline."""

from backend.pipeline.prompts.attack_tree import attack_tree_prompt
from backend.pipeline.prompts.maestro import (
    maestro_asset_prompt,
    maestro_gap_prompt,
    maestro_improve_prompt,
    maestro_threats_prompt,
)
from backend.pipeline.prompts.stride import (
    stride_asset_prompt,
    stride_flow_prompt,
    stride_gap_prompt,
    stride_summary_prompt,
    stride_threats_improve_prompt,
    stride_threats_prompt,
)
from backend.pipeline.prompts.test_case import test_case_prompt

__all__ = [
    # STRIDE prompts
    "stride_summary_prompt",
    "stride_asset_prompt",
    "stride_flow_prompt",
    "stride_gap_prompt",
    "stride_threats_prompt",
    "stride_threats_improve_prompt",
    # MAESTRO prompts
    "maestro_asset_prompt",
    "maestro_threats_prompt",
    "maestro_gap_prompt",
    "maestro_improve_prompt",
    # Attack tree prompts
    "attack_tree_prompt",
    # Test case prompts
    "test_case_prompt",
]
