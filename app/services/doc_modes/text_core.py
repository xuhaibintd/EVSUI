from __future__ import annotations

MODE = "text_core"
LABEL = "Text"
SKIP_VECTORSTORE_CREATE = False


def preprocess_create_payload(**kwargs) -> tuple[dict, dict | None]:
    return dict(kwargs["exec_payload"]), None
