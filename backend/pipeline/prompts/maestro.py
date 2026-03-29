"""MAESTRO ML/AI security threat modeling prompts.

This module provides prompts for ML/AI-specific threat modeling using the MAESTRO framework.
These prompts are designed for identifying threats unique to machine learning systems.
"""

from backend.models.enums import ImpactLevel, LikelihoodLevel, MaestroCategory
from backend.models.state import (
    MITIGATION_MAX_ITEMS,
    MITIGATION_MIN_ITEMS,
    THREAT_DESCRIPTION_MAX_WORDS,
    THREAT_DESCRIPTION_MIN_WORDS,
)


def _get_maestro_categories_string() -> str:
    """Helper function to get MAESTRO categories as a formatted string."""
    return " | ".join([category.value for category in MaestroCategory])


def _get_impact_levels_string() -> str:
    """Helper function to get impact levels as a formatted string."""
    return " | ".join([level.value for level in ImpactLevel])


def _get_likelihood_levels_string() -> str:
    """Helper function to get likelihood levels as a formatted string."""
    return " | ".join([level.value for level in LikelihoodLevel])


def maestro_asset_prompt() -> str:
    """Generate prompt for ML/AI asset identification."""
    return """<instruction>
You are an expert in ML/AI security and threat modeling. Your role is to carefully review a given ML/AI system architecture and identify key ML-specific assets and entities that require protection. Follow these steps:

1. Review the provided inputs carefully:

      * <architecture_diagram>: Architecture diagram of the ML/AI solution
      * <description>: Description of the ML/AI system
      * <assumptions>: Assumptions about the ML/AI deployment
      * <code_summary>: Security-focused analysis of the system's source code (if available).
        Identify ML pipeline components visible in the code — model.fit()/model.predict() call sites,
        model registries (MLflow, W&B), feature stores, training data loaders, vector databases,
        embedding generation, and GPU/TPU resource allocation. Look for model serialization formats
        (pickle, torch.save, ONNX, SavedModel) as these determine model integrity attack surface.

2. Identify ML/AI-specific assets, such as:
   - **Models**: Trained model weights, model architectures, model cards
   - **Training Data**: Datasets used for training, validation, test sets
   - **Inference Data**: Input features, prediction outputs, feedback loops
   - **ML Infrastructure**: Training clusters, model registries, feature stores, experiment tracking
   - **ML Pipelines**: Data preprocessing, feature engineering, model training, deployment pipelines
   - **Embeddings & Vectors**: Vector databases, embedding models, similarity indices

3. Identify ML/AI-specific entities:
   - **Data Scientists/ML Engineers**: Personnel with access to models and data
   - **Automated ML Systems**: AutoML platforms, model training orchestrators
   - **Model Serving Infrastructure**: Inference endpoints, model servers, API gateways
   - **End Users**: Users interacting with ML predictions

4. For each identified ML/AI asset or entity, provide:

Type: [Asset or Entity]
Name: [ML Asset/Entity Name]
Description: [Brief description emphasizing ML-specific characteristics]
</instruction>
"""


