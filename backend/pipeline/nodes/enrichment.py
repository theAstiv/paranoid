"""Threat enrichment nodes for attack trees and test cases.

Contains generate_attack_tree() for visualizing attack paths as Mermaid graphs,
and generate_test_cases() for creating Gherkin BDD test scenarios.
"""

from backend.models.extended import AttackTree, TestSuite
from backend.pipeline.nodes.helpers import build_xml_tag
from backend.pipeline.prompts import attack_tree_prompt, test_case_prompt
from backend.providers.base import LLMProvider


async def generate_attack_tree(
    threat: str,
    threat_description: str,
    target: str,
    stride_category: str | None,
    maestro_category: str | None,
    mitigations: list[str],
    provider: LLMProvider,
    temperature: float = 0.3,
) -> AttackTree:
    """Generate attack tree for a specific threat.

    Args:
        threat: Threat name
        threat_description: Detailed threat description
        target: Target asset/component
        stride_category: Optional STRIDE category
        maestro_category: Optional MAESTRO category
        mitigations: List of mitigations
        provider: LLM provider
        temperature: Sampling temperature (slightly higher for creativity)

    Returns:
        AttackTree with Mermaid.js graph
    """
    system_prompt = attack_tree_prompt()

    # Build prompt
    prompt_parts = [
        build_xml_tag("threat_name", threat),
        build_xml_tag("threat_description", threat_description),
        build_xml_tag("target", target),
    ]

    if stride_category:
        prompt_parts.append(build_xml_tag("stride_category", stride_category))

    if maestro_category:
        prompt_parts.append(build_xml_tag("maestro_category", maestro_category))

    mitigations_text = "\n".join(f"- {mitigation}" for mitigation in mitigations)
    prompt_parts.append(build_xml_tag("mitigations", mitigations_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=AttackTree,
        temperature=temperature,
    )

    return response


async def generate_test_cases(
    threat: str,
    threat_description: str,
    target: str,
    mitigations: list[str],
    provider: LLMProvider,
    temperature: float = 0.3,
) -> TestSuite:
    """Generate Gherkin test cases for a specific threat.

    Args:
        threat: Threat name
        threat_description: Detailed threat description
        target: Target asset/component
        mitigations: List of mitigations to validate
        provider: LLM provider
        temperature: Sampling temperature

    Returns:
        TestSuite with Gherkin feature and scenarios
    """
    system_prompt = test_case_prompt()

    # Build prompt
    prompt_parts = [
        build_xml_tag("threat_name", threat),
        build_xml_tag("threat_description", threat_description),
        build_xml_tag("target", target),
    ]

    mitigations_text = "\n".join(f"- {mitigation}" for mitigation in mitigations)
    prompt_parts.append(build_xml_tag("mitigations", mitigations_text))

    user_prompt = "".join(prompt_parts)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Generate structured output
    response = await provider.generate_structured(
        prompt=full_prompt,
        response_model=TestSuite,
        temperature=temperature,
    )

    return response
