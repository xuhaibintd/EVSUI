from __future__ import annotations

from . import multi_format_bookrag_mode, multi_format_mode, text_core
from .constants import (
    DOC_PIPELINE_OPTIONS as DOC_PIPELINE_OPTIONS,
    normalize_doc_pipeline_mode,
)

DOC_PIPELINE_HANDLERS = {
    text_core.MODE: text_core,
    multi_format_mode.MODE: multi_format_mode,
    multi_format_bookrag_mode.MODE: multi_format_bookrag_mode,
}


def get_doc_pipeline_handler(mode: str):
    return DOC_PIPELINE_HANDLERS[normalize_doc_pipeline_mode(mode)]
