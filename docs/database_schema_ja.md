# SQLite コントロールプレーンのスキーマ

> **言語:** [English](database_schema.md) | 日本語
<!-- Source-SHA256: 4063aa2500725a2738e9981418c0bd13388b93525be9d75413ca10262c760b39 -->

teradataevsui のスキーマバージョン 9 は、`app/db/migrations.py` から作成およびアップグレードされます。ランタイムファイル `data/evsui.db` は意図的にコミットされません。ソース管理には再現可能なスキーマを格納し、各環境がそれぞれのユーザー、セッション、暗号化された認証情報、ジョブ、および監査履歴を保持します。

| テーブル | 主キー | 主な関連と用途 |
|---|---|---|
| `schema_versions` | `version` | 適用された各連番付きマイグレーションを記録 |
| `users` | `id` | アカウント、Argon2 パスワードハッシュ、ロール、有効化／ロックアウト状態、ログイン日時 |
| `sessions` | `session_id_hash` | `user_id → users.id`。有効期限と失効機能を持つサーバーサイドセッション |
| `permissions` | `id` | `user_id → users.id`。リソース単位の読み取り／書き込み／管理権限 |
| `audit_logs` | `id` | 任意の `user_id → users.id`。セキュリティおよび管理イベント |
| `system_connection_profiles` | `id` | 再利用可能な名前付き Teradata プロファイル。1 つを既定に設定可能 |
| `external_service_configs` | `service_name` | 共有外部サービスのエンドポイントと暗号化された API キー |
| `jobs` | `id` | `owner_user_id → users.id`、`connection_profile_id → system_connection_profiles.id`。永続ワークフローの状態、進捗、ハートビート、コマンド／結果 JSON |
| `artifacts` | `id` | 任意の `job_id → jobs.id`、`owner_user_id → users.id`。生成／アップロードされたファイルのインベントリと有効期限 |
| `connection_configs` | `user_id` | ユーザー単位の旧接続設定との互換性を保つテーブル |
| `system_connection_config` | `config_id=1` | 単一接続を使用していた旧構成との互換性を保つテーブル |

機密性の高い列は、デプロイ時の Fernet キーで暗号化されます。

- `system_connection_profiles.password_ciphertext`, `pat_token_ciphertext`, `pem_ciphertext`
- `external_service_configs.api_key_ciphertext`
- 任意の VLM プロバイダーキーなど、一時的なフォームシークレットを格納する `jobs.secret_payload_ciphertext`

ジョブのシークレット暗号文は、ジョブの成功、失敗、またはキャンセル時に消去されます。PEM の内容は SQLite に暗号化して保存され、SDK がファイルパスを必要とするときに、追跡対象外でアクセス制限された `pem_runtime/` ディレクトリへ実体化されます。認証情報キーをデータベースと一緒にバックアップしてください。データベースだけではこれらの値を復号できません。

データベースの作成またはアップグレード、およびマイグレーション状態の確認には、次のコマンドを使用します。

```powershell
python -m app.db migrate
python -m app.db status
```

稼働中のデータベースには、オンラインバックアップコマンドを使用してください。

```powershell
python -m app.db backup
```
