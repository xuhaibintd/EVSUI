# SQLite コントロールプレーン詳細設計

文書 ID：`TD-EVSUI-DD-04`

## 1. 役割

SQLite は、アプリケーション自身が所有する小規模で整合性が必要な状態を保存する。Vector Store、埋め込み、BookRAG 業務テーブル、大容量文書は保存しない。

`SQLiteDatabase.connect()` は短命 connection を生成し、row factory、foreign key、10 秒の busy timeout を統一する。各書込みは context manager の transaction で完了させる。

## 2. テーブル契約

| テーブル | 主キー | 所有情報 | 主な用途 |
|---|---|---|---|
| `schema_versions` | `version` | 適用時刻 | migration 履歴 |
| `users` | `id` | account、role、lockout | 認証 |
| `sessions` | `session_id_hash` | `user_id`、TTL | server session |
| `permissions` | `id` | user/resource/permission | 将来の細粒度認可 |
| `audit_logs` | `id` | user、action、result | 監査 |
| `system_connection_profiles` | `id` | 名前、接続、暗号文、default | 再利用接続 |
| `external_service_configs` | `service_name` | URL、暗号 API key | Unstructured 等 |
| `jobs` | `id` | kind、owner、profile、状態 | 永続ワークフロー |
| `artifacts` | `id` | job、owner、path、hash、expiry | ファイル台帳 |
| `connection_configs` | `user_id` | 旧接続 | 互換のみ |
| `system_connection_config` | `config_id=1` | 旧 singleton | 互換のみ |

## 3. 関係

```text
users
├─ sessions
├─ permissions
├─ audit_logs
├─ jobs ── system_connection_profiles
└─ artifacts ── jobs

external_service_configs
system_connection_profiles
schema_versions
legacy connection tables
```

- ユーザー削除時、session と permission は cascade、audit の user_id は null、履歴上の username は保持する。
- 接続プロファイル削除時、job の profile ID は null になり、古い job は安全に再実行不能となる。
- job 削除・分離時も artifact は台帳として残せる。

## 4. マイグレーション

現在の schema version は 9 である。

| Version | 内容 |
|---:|---|
| 1 | users、sessions、permissions、audit_logs |
| 2 | 旧ユーザー別接続 |
| 3 | 旧 singleton system connection |
| 4 | 暗号化 PEM 列 |
| 5 | 複数接続プロファイル |
| 6 | 永続 jobs |
| 7 | artifacts |
| 8 | external service configs |
| 9 | job secret payload 暗号列 |

- `DB-MIG-001`：新しい変更は次の連番 migration として追加する。
- `DB-MIG-002`：適用済み migration の SQL と意味を変更しない。
- `DB-MIG-003`：migration は再実行可能で、途中失敗時に version を記録しない。
- `DB-MIG-004`：列追加前に既存列を確認し、旧 DB からの段階更新を試験する。
- `DB-MIG-005`：破壊的な変換には事前 backup と検証を設計する。

## 5. Repository 境界

| Repository | 公開責務 |
|---|---|
| `UserRepository` | count、enabled admin count、管理一覧、export rows |
| `SessionRepository` | create、get/touch、revoke |
| `ExternalServiceRepository` | get、save、bootstrap |
| `JobRepository` | create、get、list、claim、heartbeat、完了、失敗、取消、stale recovery |
| `ArtifactRepository` | register、active/expired list、deleted mark |

`AuthStore` は現在、ユーザー管理と接続プロファイルの SQL を含む互換ファサードである。新しい独立機能の SQL は Repository へ置き、AuthStore にはオーケストレーションと監査を残す。

## 6. 接続プロファイル

プロファイル名は大文字小文字非区別で一意とする。1 件だけ `is_default=1` にできる。保存時は管理者を検証し、空の password/PAT/PEM は既存値を保持する。明示的置換時だけ暗号文を更新する。

削除時は次を確認する。

1. 対象存在
2. 最低限必要な別プロファイルの有無
3. default の再割当
4. 実体化 PEM の削除
5. 監査記録

## 7. Jobs

`jobs` の状態は `queued`、`running`、`succeeded`、`failed`、`cancelled` の有限集合である。通常 payload と result は JSON、秘密部分は `secret_payload_ciphertext` に分離する。

`claim_next()` は一つの transaction で queued job を running にし、`attempt` を増やす。heartbeat、succeed、fail は期待 attempt を条件に更新し、stale recovery 後の古い実行者が結果を書き戻すことを防ぐ。

## 8. Artifacts

path は一意、size、SHA-256、metadata、作成、期限、論理削除を保持する。ファイルの削除成功後に `deleted_at` を設定する。台帳外ファイルを cleanup が勝手に削除してはならない。

## 9. バックアップ

`backup_database()` は SQLite online backup API を使用して WAL を含む一貫した複製を作り、コピー側で `PRAGMA integrity_check` を実行する。元 DB と同じパス、および既存 destination を拒否する。失敗した不完全 backup は削除する。

DB backup には暗号鍵と `uploads/` が含まれない。復旧単位として次を同期して管理する。

- SQLite backup
- 対応する CredentialVault key
- 必要な uploads/artifacts
- 同時点のアプリケーション version と設定

## 10. 並行性と整合性

- 短命 connection と WAL を使用する。
- 書込み transaction を短く保つ。
- 長い SDK またはネットワーク処理中に SQLite transaction を開いたままにしない。
- claim や lockout count の競合は一つの SQL update で解決する。
- DB ファイルを複数アプリプロセスで共有しない。

## 11. 検証項目

- 空 DB から version 9、各旧 version から version 9 を検証する。
- foreign key、unique、check 制約を確認する。
- default profile の一意性をサービス操作で保証する。
- job の二重 claim、attempt fencing、stale recovery を並行試験する。
- backup の integrity と鍵を含む復旧を確認する。
- secret columns、payload、audit に平文がないことを確認する。
