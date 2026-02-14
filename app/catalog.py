from __future__ import annotations

import inspect
from dataclasses import dataclass
from importlib import import_module
from typing import Any


@dataclass(frozen=True)
class FeatureMethod:
    id: str
    group: str
    class_name: str
    method_name: str
    module: str
    signature: str
    description: str


_DEFAULT_METHODS: list[FeatureMethod] = [
    FeatureMethod(
        id="vsmanager.health",
        group="Vector Store Manager",
        class_name="VSManager",
        method_name="health",
        module="teradatagenai.vector_store.vector_store",
        signature="()",
        description="Health check for vector store service.",
    ),
    FeatureMethod(
        id="vsmanager.list",
        group="Vector Store Manager",
        class_name="VSManager",
        method_name="list",
        module="teradatagenai.vector_store.vector_store",
        signature="(**kwargs)",
        description="List vector stores.",
    ),
    FeatureMethod(
        id="vsmanager.list_patterns",
        group="Vector Store Manager",
        class_name="VSManager",
        method_name="list_patterns",
        module="teradatagenai.vector_store.vector_store",
        signature="(log=False)",
        description="List document chunking patterns.",
    ),
    FeatureMethod(
        id="vsmanager.list_sessions",
        group="Vector Store Manager",
        class_name="VSManager",
        method_name="list_sessions",
        module="teradatagenai.vector_store.vector_store",
        signature="()",
        description="List active sessions.",
    ),
    FeatureMethod(
        id="vsmanager.disconnect",
        group="Vector Store Manager",
        class_name="VSManager",
        method_name="disconnect",
        module="teradatagenai.vector_store.vector_store",
        signature="(session_id=None, raise_error=True)",
        description="Disconnect session from vector store.",
    ),
    FeatureMethod(
        id="vectorstore.create",
        group="Vector Store",
        class_name="VectorStore",
        method_name="create",
        module="teradatagenai.vector_store.vector_store",
        signature="(self, **kwargs)",
        description="Create a vector store.",
    ),
    FeatureMethod(
        id="vectorstore.update",
        group="Vector Store",
        class_name="VectorStore",
        method_name="update",
        module="teradatagenai.vector_store.vector_store",
        signature="(self, **kwargs)",
        description="Update a vector store (ADD or DROP, MAJOR or MINOR).",
    ),
    FeatureMethod(
        id="vectorstore.status",
        group="Vector Store",
        class_name="VectorStore",
        method_name="status",
        module="teradatagenai.vector_store.vector_store",
        signature="(self)",
        description="Check async operation status.",
    ),
    FeatureMethod(
        id="vectorstore.destroy",
        group="Vector Store",
        class_name="VectorStore",
        method_name="destroy",
        module="teradatagenai.vector_store.vector_store",
        signature="(self)",
        description="Delete or destroy vector store.",
    ),
    FeatureMethod(
        id="vectorstore.get_details",
        group="Vector Store",
        class_name="VectorStore",
        method_name="get_details",
        module="teradatagenai.vector_store.vector_store",
        signature="(self)",
        description="Get vector store details.",
    ),
    FeatureMethod(
        id="vectorstore.get_objects",
        group="Vector Store",
        class_name="VectorStore",
        method_name="get_objects",
        module="teradatagenai.vector_store.vector_store",
        signature="(self)",
        description="List source objects in vector store.",
    ),
    FeatureMethod(
        id="vectorstore.list_user_permissions",
        group="Vector Store",
        class_name="VectorStore",
        method_name="list_user_permissions",
        module="teradatagenai.vector_store.vector_store",
        signature="(self)",
        description="List permissions for vector store users.",
    ),
    FeatureMethod(
        id="vectorstore.similarity_search",
        group="Vector Store",
        class_name="VectorStore",
        method_name="similarity_search",
        module="teradatagenai.vector_store.vector_store",
        signature="(self, question=None, **kwargs)",
        description="Run semantic similarity search.",
    ),
    FeatureMethod(
        id="vectorstore.ask",
        group="Vector Store",
        class_name="VectorStore",
        method_name="ask",
        module="teradatagenai.vector_store.vector_store",
        signature="(self, question=None, prompt=None, **kwargs)",
        description="Ask QnA against vector store.",
    ),
    FeatureMethod(
        id="vectorstore.prepare_response",
        group="Vector Store",
        class_name="VectorStore",
        method_name="prepare_response",
        module="teradatagenai.vector_store.vector_store",
        signature="(self, similarity_results, question=None, prompt=None, **kwargs)",
        description="Compose final answer from similarity results.",
    ),
    FeatureMethod(
        id="vectorstore.get_batch_result",
        group="Vector Store",
        class_name="VectorStore",
        method_name="get_batch_result",
        module="teradatagenai.vector_store.vector_store",
        signature="(self, api_name, **kwargs)",
        description="Fetch result for a previous batch call.",
    ),
    FeatureMethod(
        id="vspattern.create",
        group="Vector Store Pattern",
        class_name="VSPattern",
        method_name="create",
        module="teradatagenai.vector_store.vector_store",
        signature="(self, pattern_string)",
        description="Create a new vector store parsing pattern.",
    ),
    FeatureMethod(
        id="vspattern.get",
        group="Vector Store Pattern",
        class_name="VSPattern",
        method_name="get",
        module="teradatagenai.vector_store.vector_store",
        signature="(self)",
        description="Get current pattern details.",
    ),
    FeatureMethod(
        id="vspattern.delete",
        group="Vector Store Pattern",
        class_name="VSPattern",
        method_name="delete",
        module="teradatagenai.vector_store.vector_store",
        signature="(self)",
        description="Delete current pattern.",
    ),
    FeatureMethod(
        id="text.analyze_sentiment",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="analyze_sentiment",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data=None, **kwargs)",
        description="Sentiment analysis on text column.",
    ),
    FeatureMethod(
        id="text.classify",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="classify",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data, labels=None, multi_label=False, **kwargs)",
        description="Text classification.",
    ),
    FeatureMethod(
        id="text.detect_language",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="detect_language",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data=None, language=None, **kwargs)",
        description="Language detection.",
    ),
    FeatureMethod(
        id="text.extract_key_phrases",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="extract_key_phrases",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data=None, **kwargs)",
        description="Extract key phrases.",
    ),
    FeatureMethod(
        id="text.mask_pii",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="mask_pii",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data=None, **kwargs)",
        description="Mask PII entities.",
    ),
    FeatureMethod(
        id="text.recognize_entities",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="recognize_entities",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data=None, **kwargs)",
        description="Named entity recognition.",
    ),
    FeatureMethod(
        id="text.recognize_linked_entities",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="recognize_linked_entities",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data=None, **kwargs)",
        description="Linked entity recognition.",
    ),
    FeatureMethod(
        id="text.recognize_pii_entities",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="recognize_pii_entities",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data=None, **kwargs)",
        description="PII entity recognition.",
    ),
    FeatureMethod(
        id="text.summarize",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="summarize",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data=None, level=1, **kwargs)",
        description="Text summarization.",
    ),
    FeatureMethod(
        id="text.translate",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="translate",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data=None, target_lang='English', **kwargs)",
        description="Translation.",
    ),
    FeatureMethod(
        id="text.embeddings",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="embeddings",
        module="teradatagenai.text_analytics.TextAnalyticsAIClient",
        signature="(self, column, data=None, persist=False, **kwargs)",
        description="Generate embeddings.",
    ),
    FeatureMethod(
        id="text.sentence_similarity",
        group="Text Analytics",
        class_name="TextAnalyticsAI",
        method_name="sentence_similarity",
        module="teradatagenai.text_analytics.TextAnalyticsAIHuggingFace",
        signature="(self, column1, column2, data=None, **kwargs)",
        description="Sentence similarity (hugging_face backend).",
    ),
    FeatureMethod(
        id="llm.answer",
        group="LLM",
        class_name="TeradataAI",
        method_name="answer",
        module="teradatagenai.llm.llm",
        signature="(self, query)",
        description="Get an answer from configured LLM endpoint.",
    ),
    FeatureMethod(
        id="llm.task",
        group="LLM",
        class_name="TeradataAI",
        method_name="task",
        module="teradatagenai.llm.llm",
        signature="(self, **kwargs)",
        description="Run backend-specific task call.",
    ),
    FeatureMethod(
        id="llm.get_llm",
        group="LLM",
        class_name="TeradataAI",
        method_name="get_llm",
        module="teradatagenai.llm.llm",
        signature="(self)",
        description="Get underlying LLM object.",
    ),
    FeatureMethod(
        id="llm.get_deployment_id",
        group="LLM",
        class_name="TeradataAI",
        method_name="get_deployment_id",
        module="teradatagenai.llm.llm",
        signature="(self)",
        description="Get deployment identifier.",
    ),
    FeatureMethod(
        id="llm.get_model_args",
        group="LLM",
        class_name="TeradataAI",
        method_name="get_model_args",
        module="teradatagenai.llm.llm",
        signature="(self)",
        description="Get model arguments.",
    ),
    FeatureMethod(
        id="llm.get_env",
        group="LLM",
        class_name="TeradataAI",
        method_name="get_env",
        module="teradatagenai.llm.llm",
        signature="(self)",
        description="Get BYO HuggingFace environment.",
    ),
    FeatureMethod(
        id="llm.remove",
        group="LLM",
        class_name="TeradataAI",
        method_name="remove",
        module="teradatagenai.llm.llm",
        signature="(self)",
        description="Remove BYO environment resources.",
    ),
    FeatureMethod(
        id="utils.load_data",
        group="Utility",
        class_name="general_utils",
        method_name="load_data",
        module="teradatagenai.general_utils.load_data",
        signature="(function_name, table_name)",
        description="Load sample data used by teradatagenai examples.",
    ),
]


