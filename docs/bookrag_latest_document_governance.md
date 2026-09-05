# BookRAG Latest-Document Governance

> **Language:** English | [日本語](bookrag_latest_document_governance_ja.md)

## Storage contract

The governed retrieval path uses the existing BookRAG tables plus one view:

- `<vector_store>_bk_bdoc`: document metadata, including the authoritative publication date.
- `<vector_store>_bk_bdrel`: explicit document relationships. `updates` points from the newer document to the obsolete document.
- `<vector_store>_bk_retrieval_v`: effective documents joined to `bnode`, with `latest_rank` calculated from `publication_date`.

`created_at` is a processing timestamp and must not be used as a publication date. Filename sorting must not be used to determine recency. The view reads its underlying tables dynamically; normal metadata and relationship updates do not recreate it.

## MCP LLM prompt

The following template uses fictional identifiers. Replace `example_database`
and `EXAMPLE_STORE` with an authorized deployment's names before use.

```text
My database is example_database. My vector store is EXAMPLE_STORE.

Before answering, use the configured read-only query tool to identify eligible
documents in example_database.EXAMPLE_STORE_bk_retrieval_v. Do not run a
vector-store similarity search before establishing the governed document scope.

Time conditions:
1. Apply any explicit date, month, or requested period to publication_date.
2. Without an explicit period, do not impose an arbitrary fixed document count.
   First retrieve current conclusions, forecasts, and figures from relevant,
   effective recent documents. Supplement with periodic background reports only
   when needed for coverage, detail, or diversity. Prefer newer publication_date
   values when background reports contradict newer evidence.

Superseded documents:
- Do not reintroduce documents absent from EXAMPLE_STORE_bk_retrieval_v.
- In EXAMPLE_STORE_bk_bdrel, an updates relation points from a newer document to
  the superseded document. Exclude that superseded target from current evidence.

Retrieval and answers:
1. Search title, content, page_start, page_end, and path only for eligible doc_id
   values in the governed retrieval view.
2. Apply document and time restrictions before vector-store similarity search;
   do not retrieve unrestricted results and filter them only afterwards.
3. Combine relevance with publication_date freshness. Do not treat created_at,
   filename lexical order, or decorative filename prefixes as publication dates.
4. If publication_date or metadata_status is unverified, disclose that freshness
   cannot be guaranteed and request metadata review instead of claiming "latest".
5. Use the same final evidence nodes for answer generation, citations, and API
   evidence. Include the source filename, publication date, and page references.

Related tables use the EXAMPLE_STORE_bk_ prefix:
- bdoc: document identity, file details, and publication metadata.
- braw: raw parsed elements.
- bblk: text, table, and image blocks.
- bnode: retrieval nodes.
- bent: extracted entities.
- belnk: entity occurrences linked to nodes.
- brel: relationships between entities.
- bdrel: relationships between documents.
- retrieval_v: effective documents and retrieval nodes with latest_rank.
```

## Operations

1. Open `BookRAG Governance > Document Governance > Document Metadata`.
2. Select the vector store and run `Auto-fill Metadata`.
3. Confirm rows whose source is `filename` and status is `review`; correct the publication date when necessary.
4. In `Document Relationships`, register `new document --updates--> old document` for revisions.
5. Verify each document's publication date, series, role, and metadata status
   before using API or MCP retrieval.

CSV export and import are available for bulk review. Manual values use `publication_date_source=manual` and are preserved by later auto-fill runs.

## Adaptive retrieval policy

The API retrieval path is configured by
`app/config/bookrag_retrieval_policy.json`. Candidate budgets, ranking weights,
background eligibility, coverage thresholds, diversity limits, governance
statuses, and filename classification rules can be changed without embedding
evaluation questions or asset taxonomies in production code.

The 22 acceptance questions live only in
`tests/fixtures/bookrag_evaluation_questions.json`. They verify that the query
planner remains open-ended; the runtime never loads that fixture.
