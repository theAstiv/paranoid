"""Enums for threat modeling system."""

from enum import Enum


class StrideCategory(str, Enum):
    """STRIDE threat modeling categories."""

    SPOOFING = "Spoofing"
    TAMPERING = "Tampering"
    REPUDIATION = "Repudiation"
    INFORMATION_DISCLOSURE = "Information Disclosure"
    DENIAL_OF_SERVICE = "Denial of Service"
    ELEVATION_OF_PRIVILEGE = "Elevation of Privilege"


class MaestroCategory(str, Enum):
    """MAESTRO ML/AI security threat categories."""

    MODEL_SECURITY = "Model Security"
    DATA_SECURITY = "Data Security"
    LLM_SECURITY = "LLM Security"
    PRIVACY = "Privacy"
    SUPPLY_CHAIN = "Supply Chain"
    RESOURCE_ABUSE = "Resource Abuse"
    PIPELINE_SECURITY = "Pipeline Security"
    REINFORCEMENT_LEARNING = "Reinforcement Learning"
    DISTRIBUTED_ML = "Distributed ML"
    MONITORING = "Monitoring"
    INTERPRETABILITY = "Interpretability"
    AUTOML = "AutoML"
    FAIRNESS = "Fairness"


class AssetType(str, Enum):
    """Types of assets and entities in threat modeling."""

    ASSET = "Asset"
    ENTITY = "Entity"


class FlowType(str, Enum):
    """Types of flows in system architecture."""

    DATA_FLOW = "data_flow"
    CONTROL_FLOW = "control_flow"
    TRUST_BOUNDARY = "trust_boundary"


class ImpactLevel(str, Enum):
    """Threat impact assessment levels."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class LikelihoodLevel(str, Enum):
    """Threat likelihood assessment levels."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class ThreatStatus(str, Enum):
    """Status of threats in review workflow."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MITIGATED = "mitigated"


class ModelStatus(str, Enum):
    """Status of threat modeling runs."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Framework(str, Enum):
    """Threat modeling frameworks."""

    STRIDE = "STRIDE"
    MAESTRO = "MAESTRO"
    HYBRID = "HYBRID"


class Provider(str, Enum):
    """LLM provider types."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"


class DiagramFormat(str, Enum):
    """Supported architecture diagram formats."""

    PNG = "png"
    JPEG = "jpeg"
    MERMAID = "mermaid"