def _resolve_signature(module_name: str, class_name: str, method_name: str, fallback: str) -> str:
    try:
        module = import_module(module_name)
    except Exception:
        return fallback

    target: Any
    try:
        if class_name == "general_utils":
            target = getattr(module, method_name)
        else:
            klass = getattr(module, class_name)
            target = getattr(klass, method_name)
        return str(inspect.signature(target))
    except Exception:
        return fallback


def build_catalog() -> list[FeatureMethod]:
    hydrated: list[FeatureMethod] = []
    for item in _DEFAULT_METHODS:
        hydrated.append(
            FeatureMethod(
                id=item.id,
                group=item.group,
                class_name=item.class_name,
                method_name=item.method_name,
                module=item.module,
                signature=_resolve_signature(
                    item.module,
                    item.class_name,
                    item.method_name,
                    item.signature,
                ),
                description=item.description,
            )
        )
    return hydrated


FEATURE_METHODS: list[FeatureMethod] = build_catalog()
FEATURE_INDEX: dict[str, FeatureMethod] = {item.id: item for item in FEATURE_METHODS}


def grouped_methods(items: list[FeatureMethod] | None = None) -> list[tuple[str, list[FeatureMethod]]]:
    source = items or FEATURE_METHODS
    groups: dict[str, list[FeatureMethod]] = {}
    for item in source:
        groups.setdefault(item.group, []).append(item)
    return sorted(groups.items(), key=lambda pair: pair[0].lower())


def search_methods(query: str | None) -> list[FeatureMethod]:
    if not query:
        return FEATURE_METHODS
    q = query.strip().lower()
    if not q:
        return FEATURE_METHODS
    return [
        item
        for item in FEATURE_METHODS
        if q in item.id.lower()
        or q in item.method_name.lower()
        or q in item.class_name.lower()
        or q in item.group.lower()
        or q in item.description.lower()
    ]