def maestro_threats_prompt() -> str:
    """Generate prompt for MAESTRO ML/AI threat identification."""
    maestro_cats = _get_maestro_categories_string()
    impact_levels = _get_impact_levels_string()
    likelihood_levels = _get_likelihood_levels_string()

    return f"""
<task>
You are an expert in ML/AI security and threat modeling. Your goal is to generate a comprehensive list of ML/AI-specific security threats for a given ML/AI system using the MAESTRO framework. Focus on threats unique to machine learning systems that wouldn't apply to traditional software.
</task>

<instructions>

1. Review the inputs carefully:

   * <architecture_diagram>: Architecture diagram of the ML/AI solution
   * <identified_assets_and_entities>: Inventory of ML/AI assets and entities
   * <data_flow>: ML pipeline data flows (training, inference, feedback)
   * <description>: System description
   * <assumptions>: ML deployment assumptions
   * <code_summary>: Security-focused analysis of the system's source code (if available).
     Ground ML threats in actual implementation — torch.load() without integrity checks (arbitrary
     code execution via pickle), training data loaded from unvalidated URLs (data poisoning),
     model serving endpoints without rate limiting (model extraction), prompt templates with
     user-controlled variables (prompt injection), eval()/exec() on model outputs (code injection),
     and gradient computation exposed to API callers (adversarial example generation).

2. MAESTRO threat modeling framework:

   Use the **MAESTRO framework** for ML/AI threats: {maestro_cats}

   **MAESTRO Categories Defined:**
   - **Model Security**: Threats to model integrity (extraction, inversion, backdoors)
   - **Data Security**: Threats to training/inference data (poisoning, integrity)
   - **LLM Security**: LLM-specific threats (prompt injection, jailbreaking)
   - **Privacy**: Privacy violations (membership inference, attribute inference)
   - **Supply Chain**: Compromised pre-trained models, ML libraries, datasets
   - **Resource Abuse**: Inference cost attacks, training resource exhaustion
   - **Pipeline Security**: Training-serving skew, data pipeline vulnerabilities
   - **Reinforcement Learning**: RL-specific threats (reward hacking, unsafe exploration)
   - **Distributed ML**: Federated learning attacks (gradient leakage, poisoning)
   - **Monitoring**: Drift detection bypass, explainability manipulation
   - **Interpretability**: Adversarial explanations, explanation gaming
   - **AutoML**: Hyperparameter manipulation, architecture search poisoning
   - **Fairness**: Bias amplification, fairness gaming

3. ML/AI-specific threat actors:

   **Consider these ML-specific threat scenarios:**
   - **Model Extraction Attackers**: Systematically query APIs to steal model functionality
   - **Data Poisoning Actors**: Inject malicious examples into training pipelines
   - **Adversarial Example Crafters**: Create imperceptible perturbations to fool models
   - **Privacy Attackers**: Reconstruct training data through inference queries
   - **Supply Chain Compromisers**: Distribute backdoored pre-trained models
   - **Cost Exhaustion Attackers**: Exploit expensive inference operations

4. Use this ML/AI threat grammar template:

   <ml_threat_grammar>
   [Attacker with specific access to ML system] can [ML-specific attack method] by [ML attack vector], leading to [ML security impact], affecting [ML asset/stakeholder].
   </ml_threat_grammar>

5. DREAD Risk Scoring for ML/AI Threats:

   Use ONLY these anchor values: **0, 2.5, 5, 7.5, 10**

   ### ML/AI-SPECIFIC DREAD SCORING RUBRIC

   * **1. Damage Potential (ML/AI Impact)**:
     - 0 = No ML-specific damage or impact
     - 2.5 = Minor model performance degradation, non-critical predictions affected
     - 5 = Model misclassification on specific inputs, individual training samples leaked
     - 7.5 = Training data leakage, model theft, significant performance degradation
     - 10 = Complete model compromise, full dataset extraction, model backdoor activated

   * **2. Reproducibility (ML Attack Reliability)**:
     - 0 = Cannot be reliably reproduced, highly experimental attack
     - 2.5 = Requires rare model state, specific training conditions, or rare data distributions
     - 5 = Complex but predictable. Works on models trained with common configurations
     - 7.5 = Consistently reproducible across different model versions with a few simple steps
     - 10 = Guaranteed. Always works on any instance of the ML system

   * **3. Exploitability (ML Attack Skill/Effort)**:
     - 0 = Requires state-of-the-art ML research capabilities, novel attack development
     - 2.5 = Requires custom ML attack tools, research expertise, or gradient access
     - 5 = Can use existing adversarial ML frameworks (ART, Foolbox, CleverHans)
     - 7.5 = Available as open-source attack scripts, simple API manipulation
     - 10 = Exploit via standard API calls with basic ML knowledge, no special tools

   * **4. Affected Users (ML System Blast Radius)**:
     - 0 = No users affected, attack has no observable impact
     - 2.5 = Only affects attacker's own queries or isolated test instances
     - 5 = Affects a subset of inference requests, specific user cohort, or data slice
     - 7.5 = Affects all queries to specific model endpoints or entire model version
     - 10 = Compromises entire ML platform for all users, all models affected

   * **5. Discoverability (ML Vulnerability Detection)**:
     - 0 = Requires access to model internals, training code, and weights
     - 2.5 = Requires systematic ML model probing, white-box access, or gradient inspection
     - 5 = Visible through model behavior analysis, confidence score patterns
     - 7.5 = Obvious from API response patterns, model cards, or public documentation
     - 10 = Publicly documented model vulnerabilities, CVEs, or blatant misconfigurations

6. ML/AI Threat Coverage Requirements:

   **Ensure coverage across ML lifecycle stages:**
   - **Data Collection**: Data provenance, labeling integrity
   - **Model Training**: Training data poisoning, backdoor insertion
   - **Model Evaluation**: Test set contamination, evaluation metric gaming
   - **Model Deployment**: Model theft, serving infrastructure compromise
   - **Inference**: Adversarial examples, inference cost attacks
   - **Monitoring**: Drift detection bypass, explainability manipulation
   - **Feedback**: Feedback loop poisoning, online learning attacks

7. Format each ML/AI threat as follows:

   **Threat Name**: [Clear ML/AI-specific descriptive title]
   **MAESTRO Category**: [{maestro_cats}]
   **Severity Class**: [Critical / High / Medium / Low - based on DREAD total]
   **Description**: [Use <ml_threat_grammar>; {THREAT_DESCRIPTION_MIN_WORDS}–{THREAT_DESCRIPTION_MAX_WORDS} words]
   **Target**: [Specific ML asset: model, training data, inference pipeline, etc.]
   **Impact**: [{impact_levels}]
   **Likelihood**: [{likelihood_levels}]
   **DREAD Assessment**:
     - Damage: [Value]
     - Reproducibility: [Value]
     - Exploitability: [Value]
     - Affected Users: [Value]
     - Discoverability: [Value]
     - Total Score: [Sum: 0-50]
   **Mitigations**:
     1. [P] [ML-specific preventive control]
     2. [D] [ML monitoring/detection mechanism]
     3. [C] [ML-specific containment strategy]
   ... (provide {MITIGATION_MIN_ITEMS}–{MITIGATION_MAX_ITEMS} ML-specific mitigations)

8. ML/AI-Specific Mitigation Categories:

   **Preventive Controls:**
   - Differential privacy during training
   - Adversarial training with robust examples
   - Input validation and sanitization for prompts
   - Model watermarking and signing
   - Data provenance tracking

   **Detective Controls:**
   - Model drift monitoring
   - Anomaly detection on inference patterns
   - Prediction confidence monitoring
   - Model behavior testing (metamorphic testing)
   - Privacy budget tracking

   **Containment Controls:**
   - Rate limiting per API key
   - Query result caching
   - Model ensemble voting
   - Confidence thresholding
   - Graceful degradation

9. Quality control checklist for ML/AI threats:

   * [ ] Is this threat specific to ML/AI systems (not applicable to traditional software)?
   * [ ] Does the threat leverage ML-specific attack vectors?
   * [ ] Are mitigations ML-aware (not just generic security controls)?
   * [ ] Is the MAESTRO category appropriate for this ML threat?
   * [ ] Does the DREAD scoring reflect ML-specific risk factors?
   * [ ] Are attack chain implications considered (e.g., model extraction enabling adversarial examples)?

10. DREAD Severity Distribution and Balanced Scoring:

    **CRITICAL REQUIREMENT:** Generate ML/AI threats across ALL severity levels, not just Critical/High.
    Your threat catalog MUST include a realistic distribution of severities.

    **Total Risk Rating Thresholds (Sum: 0-50):**
    * **Critical (DREAD 40-50):** Stop the line. Immediate hotfix. Model deployment halt.
    * **High (DREAD 25-39):** Must be mitigated before production. Model retraining/patching required.
    * **Medium (DREAD 11-24):** Scheduled for resolution in upcoming sprint. Monitoring enhanced.
    * **Low (DREAD 1-10):** Standard backlog. Defense-in-depth gaps, best practice violations.

    **Target Distribution for ML/AI Threats (8-12 threats):**
    * Critical: 1-2 threats (model theft, full data extraction, model backdoors)
    * High: 2-3 threats (privacy violations, significant poisoning, adversarial attacks)
    * Medium: 3-4 threats (drift issues, minor biases, configuration weaknesses)
    * Low: 1-2 threats (logging gaps, monitoring issues, documentation deficiencies)

    **ANTI-PATTERN WARNING:** DO NOT inflate DREAD scores to make ML threats seem more severe than they are. Score honestly based on actual ML-specific impact and exploitability.

</instructions>
"""


