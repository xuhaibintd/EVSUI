# BookRAG Latest-Document Governance

## Storage contract

The governed retrieval path uses the existing BookRAG tables plus one view:

- `<vector_store>_bk_bdoc`: document metadata, including the authoritative publication date.
- `<vector_store>_bk_bdrel`: explicit document relationships. `updates` points from the newer document to the obsolete document.
- `<vector_store>_bk_retrieval_v`: effective documents joined to `bnode`, with `latest_rank` calculated from `publication_date`.

`created_at` is a processing timestamp and must not be used as a publication date. Filename sorting must not be used to determine recency. The view reads its underlying tables dynamically; normal metadata and relationship updates do not recreate it.

## MCP LLM prompt

The MCP server does not require a code change. Replace the previous "vector store first" instruction with the following database-first retrieval contract. Substitute the database and vector-store names when they differ.

```text
私のデータベースは usecases_japan です。
vector store は MUBKWM です。

回答前に、MCP の base_readQuery を使用して、必ず
usecases_japan.MUBKWM_bk_retrieval_v
から検索対象文書を確定してください。vector store の意味検索を先に実行してはいけません。

【時間条件の判定】
1. 質問に年月日、年月、対象期間などの明示的な時間指定がある場合は、その条件を publication_date に適用してください。
2. 明示的な時間指定がない場合は、固定件数で文書を限定してはいけません。必ず次の二系統を別々に検索してください。
   a. retrieval_v 内の全有効文書から、問い合わせに最も関連する最新情報を取得する。これは現在の結論、投資判断、予測、数値の根拠とする。
   b. document_series が monthly または main の有効な定期レポートから、同じ問い合わせに関連する詳細分析・背景情報を取得する。
   c. 定期レポートは、背景、理由、仕組み、詳細分析を補完する場合にのみ使用する。新しい資料と矛盾する場合は、publication_date が新しい資料を優先する。

【旧版の除外】
MUBKWM_bk_retrieval_v に存在しない文書は検索対象に戻してはいけません。
MUBKWM_bk_bdrel で relation_type = 'updates' の更新先となった旧版は、最新判定および回答根拠から除外してください。

【検索と回答】
1. 対象文書を確定した後、その doc_id に限定して MUBKWM_bk_retrieval_v の title、content、page_start、page_end、path を検索してください。
2. vector store の意味検索も利用する場合、確定済み doc_id に SQL filter を適用してください。全庫検索後に結果を選別する方法は使用してはいけません。
3. 最新性は publication_date だけで判断してください。created_at、ファイル名全体の文字列順、先頭記号（①～⑥）を最新判定に使用してはいけません。
4. publication_date または metadata_status が未確認で最新性を保証できない場合は、「最新」と断定せず、メタデータ確認が必要であることを回答してください。
5. 回答には参照した filename、publication_date、ページを記載してください。

MUBKWM と関連するテーブルは以下です。
MUBKWM_bk_bdoc: 文書単位の基本情報、ファイル情報、発行日メタデータを管理する。
MUBKWM_bk_braw: 文書解析直後の未加工エレメントを保存する。
MUBKWM_bk_bblk: テキスト、テーブル、画像などの解析ブロックを管理する。
MUBKWM_bk_bnode: vector store の検索ノードを管理する。
MUBKWM_bk_bent: 文書から抽出した人物、企業、用語などのエンティティを管理する。
MUBKWM_bk_belnk: エンティティと文書ノードの出現箇所を関連付ける。
MUBKWM_bk_brel: エンティティ同士の関係を管理する。
MUBKWM_bk_bdrel: 要約、参照、更新など、文書同士の関係を管理する。
MUBKWM_bk_retrieval_v: 旧版を除外し、publication_date 順の latest_rank と検索ノードを提供する。
```

## Operations

1. Open `Administration > Business Configuration > Document Metadata`.
2. Select the vector store and run `Auto-fill Metadata`.
3. Confirm rows whose source is `filename` and status is `review`; correct the publication date when necessary.
4. In `Document Relationships`, register `new document --updates--> old document` for revisions.
5. Verify `Effective Latest 3` before using API or MCP retrieval.

CSV export and import are available for bulk review. Manual values use `publication_date_source=manual` and are preserved by later auto-fill runs.
