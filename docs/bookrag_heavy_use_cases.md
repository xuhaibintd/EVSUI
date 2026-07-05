# BookRAG Heavyweight Use Cases / BookRAG の重量級ユースケース

This document summarizes where EVSUI's `multi_format_bookrag` mode is a better fit than plain chunk-based RAG. BookRAG is intended for long, structured, multi-evidence documents where section paths, tables, images, entities, relations, and auditability matter.

本ドキュメントは、EVSUI の `multi_format_bookrag` モードが通常のチャンク型 RAG より有効になる場面を整理したものです。BookRAG は、章構造、表、画像、エンティティ、関係性、根拠追跡が重要な長大かつ構造化された文書を対象にします。

## English

### Core Positioning

Plain RAG usually follows this pattern:

```text
chunk -> embedding -> similarity search -> answer
```

BookRAG is designed for a heavier evidence model:

```text
document -> section tree -> blocks -> entities -> relations -> evidence graph -> retrieval + reasoning
```

Use BookRAG when the answer must be grounded in multiple parts of a document, when table or figure evidence is important, or when a reviewer needs to trace an answer back to page numbers, section paths, and source elements.

### 1. Annual Reports, Financial Reports, and IR Documents

Examples:

```text
10-K, annual securities reports, earnings releases, integrated reports, investor relations PDFs
```

Typical questions:

```text
What drove revenue changes over the last three years?
How does segment margin decline relate to disclosed risk factors?
Is the dividend policy consistent with cash flow and capital allocation statements?
```

Why BookRAG helps:

- Preserves section hierarchy and page-level provenance.
- Keeps table and numeric evidence traceable.
- Connects entities such as business units, financial metrics, dates, and risk categories.
- Reduces the chance of answering from an isolated chunk without the surrounding management discussion or notes.

### 2. Legal, Regulatory, Compliance, and Contract Review

Examples:

```text
Regulatory rules, internal policies, audit reports, contracts, control manuals
```

Typical questions:

```text
Which clauses require customer data encryption?
Does this workflow violate an internal control requirement?
Where do payment terms and termination penalties interact?
```

Why BookRAG helps:

- Preserves clause and subsection hierarchy.
- Links definitions, exceptions, responsibilities, deadlines, and obligations.
- Supports multi-evidence answers instead of relying on one nearby chunk.
- Produces traceable citations for audit and review.

### 3. Medical, Clinical, Scientific, and Technical Documents

Examples:

```text
Clinical trial reports, drug labels, SOPs, equipment manuals, research papers
```

Typical questions:

```text
Which trial groups reported a specific adverse event?
Do dosage restrictions conflict with contraindications?
Are methods, results, and conclusions consistent?
```

Why BookRAG helps:

- Preserves section roles such as method, result, discussion, warning, and appendix.
- Keeps tables and experimental results attached to their source context.
- Supports entity and relation extraction for drugs, outcomes, cohorts, devices, and measurements.
- Improves auditability for high-risk answers.

### 4. Enterprise Knowledge Bases and Large Operational Manuals

Examples:

```text
IT runbooks, operations manuals, product documentation, training material, troubleshooting guides
```

Typical questions:

```text
What is the correct troubleshooting sequence when database replication fails?
Which configuration items are related to this error code?
Which upgrade steps require manual approval?
```

Why BookRAG helps:

- Preserves procedures, prerequisites, warnings, and nested steps.
- Helps retrieve by process structure, not only semantic similarity.
- Can connect error codes, components, configuration keys, commands, and remediation steps.

### 5. Investment Research, Due Diligence, and M&A

Examples:

```text
Company filings, prospectuses, research notes, market reports, legal due diligence material
```

Typical questions:

```text
Are the target company's key risks related to customer concentration?
Are supplier dependency statements consistent across documents?
Do management claims conflict with financial data?
```

Why BookRAG helps:

- Supports cross-document entity normalization.
- Helps align evidence across filings, reports, and diligence notes.
- Enables contradiction and consistency checks across sections and documents.

### When Not To Use BookRAG

Plain VectorStore RAG is usually enough for:

- Short FAQ content.
- Simple web pages.
- Basic customer support answers.
- Documents where section hierarchy and table evidence are not important.
- Use cases that only need semantic search without audit-grade traceability.

BookRAG adds processing cost and model complexity. Use it when the document structure and evidence trail justify that cost.

### EVSUI Product Positioning

In EVSUI, use:

- `Multi Format` for standard RAG over ordinary documents.
- `Multi-Format BookRAG` for heavy documents that require traceable evidence, section paths, table/image handling, entities, relations, and multi-evidence reasoning.

In short: BookRAG is for audit-grade document question answering and cross-evidence reasoning, especially for financial, legal, medical, technical, and due diligence workflows.

## 日本語