def maestro_gap_prompt() -> str:
    """Generate prompt for ML/AI threat catalog gap analysis."""
    maestro_cats = _get_maestro_categories_string()

    return f"""
<task>
You are an expert in ML/AI security. Validate the comprehensiveness of an ML/AI threat catalog against the MAESTRO framework. Identify gaps in coverage specific to machine learning security threats.
</task>

<instructions>

1. Review the inputs:

   * <architecture_diagram>: ML/AI system architecture
   * <identified_assets_and_entities>: ML/AI assets inventory
   * <data_flow>: ML pipeline flows
   * <threats>: Existing ML/AI threat catalog
   * <description>: System context
   * <assumptions>: ML deployment assumptions. **CRITICAL**: You MUST respect these assumptions when assessing gaps. Do not suggest threats that violate stated assumptions or are explicitly out-of-scope. Focus your gap analysis on areas marked as in-scope, AI-specific considerations, and threat modeling focus areas.
   * <code_summary>: Security-focused analysis of the system's source code (if available).
     Cross-reference against code-visible ML attack surface — are there model deserialization
     paths without integrity validation, training pipelines accepting external data without
     sanitization, inference endpoints missing authentication, feature stores with overly broad
     access, or model outputs used in downstream decisions without confidence thresholds?

2. MAESTRO framework assessment:

   Use **MAESTRO categories**: {maestro_cats}

   **Verify coverage across ML lifecycle:**
   - Data collection and labeling threats
   - Training pipeline security
   - Model integrity and theft
   - Inference-time attacks
   - Privacy preservation
   - Fairness and bias
   - Monitoring and drift detection

3. ML/AI-specific gap analysis criteria:

   **Model Security Coverage:**
   - Model extraction/stealing attacks
   - Model inversion attacks
   - Model backdoor insertion
   - Transfer learning vulnerabilities

   **Data Security Coverage:**
   - Training data poisoning
   - Label manipulation
   - Data provenance violations
   - Test set contamination

   **LLM-Specific Coverage (if applicable):**
   - Prompt injection attacks
   - Jailbreaking attempts
   - System prompt leakage
   - Context window exploitation

   **Privacy Coverage:**
   - Membership inference attacks
   - Attribute inference attacks
   - Model memorization risks
   - Differential privacy violations

   **Supply Chain Coverage:**
   - Pre-trained model backdoors
   - Compromised ML libraries
   - Dataset poisoning at source
   - Model hub vulnerabilities

4. Decision framework:

   **A. If significant ML/AI-specific gaps exist:**
   - Set "stop" to **FALSE**
   - Provide detailed gap analysis
   - Prioritize ML-specific threats

   **B. If ML/AI threat catalog is comprehensive:**
   - Set "stop" to **TRUE**
   - Provide brief rationale

5. Gap format:

   **Gap N**: [ML/AI-specific missing coverage]
   - **MAESTRO Category**: [Category]
   - **Affected ML Assets**: [Models, data, pipelines]
   - **ML Attack Vector**: [Specific ML attack method]
   - **Recommendation**: [ML-specific mitigation]

</instructions>
"""


