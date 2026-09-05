# BookRAG 最新文書ガバナンス

> **言語:** [English](bookrag_latest_document_governance.md) | 日本語
<!-- Source-SHA256: d76fc3f47074c78bb19b95defc5c56c5e23d64459ff3affee54f6f8dab0ac722 -->

## ストレージ契約

統制された検索経路では、既存の BookRAG テーブルと一つのビューを使用します。

- `<vector_store>_bk_bdoc`: 正式な発行日を含む文書メタデータ。
- `<vector_store>_bk_bdrel`: 明示的な文書間関係。`updates` は新しい文書から廃止された文書を指します。
- `<vector_store>_bk_retrieval_v`: 有効な文書と `bnode` を結合し、`publication_date` から `latest_rank` を算出するビュー。

`created_at` は処理時刻であり、発行日として使用してはいけません。ファイル名の並べ替えで新旧を判定してはいけません。このビューは基礎テーブルを動的に読み取るため、通常のメタデータ更新や関係更新で再作成する必要はありません。

## MCP LLM プロンプト

次のテンプレートでは架空の識別子を使用しています。使用前に `example_database` と `EXAMPLE_STORE` を、認可されたデプロイ環境の名前に置き換えてください。

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

## 運用手順

1. `BookRAG Governance > Document Governance > Document Metadata` を開きます。
2. Vector Store を選択し、`Auto-fill Metadata` を実行します。
3. source が `filename`、status が `review` の行を確認し、必要に応じて発行日を修正します。
4. 改訂版については、`Document Relationships` で `new document --updates--> old document` を登録します。
5. API または MCP で検索する前に、各文書の発行日、series、role、metadata status を確認します。

一括レビューには CSV のエクスポートとインポートを使用できます。手動で設定した値は `publication_date_source=manual` となり、その後に自動補完を実行しても保持されます。

## 適応型検索ポリシー

API の検索経路は `app/config/bookrag_retrieval_policy.json` で設定します。候補数、ランキングの重み、背景文書の適格性、カバレッジ閾値、多様性制限、ガバナンスステータス、ファイル名分類規則は、評価用質問や資産分類を本番コードへ埋め込まずに変更できます。

22 件の受け入れ質問は `tests/fixtures/bookrag_evaluation_questions.json` にのみ存在します。これらはクエリプランナーがオープンエンドであることを検証するものであり、実行時にこの fixture が読み込まれることはありません。
