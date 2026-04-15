"""Services for Layer 5 generation."""

from jarvis.generation.services.chat_service import (
    ChatHistoryEntry,
    ChatService,
    ChatWindow,
    SavedMessageResult,
)
from jarvis.generation.services.citation_validator import (
    CitationIssue,
    CitationValidationResult,
    CitationValidator,
)
from jarvis.generation.services.chat_memory_service import ChatMemoryService
from jarvis.generation.services.confidence_service import (
    ConfidenceEvidence,
    ConfidenceService,
    compute_confidence,
)
from jarvis.generation.services.hallucination_checker import (
    ClaimCheck,
    GroundednessResult,
    HallucinationChecker,
)
from jarvis.generation.services.providers import (
    AllProvidersFailedError,
    FallbackLLMProvider,
    GigaChatProvider,
    LLMAuthenticationError,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    YandexGPTProvider,
    build_primary_provider,
)
from jarvis.generation.services.prompt_builder import (
    DocumentContext,
    GenerationMode,
    PromptResult,
    build_prompt,
    estimate_token_count,
    intent_to_mode,
)
from jarvis.generation.services.context_assembler import (
    AssembledContext,
    EventCluster,
    NewsWithContext,
    assemble_context_for_chat,
    assemble_context_for_digest,
    enrich_with_db_data,
    fetch_news_full,
    fetch_sources_map,
    group_by_event_clusters,
    trim_documents_to_budget,
)
from jarvis.generation.services.generation_logger import (
    GenerationLogEntry,
    GenerationLogResult,
    get_generation_log_by_id,
    get_generation_logs_for_user,
    save_generation_log,
)
from jarvis.generation.services.evaluation_service import (
    AblationComparison,
    GenerationEvaluationScenario,
    GenerationEvaluationService,
    GenerationEvaluationSummary,
)
from jarvis.generation.services.response_cache import ResponseCache
from jarvis.generation.services.rag_modes import (
    CRAGDecision,
    CRAGResult,
    CRAGService,
    GraphExpansion,
    GraphRAGLightResult,
    GraphRAGLightService,
    SelfRAGDecision,
    SelfRAGLightResult,
    SelfRAGLightService,
)
from jarvis.generation.services.retrieval_bridge import RetrievalBridge
from jarvis.generation.services.tts_service import DigestTTSService, TTSResult
from jarvis.generation.services.answer_generation_service import (
    AnswerGenerationService,
    GenerationConfig,
    GenerationAnswerResult,
    GenerationDigestResult,
    SourceInfo,
    build_answer_generation_service,
)

__all__ = [
    # Chat service
    "ChatHistoryEntry",
    "ChatService",
    "ChatWindow",
    "SavedMessageResult",
    # Citation validator
    "CitationIssue",
    "CitationValidationResult",
    "CitationValidator",
    # Chat memory
    "ChatMemoryService",
    # Confidence
    "ConfidenceEvidence",
    "ConfidenceService",
    "compute_confidence",
    # Hallucination checker
    "ClaimCheck",
    "GroundednessResult",
    "HallucinationChecker",
    # Providers
    "AllProvidersFailedError",
    "FallbackLLMProvider",
    "GigaChatProvider",
    "LLMAuthenticationError",
    "LLMProvider",
    "LLMProviderError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "YandexGPTProvider",
    "build_primary_provider",
    # Prompt builder
    "DocumentContext",
    "GenerationMode",
    "PromptResult",
    "build_prompt",
    "estimate_token_count",
    "intent_to_mode",
    # Context assembler
    "AssembledContext",
    "EventCluster",
    "NewsWithContext",
    "assemble_context_for_chat",
    "assemble_context_for_digest",
    "enrich_with_db_data",
    "fetch_news_full",
    "fetch_sources_map",
    "group_by_event_clusters",
    "trim_documents_to_budget",
    # Generation logger
    "GenerationLogEntry",
    "GenerationLogResult",
    "get_generation_log_by_id",
    "get_generation_logs_for_user",
    "save_generation_log",
    "AblationComparison",
    "GenerationEvaluationScenario",
    "GenerationEvaluationService",
    "GenerationEvaluationSummary",
    # Cache / TTS
    "ResponseCache",
    "RetrievalBridge",
    "CRAGDecision",
    "CRAGResult",
    "CRAGService",
    "GraphExpansion",
    "GraphRAGLightResult",
    "GraphRAGLightService",
    "SelfRAGDecision",
    "SelfRAGLightResult",
    "SelfRAGLightService",
    "DigestTTSService",
    "TTSResult",
    # Answer generation service
    "AnswerGenerationService",
    "GenerationConfig",
    "GenerationAnswerResult",
    "GenerationDigestResult",
    "SourceInfo",
    "build_answer_generation_service",
]
