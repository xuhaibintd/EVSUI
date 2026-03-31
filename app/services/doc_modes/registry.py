from __future__ import annotations

from . import multi_format, multi_format_bookrag, text_core
from .common import DOC_PIPELINE_OPTIONS, normalize_doc_pipeline_mode

DOC_PIPELINE_HANDLERS = {
    text_core.MODE: text_core,
    multi_format.MODE: multi_format,
    multi_format_bookrag.MODE: multi_format_bookrag,
}


def get_doc_pipeline_handler(mode: str):
    return DOC_PIPELINE_HANDLERS[normalize_doc_pipeline_mode(mode)]