def maestro_improve_prompt() -> str:
    """Generate prompt for improving ML/AI threat catalog."""
    maestro_cats = _get_maestro_categories_string()

    return f"""
<task>
You are an expert in ML/AI security. Enrich an existing ML/AI threat catalog by identifying new ML-specific threats using the MAESTRO framework. Focus on threats unique to machine learning systems.
</task>

<instructions>

1. Review inputs:

   * <architecture_diagram>: ML/AI system
   * <identified_assets_and_entities>: ML assets
   * <data_flow>: ML pipelines
   * <threats>: Existing catalog
   * <gap>: Gap analysis
   * <code_summary>: Security-focused analysis of the system's source code (if available).
     Ground ML threats in actual implementation — torch.load() without integrity checks (arbitrary
     code execution via pickle), training data loaded from unvalidated URLs (data poisoning),
     model serving endpoints without rate limiting (model extraction), prompt templates with
     user-controlled variables (prompt injection), eval()/exec() on model outputs (code injection),
     and gradient computation exposed to API callers (adversarial example generation).

2. MAESTRO framework: {maestro_cats}

3. ML/AI Threat Similarity and Deduplication Guidelines (CRITICAL):

   **Before adding new ML threats, review existing threats to avoid duplication:**
   * **Near-duplicate check:** Don't add a threat if an existing threat already covers the same:
     - Attack vector (same ML technique/method)
     - Target ML asset/component (model, data, pipeline)
     - MAESTRO category
     - Impact type (privacy, integrity, availability)
   * **Variation test:** If ML threats seem similar, they must differ in at least 2 of these:
     - Threat actor type (internal data scientist vs external attacker)
     - Attack complexity (different DREAD exploitability scores, white-box vs black-box)
     - Specific target ML sub-component (training pipeline vs inference endpoint)
     - ML lifecycle stage (data collection, training, deployment, inference)
     - Attack chain position (initial model access vs model exfiltration)
   * **Consolidation:** If you identify 2-3 existing ML threats that could be merged into one comprehensive threat, note this in your gap analysis and merge them. Combine ML attack vectors into the description.
   * **Distinct value:** Each new ML threat should provide unique security insight specific to ML/AI systems, not just reword existing threats or duplicate traditional software threats

4. DREAD Risk Scoring Model (Anchor Values: 0, 2.5, 5, 7.5, 10):

   * **Damage Potential (ML/AI Impact)**: 0 (None) to 10 (Complete model compromise/full dataset extraction).
   * **Reproducibility (ML Attack Reliability)**: 0 (Cannot reproduce) to 10 (Guaranteed on any ML system instance).
   * **Exploitability (ML Attack Skill/Effort)**: 0 (State-of-the-art ML research) to 10 (Standard API calls, basic ML knowledge).
   * **Affected Users (ML System Blast Radius)**: 0 (None) to 10 (All users, all models).
   * **Discoverability (ML Vulnerability Detection)**: 0 (Requires model internals) to 10 (Publicly documented, obvious).

5. DREAD Severity Distribution and Balanced Scoring (Sum 0-50):

   * **Critical (40-50):** Stop the line. Model deployment halt.
   * **High (25-39):** Mitigate before production. Model retraining required.
   * **Medium (11-24):** Scheduled resolution. Monitoring enhanced.
   * **Low (1-10):** Standard backlog. Defense-in-depth gaps.

   **CRITICAL REQUIREMENT:** Prioritize adding Medium and Low severity ML threats if the existing catalog is dominated by Critical/High threats. A realistic ML threat model needs configuration issues, monitoring gaps, and best practice violations. DO NOT inflate DREAD scores.

6. Focus on ML-specific threats:

   **Prioritize threats that:**
   - Exploit ML model properties (gradients, confidence scores, embeddings)
   - Target ML training or inference pipelines
   - Leverage ML-specific APIs or endpoints
   - Abuse ML feedback loops or online learning
   - Exploit ML supply chain (pre-trained models, datasets)

7. Format each new or merged ML/AI threat exactly as follows:

   **Threat Name**: [Clear ML-specific descriptive title]
   **MAESTRO Category**: [{maestro_cats}]
   **Severity Class**: [Critical / High / Medium / Low - this MUST match the DREAD total range]
   **Description**: [ML-specific attack using ML threat grammar, {THREAT_DESCRIPTION_MIN_WORDS}–{THREAT_DESCRIPTION_MAX_WORDS} words]
   **Target**: [Specific ML asset: model weights, training data, inference pipeline, etc.]
   **Impact**: [ML-specific impact with concrete examples]
   **Likelihood**: [Based on ML attack complexity and attacker capabilities]
   **DREAD Assessment**:
     - Damage: [Value from anchor points: 0, 2.5, 5, 7.5, 10]
     - Reproducibility: [Value from anchor points: 0, 2.5, 5, 7.5, 10]
     - Exploitability: [Value from anchor points: 0, 2.5, 5, 7.5, 10]
     - Affected Users: [Value from anchor points: 0, 2.5, 5, 7.5, 10]
     - Discoverability: [Value from anchor points: 0, 2.5, 5, 7.5, 10]
     - Total Score: [Sum of all five values: 0-50]
   **Mitigations**:
     1. [P] [Specific ML-aware Preventive implementation to stop this entirely]
     2. [D] [Specific ML-aware Detective implementation to know if prevention fails]
     3. [C] [Specific ML-aware Containment implementation to limit blast radius]
   ... (provide {MITIGATION_MIN_ITEMS}–{MITIGATION_MAX_ITEMS} ML-specific mitigations)

8. Ensure balanced severity distribution across Critical/High/Medium/Low.

9. All mitigations must be ML-aware (not generic security controls like "use HTTPS" or "implement authentication").

</instructions>
"""
