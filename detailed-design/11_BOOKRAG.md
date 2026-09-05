# BookRAG 詳細設計

文書 ID：`TD-EVSUI-DD-08`

## 1. 目的と非目的

BookRAG は、長く構造化された文書から、該当 passage とその section 階層、page、source block、文書 metadata、文書関係、entity 情報を一つの追跡可能な evidence package として返す。

自動知識グラフ探索、法務・監査判断、矛盾の最終判定、引用の真実性保証、関連文書の無制限展開は行わない。出力は人または上位 LLM が検証する証拠候補である。

## 2. モジュール地図

| モジュール | 責務 |
|---|---|
| `bookrag_schema.py` | table 列、物理名、key、関係、view |
| `bookrag_tree.py` | raw element から階層 node 構築 |
| `bookrag_graph.py` | entity、mention link、relation |
| `bookrag_integrity.py` | 文書単位 key と関係整合性 |
| `bookrag_storage.py` | CSV、table 作成、load、row count |
| `bookrag_document_metadata.py` | publication metadata と governed scope |
| `bookrag_document_relations.py` | 文書間関係 CRUD/import/export |
| `bookrag_reconcile.py` | 既存 table と metadata の補正 |
| `bookrag_query_planner.py` | question facet と時間条件 |
| `bookrag_retrieval_policy.py` | policy JSON の型付き読込 |
| `bookrag_adaptive_retrieval.py` | current/background 検索と rerank |
| `bookrag_retrieval.py` | semantic match から evidence 再構築 |
| `bookrag_section_rules.py` | section 判定規則 |

## 3. 物理テーブル

Vector Store 名から Teradata の識別子制約に従って base 名を作り、次の suffix を付ける。

| 論理名 | suffix | 主キー | 役割 |
|---|---|---|---|
| documents | `bdoc` | `doc_id` | 文書 catalog と publication metadata |
| raw | `braw` | `doc_id, ordinal_raw` | Unstructured raw 監査 |
| blocks | `bblk` | `doc_id, element_id` | source element |
| nodes | `bnode` | `doc_id, node_id` | 階層と embedding source |
| document_relations | `bdrel` | `from_doc_id, relation_type, to_doc_id` | 文書関係 |
| entities | `bent` | `doc_id, entity_id` | 文書内 canonical entity |
| entity_links | `belnk` | `doc_id, link_id` | entity mention と node の対応 |
| entity_relations | `brel` | `doc_id, relation_id` | 文書内 entity relation |
| leaf view | `bleaf` | node key | leaf node 参照 |
| retrieval view | `<base>_bk_retrieval_v` | node key | 最新文書を反映した検索 source |

Teradata に物理 FK を必須としない代わりに、生成前の integrity check と複合 key join を必須とする。

## 4. ID と結合規則

- `doc_id` は一 upload 文書 instance の安定 UUID である。
- `node_id`、`element_id`、`entity_id`、`link_id`、`relation_id` は単独で文書を跨いで結合しない。
- node parent は `(doc_id,parent_node_id) → (doc_id,node_id)`。
- node source は `(doc_id,source_element_id) → (doc_id,element_id)`。
- entity link と relation も doc_id を含む endpoint を検証する。
- document relation の両端 doc_id は bdoc に存在し、自己関係や unsupported type を規則に従い拒否する。

## 5. Tree 構築

raw element を元の ordinal 順で処理し、section rule、title、category、page、metadata を使って document root、section、content node を作る。content node の source_element_id は bblk に対応させる。

embedding 対象 node type は `text`、`table`、`image` とする。section path と page range を保持し、検索後に祖先 chain を再構築できるようにする。

header/footer、主要 section、group、enumeration のルールは version 管理された `bookrag_section_rules.json` から読み、UI 保存時にも schema を検証する。

## 6. Graph 構築

NER が有効な場合、文書内で entity を正規化し、mention と node の mapping、entity 間 relation を生成する。entity normalization は文書 scope であり、別文書の同名 entity を自動統合しない。

