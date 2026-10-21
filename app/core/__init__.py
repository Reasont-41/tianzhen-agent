"""核心包：知识库、检索、约束校验、处方生成、施药窗口、智能体编排。"""

from .agent import (
    AgentRunResult,
    AgentRuntime,
    AgentSession,
    LLMClient,
    get_agent_runtime,
    get_session,
    reset_session,
)
from .constraint_engine import ConstraintEngine
from .models import (
    Disease,
    PesticideRecord,
    Prescription,
    PrescriptionItem,
    RuleResult,
    SprayContext,
    ValidationReport,
)
from .pipeline import (
    ConstrainedGenerator,
    PipelineResult,
    PrescriptionPipeline,
    UnconstrainedBaselineGenerator,
)
from .retrieval import DiseaseRetriever, PesticideRetriever
from .spray_window import MockWeatherProvider, compute_spray_window
from .store import KnowledgeBase, get_kb

__all__ = [
    "AgentRunResult",
    "AgentRuntime",
    "AgentSession",
    "ConstraintEngine",
    "ConstrainedGenerator",
    "Disease",
    "DiseaseRetriever",
    "KnowledgeBase",
    "LLMClient",
    "MockWeatherProvider",
    "PesticideRecord",
    "PesticideRetriever",
    "PipelineResult",
    "Prescription",
    "PrescriptionItem",
    "PrescriptionPipeline",
    "RuleResult",
    "SprayContext",
    "UnconstrainedBaselineGenerator",
    "ValidationReport",
    "compute_spray_window",
    "get_agent_runtime",
    "get_kb",
    "get_session",
    "reset_session",
]
