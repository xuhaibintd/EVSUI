# Teradata ランタイム・接続詳細設計

文書 ID：`TD-EVSUI-DD-05`

## 1. 前提

`teradataml` の context と `teradatagenai` の認証状態はプロセス全体で共有される。本システムはユーザーごとに独立した SDK インスタンスが存在すると仮定しない。すべての Teradata 操作は、選択した保存済み接続を直列化して再活性化してから実行する。

## 2. モジュール

| モジュール | 責務 |
|---|---|
| `app/teradata_runtime.py` | SDK import と利用可能性のファサード |
| `app/core/runtime_manager.py` | async/thread lock、active identity、middleware |
| `app/integrations/teradata/connection.py` | background job 用接続 context manager |
| `app/web_support.py` | browser session 用再活性化 |
| `app/services/teradata_sql.py` | 識別子、型、SQL 実行補助 |

## 3. 接続プロファイルから SDK への変換

必須値は `host`、`username`、`password`、`ues_url`、`pat_token` である。PEM は構成に応じて任意で付加する。

```text
profile
  → create_context(host, username, password)
  → UES URL 末尾 /open-analytics を除去
  → set_auth_token(base_url, pat_token, pem_file?)
  → auth_data
```

接続開始前に既存 `VSManager` session と teradataml context を cleanup する。認証失敗時にも再度 cleanup し、半接続状態を残さない。

## 4. Runtime Manager

`TeradataRuntimeManager` は次を持つ。

- `asyncio.Lock`：HTTP とアプリ内 job の相互排他
- `threading.RLock`：同期 SDK 再活性化の保護
- `active_identity`：現在活性化した接続と session の識別
- `generation`：切替回数

- `TD-RUNTIME-001`：すべての Teradata I/O は `operation()` の内側で行う。
- `TD-RUNTIME-002`：処理前に必要な profile/session identity を確認し、異なる場合は cleanup と再認証を行う。
- `TD-RUNTIME-003`：再活性化失敗時は session の connected を false にし、安全なエラーを返す。
- `TD-RUNTIME-004`：job 終了時は成功・失敗に関係なく SDK context を cleanup する。
- `TD-RUNTIME-005`：ロック保持中に利用者入力待ちを行わない。

## 5. HTTP Middleware

`RuntimeIsolationMiddleware` は `/ui/` と `/api/bookrag` を対象に manager lock を取得する。job status の `/ui/jobs/` は Teradata を操作しないため除外する。

接続と reset 自体を除き、ログイン session が connected の場合は要求前にその session の接続を再活性化する。失敗時は SDK context を invalid にし `409` を返す。

## 6. Background Job 接続

job payload は `connection_profile_id` を持ち、シークレットを持たない。handler 実行時に `activated_connection()` が SQLite から profile を読み、暗号文を復号して接続する。

プロファイルが削除済み、不完全、SDK import 不可の場合は job を失敗させる。別 profile へ自動的に切り替えない。

## 7. 対象同一性

CSV load の再利用可否には、profile ID と非秘密 target fingerprint を使う。fingerprint は host、username、UES URL から作り、別の Teradata 対象へ誤って過去のロード結果を再利用しない。

password、PAT、PEM の rotation は同じ接続対象として扱う。host、username、UES URL の変更は別 target として扱う。

## 8. SQL 安全性

- 識別子は許可文字と Teradata 長制限へ正規化する。
- schema/table は引用関数を通す。
- 値は可能な限り parameter 化し、生成 SQL が必要な場合は型付き literal 関数を使う。
- ユーザー入力を raw SQL へ連結しない。
- DDL/DML の結果件数と期待 schema を検証する。

## 9. 失敗と復旧

| 失敗 | 状態 | 復旧 |
|---|---|---|
| DB context 作成失敗 | 未接続 | 設定修正後に再接続 |
| auth token 失敗 | cleanup 済み | PAT/PEM/UES を修正 |
| session 切替失敗 | session disconnected | 明示的再接続 |
| SDK import 不可 | runtime unavailable | lockfile に従い環境修復 |
| job 中断 | job stale 候補 | 外部状態照合後に新規実行 |
| timeout | リモート処理継続の可能性 | status/list で確認 |

timeout をリモート cancel 成功として扱わない。再実行前に同名 Vector Store、対象 table、manifest の状態を確認する。

## 10. 禁止事項

- Web Worker を増やして throughput を上げる。
- 外部 job process を同じ DB と SDK context へ接続する。
- session 選択だけで SDK context を変更する。
- `active_identity` だけを信頼して保存 profile の存在確認を省く。
- cleanup 例外で元の業務エラーを上書きする。
- SDK 互換分岐を各 Router と Template に分散させる。

## 11. 検証項目

- 二つの session が交互に操作しても正しい profile が毎回活性化される。
- HTTP と job の SDK 操作が同時実行されない。
- 接続失敗後に前 session の context が残らない。
- profile 削除・変更後の job が安全に失敗する。
- target fingerprint が対象変更を検知し、secret rotation を誤検知しない。
- すべての error/log が password、PAT、PEM を秘匿する。