Graph table が無効または entity がない場合も、選択された contract に従って header-only CSV または空 table を扱う。Core 処理を Graph の空結果で失敗させない。

## 7. 文書メタデータ

bdoc の governance 項目は次である。

- `publication_date`
- `publication_date_source`
- `publication_date_precision`
- `document_series`
- `document_role`
- `logical_document_key`
- `revision_no`
- `metadata_status`

autofill は filename 等から候補を生成するが、確定判断ではない。保存、CSV import、export は同じ検証規則を使う。日付 precision、revision、status の不整合を拒否する。

## 8. 文書関係

`bdrel` は `updates`、`supplements`、`summarizes` 等の方向付き関係を保持する。relation description と source type を持ち、自動ルール由来と人手編集を区別する。

- 関係がない文書へ placeholder や自己関係を作らない。
- 関係更新は embedding 再作成を要求しない。
- import は全行検証後に適用し、部分的な不正行を黙って保存しない。
- 旧 store に bdrel がない場合の initialize は空 table の作成だけを行い、関係を推測しない。

## 9. 最新文書ガバナンス

同じ logical document の revision と `updates` 関係を用いて旧版を既定検索範囲から除外する。retrieval view は metadata status と obsolete target を考慮する。

明示的な過去時点質問では query planner の時間条件を使う。時間指定がない場合は current scope を優先し、policy に定義された periodic documents の古いものを background 候補へ分ける。

## 10. Query plan

question を一つ以上の facet へ分け、各 facet に semantic query、時間条件、探索 track を割り当てる。planner の出力は決定可能な構造データとし、後段が文字列解析に依存しない。

policy は次を制御する。

- current/background の候補数
- series/role ごとの current 保持件数
- freshness、semantic rank、facet coverage の重み
- duplicate 排除
- final top_k と minimum evidence

policy JSON の未知または不正値を無視せず、起動または読込時に検証する。

## 11. Adaptive retrieval

```text
Question
  → QueryPlan / facets
  → governed document scope
  → current track semantic search
  → 必要時 background track
  → doc_id filter
  → evidence reconstruction
  → candidate dedupe
  → semantic/freshness/coverage rerank
  → exact node filter で final lock
  → evidence package
```

final lock は最終候補の `(doc_id,node_id)` だけを対象にし、LLM 入力と返却 evidence のずれを防ぐ。

## 12. Evidence package

各 package は最低限次を持つ。

- rank、score、matched facets、retrieval track
- match node
- nearest section と ancestor chain
- source block
- document metadata
- document relations
- entities
- entity links/mapping
- entity relations
- schema と table mapping

検索 match に対応する node が解決できない場合は、その package を不完全なまま返さず除外または warning とする。SQL 取得の一部が存在しない旧 schema では、利用可能な Core evidence を保ちながら optional graph を空にできる。

## 13. LLM 入力と回答

LLM 入力には task、instructions、retrieval scope、query plan、evidence、output contract を含める。回答は citations を evidence item に結び、引用候補の doc_id、node_id、page、source を失わない。

本システム内の既定回答生成は evidence に限定し、証拠がない断定を避ける。citation の存在は主張が事実として検証済みであることを意味しない。

## 14. 整合性と再構築

load 前に主キー重複、parent、source block、entity endpoint、document relation endpoint を検証する。reconcile は既存 table の不足列や view を安全に補うが、業務 metadata を推測して上書きしない。

schema contract の変更は version と migration/reconcile 戦略を必要とする。既存 suffix や key の意味を変更しない。

## 15. 検証項目

- 複数文書で同じ node/entity ID があっても doc_id scope で分離される。
- section chain、page、block、document metadata を一致させる。
- old/new revision、updates relation、過去時点質問を試験する。
- current/background 分割、facet dedupe、rerank、final lock を試験する。
- graph なし、bdrel なし、optional table なしの旧 store を安全に扱う。
- API response と LLM input の evidence key が一致する。