### 基本的な位置づけ

通常の RAG は、多くの場合次の流れです。

```text
chunk -> embedding -> similarity search -> answer
```

BookRAG は、より重い証拠モデルを前提にします。

```text
document -> section tree -> blocks -> entities -> relations -> evidence graph -> retrieval + reasoning
```

回答が文書内の複数箇所に依存する場合、表や図の根拠が重要な場合、または回答をページ番号・章パス・元要素まで追跡する必要がある場合に BookRAG が有効です。

### 1. 年次報告書、財務報告書、IR 文書

例:

```text
10-K、有価証券報告書、決算短信、統合報告書、IR PDF
```

典型的な質問:

```text
過去 3 年間の売上変動の要因は何か。
セグメント利益率の低下は、開示されたリスク要因とどう関係しているか。
配当方針はキャッシュフローや資本配分方針と整合しているか。
```

BookRAG が有効な理由:

- 章階層とページ単位の出典を保持できる。
- 表や数値の根拠を追跡できる。
- 事業部門、財務指標、日付、リスク分類などのエンティティを関連付けられる。
- 単一チャンクだけで回答し、周辺の経営説明や注記を見落とすリスクを下げられる。

### 2. 法務、規制、コンプライアンス、契約レビュー

例:

```text
規制文書、社内規程、監査報告書、契約書、内部統制マニュアル
```

典型的な質問:

```text
顧客データの暗号化を要求している条項はどこか。
この業務フローは内部統制要件に違反していないか。
支払条件と解除・違約金条項はどこで関係しているか。
```

BookRAG が有効な理由:

- 条項、節、項の階層を保持できる。
- 定義、例外、責任、期限、義務を関連付けられる。
- 近くにある 1 チャンクだけではなく、複数根拠に基づく回答ができる。
- 監査やレビューで使える追跡可能な引用を生成しやすい。

### 3. 医療、臨床、科学、技術文書

例:

```text
臨床試験報告書、医薬品添付文書、SOP、機器マニュアル、研究論文
```

典型的な質問:

```text
特定の有害事象はどの試験群で報告されたか。
用量制限と禁忌事項に矛盾はないか。
方法、結果、結論は整合しているか。
```

BookRAG が有効な理由:

- 方法、結果、考察、警告、付録などの章の役割を保持できる。
- 表や実験結果を元の文脈に紐づけられる。
- 薬剤、アウトカム、コホート、機器、測定値などのエンティティと関係を扱える。
- 高リスクな回答の監査性を高められる。

### 4. 企業ナレッジベース、大規模運用マニュアル

例:

```text
IT runbook、運用マニュアル、製品ドキュメント、研修資料、トラブルシューティングガイド
```

典型的な質問:

```text
データベース同期に失敗した場合、どの順序で調査すべきか。
このエラーコードに関連する設定項目は何か。
アップグレード手順のうち、どこで手動承認が必要か。
```

BookRAG が有効な理由:

- 手順、前提条件、警告、入れ子になったステップを保持できる。
- 単なる意味検索ではなく、プロセス構造に沿って検索しやすい。
- エラーコード、コンポーネント、設定キー、コマンド、復旧手順を関連付けられる。

### 5. 投資調査、デューデリジェンス、M&A

例:

```text
会社開示資料、目論見書、調査メモ、市場レポート、法務 DD 資料
```

典型的な質問:

```text
対象会社の主要リスクは顧客集中と関係しているか。
サプライヤー依存に関する記述は複数資料で整合しているか。
経営陣の説明と財務データに矛盾はないか。
```

BookRAG が有効な理由:

- 複数文書にまたがるエンティティの名寄せに向いている。
- 開示資料、レポート、DD メモ間の根拠を揃えやすい。
- 章や文書をまたいだ矛盾・整合性チェックに使いやすい。

### BookRAG を使わない方がよい場面

次のような場合は、通常の VectorStore RAG で十分なことが多いです。

- 短い FAQ。
- 単純な Web ページ。
- 基本的なカスタマーサポート回答。
- 章階層や表の根拠が重要ではない文書。
- 監査レベルの追跡性を必要とせず、意味検索だけで足りる用途。

BookRAG は処理コストとモデル複雑性を増やします。文書構造と根拠追跡がそのコストに見合う場合に使うべきです。

### EVSUI での位置づけ

EVSUI では次の使い分けを想定します。

- `Multi Format`: 通常文書に対する標準的な RAG。
- `Multi-Format BookRAG`: 根拠追跡、章パス、表・画像処理、エンティティ、関係性、複数根拠の推論が必要な重量級文書。

要するに、BookRAG は監査レベルの文書 QA と複数根拠に基づく推論のためのモードです。特に財務、法務、医療、技術文書、デューデリジェンスのワークフローに適しています。
