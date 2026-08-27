from __future__ import annotations

from typing import Any


ENRICHMENT_NODE_TYPES = {
    "openai_image_description",
    "anthropic_image_description",
    "bedrock_image_description",
    "openai_table_description",
    "anthropic_table_description",
    "bedrock_table_description",
    "openai_table2html",
    "anthropic_table2html",
    "bedrock_table2html",
    "twopass_table2html",
    "openai_ocr",
    "anthropic_ocr",
    "vertexai_ocr",
}


def validate_workflow_nodes(workflow_nodes: list[dict[str, Any]]) -> None:
    """Validate EVSUI's supported Pipeline API contract before network I/O.

    Unstructured's VLM partitioner already performs image/table descriptions,
    table-to-HTML, and generative OCR. Those enrichment nodes are therefore
    invalid after an explicitly selected VLM partitioner.
    """
    if not workflow_nodes:
        raise ValueError("Unstructured workflow must contain at least one node.")

    partition_nodes = [node for node in workflow_nodes if node.get("type") == "partition"]
    if len(partition_nodes) != 1:
        raise ValueError("Unstructured workflow must contain exactly one partition node.")
    partition = partition_nodes[0]
    settings = partition.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("Unstructured partition node settings must be an object.")

    subtype = str(partition.get("subtype") or "").strip()
    strategy = str(settings.get("strategy") or "").strip().lower()
    if subtype not in {"vlm", "unstructured_api"}:
        raise ValueError(f"Unsupported Unstructured partition subtype: {subtype or '<empty>'}.")
    if subtype == "vlm" and strategy not in {"auto", "vlm"}:
        raise ValueError(f"VLM partition subtype does not support strategy '{strategy}'.")
    if subtype == "unstructured_api" and strategy not in {"fast", "hi_res", "ocr_only"}:
        raise ValueError(f"Unstructured API partition subtype does not support strategy '{strategy}'.")

    if strategy == "vlm":
        invalid = [
            str(node.get("name") or node.get("subtype") or "Enrichment")
            for node in workflow_nodes
            if node.get("type") == "prompter"
            and str(node.get("subtype") or "") in ENRICHMENT_NODE_TYPES
        ]
        if invalid:
            raise ValueError(
                "VLM partition already includes image/table/OCR enrichment; "
                f"remove these nodes: {', '.join(invalid)}."
            )

    for node in workflow_nodes:
        if node.get("type") != "prompter":
            continue
        node_settings = node.get("settings")
        if node_settings is None:
            node["settings"] = {}
        elif not isinstance(node_settings, dict):
            raise ValueError(f"Unstructured node '{node.get('name')}' settings must be an object.")
