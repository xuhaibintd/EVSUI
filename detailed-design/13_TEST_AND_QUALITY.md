# テスト・品質保証詳細設計

文書 ID：`TD-EVSUI-DD-13`

## 1. 方針

テストは実装行をなぞるためではなく、外部契約、状態遷移、権限、永続性、失敗時の安全性を証明する。外部 Teradata と Unstructured を必要としない再現可能テストを標準とし、live test は明示 opt-in の補完とする。

## 2. テスト層

| 層 | 対象 | 主な test |
|---|---|---|
| 純粋単体 | 正規化、schema、tree、planner | `test_bookrag_*`、`test_vector_management.py` |
| Repository | migration、job、artifact、auth | `test_migrations.py`、`test_auth_store.py` |
| Service/Workflow | create、destroy、multi-format、jobs | `test_create_flow.py`、`test_*workflow*.py` |
| Router/API | auth、RBAC、HTTP contract | `test_action_routes.py`、`test_api_router.py` |
| Browser | DOM、HTMX、操作、layout | `test_browser_actions.py`、`test_frontend_parameters.py` |
| Packaging | dependency、wheel、identity | `test_wheel_verification.py`、scripts |
| Live | 実接続の読み取り smoke | `test_live_smoke.py`、`check_live_connection.py` |

## 3. Test isolation

- 各 test は一時 SQLite、upload root、credential key を使う。
- production DB、実 upload、実 PEM、実 API key を参照しない。
- environment を test ごとに保存・復元する。
- module global と `app.state` を test 間で共有しない。
- SDK は public boundary で stub/mock し、内部実装順序より呼出契約を検証する。
- time、UUID、network retry を決定可能にする。

## 4. 必須契約テスト

### 4.1 起動と設定

- environment、型、最小値、production key、external token、1 worker
- fresh migration と旧 version migration
- single instance lock

### 4.2 認証と安全

- bootstrap、Argon2、lockout、session TTL/touch/revoke
- admin/operator/viewer の各 route
- CSRF 同一生成元と security headers
- error/request ID と全 secret redaction

### 4.3 Teradata runtime

- session 切替で profile 再活性化
- HTTP/job の相互排他
- cleanup の成功・例外
- profile 削除、不完全設定、SDK import failure

### 4.4 Vector Store

- health/list/details の応答形状
- Description と BookRAG marker
- create field、payload、existing、Ready/Failed/Pending
- source/index row count
- destroy success、409、403、部分 cleanup

### 4.5 文書処理

- upload limit と path safety
- workflow node contract
- parse/CSV manifest version、checksum、status
- profile fingerprint と load reuse
- 部分失敗と再実行

### 4.6 BookRAG

- table name、columns、primary key、relationship
- tree と source block
- metadata、revision、document relation
- current/background scope、planner、rerank、final lock
- evidence、LLM input、citations

### 4.7 Jobs/Artifacts

- atomic claim、attempt fencing、heartbeat、stale recovery
- owner access と cancel
- encrypted secret payload
- artifact root、dry-run、apply、deleted mark

## 5. Browser regression

`UI_DESIGN.md` のシナリオを正本とする。特に次を release gate とする。

- メッセージは共通 top に一件
- 表見出しとセル数一致
- Description の実値
- row 選択に network request なし
- 削除失敗後の layout と選択維持
- System Configuration 3 tab
- desktop、1100px、900px、mobile の overflow
- button の loading/disabled 復元

browser evidence へ実 IP、username、Vector Store 名、文書内容を含めない。CI fixture は匿名値を使う。

## 6. Live test

live test は環境変数による明示 opt-in とし、既定では skip する。標準 live smoke は読み取り専用の接続、health、list、status/search の安全な範囲に限定する。

create、destroy、table load、user/config 変更の live test は専用環境、専用 prefix、明示 cleanup plan がある場合だけ実施する。共有資源を test 名だけで削除しない。

## 7. CI 順序

1. `uv lock --check`
2. dependency policy
3. locked browser dependency sync と `uv pip check`
4. exact environment check
5. publication check
6. English/Japanese public doc parity
7. compileall
8. Ruff correctness
9. unit/route tests
10. Playwright browser tests
11. production exact sync
12. build wheel
13. wheel content verification

早い静的検査を先に実行し、高価な browser/build を後にする。各段階は失敗を無視しない。

## 8. 静的品質

現在 Ruff は correctness rule を基線とする。新しい package は未使用 import、undefined name、syntax、到達不能な誤りを含めない。style rule を広げる場合は既存全体を一括機械変更せず、module 単位で導入する。

型ヒントは public service、repository、payload/result boundary を優先する。動的 SDK 応答は adapter で `Any` を受け、内部の正規化後 data contract を明確にする。

## 9. 公開品質

`check_publication.py` は公開対象から秘密、個人情報、実行報告、local artifact を排除する。`check_doc_parity.py` は README と `docs/` の英日 pair、構造、link、source hash を確認する。

本 `detailed-design/` は日本語内部文書であるため公開双語 pair の対象外だが、秘密・個人情報を記載してよいという意味ではない。

## 10. 変更別最小試験

| 変更 | 必須試験 |
|---|---|
| Settings/起動 | settings、single instance、app factory |
| Migration/Repository | migration と対象 repository |
| Auth/Security | auth、security、route RBAC |
| Workflow/Service | 対象単体、route、durable regression |
| Template/JS/CSS | browser と関連 route |
| SDK adapter | contract stub と opt-in live smoke |
| Dependency | lock、policy、pip check、wheel |
| Public docs | publication と parity |

修正範囲に応じて全 suite を実行する。失敗を「既存」と判断する場合は、変更前にも同じ commit/worktree で再現する証拠が必要である。

## 11. 完了条件

- [ ] 設計書の対象 ID と変更理由が明確である。
- [ ] 正常、入力不正、権限不足、外部失敗、中断、再実行を検証した。
- [ ] 永続 data と manifest の後方互換性を確認した。
- [ ] secret と個人情報が source、log、artifact、screenshot にない。
- [ ] 関連 test と必須 CI gate が成功した。
- [ ] wheel または container が current source を含む。
- [ ] UI を含む場合は実 browser と複数画面幅を確認した。
- [ ] 実装と `detailed-design/` に差異がない。

## 12. 失敗調査

失敗時は test 名、入力状態、request/job ID、期待値、実際値、再現手順を残す。秘密を含む raw trace は共有しない。修正後は同じ失敗条件を回帰 test にし、見た目だけでなく根本の状態遷移または契約を検証する。
