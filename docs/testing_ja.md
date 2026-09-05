# teradataevsui テスト

> **言語:** [English](testing.md) | 日本語
<!-- Source-SHA256: 874b012f6545e21fa7c6150d571dfcae835cd8cf45c7268919e17503ba415dac -->

テストは意図的に、ユニット／サービスの回帰テスト、実際の HTTP ルートコントラクト、実際のブラウザー操作、および**明示的に有効化する読み取り専用**の外部接続確認に分けています。ユニットテストスイートが成功しただけでは、ブラウザーワークフローが動作すると認定できません。

## ローカルでの実行（PowerShell）

```powershell
uv lock --check
uv sync --locked --extra browser
uv run --locked --no-sync playwright install chromium
uv pip check
uv sync --locked --extra browser --check
uv run --locked --no-sync python scripts/check_dependencies.py
uv run --locked --no-sync python scripts/check_publication.py
uv run --locked --no-sync python scripts/check_doc_parity.py
uv run --locked --no-sync ruff check app tests scripts
uv run --locked --no-sync python -m compileall -q app scripts
uv run --locked --no-sync python -m unittest discover -s tests -v
```

ブラウザーテストは既定でスキップされます。UI を変更した場合は、**必ずこちらも実行**してください。

```powershell
$env:EVSUI_BROWSER_TESTS = "1"
# Optional: use installed Microsoft Edge instead of downloaded Chromium.
$env:EVSUI_BROWSER_CHANNEL = "msedge"
uv run --locked --no-sync python -m unittest tests.test_browser_actions tests.test_frontend_parameters -v
uv build --clear
uv run --locked --no-sync python scripts/verify_wheel.py
uv sync --locked --no-dev --no-install-project
uv pip check
uv sync --locked --no-dev --no-install-project --check
# Restore the local test environment after validating the production set.
uv sync --locked --extra browser
```

CI はインストール済みの Chromium を使用して、ブラウザーを使用しないスイートとブラウザースイートの両方を実行します。ブラウザーリクエストのステータス証跡とスクリーンショットは `test-results/` 以下に出力され、CI によってアップロードされます。個々の実行で生成されたランタイムデータとレポートはコミットしません。CSP による実行失敗を含め、捕捉されていないブラウザーの JavaScript エラーがあるとテストは失敗します。ロック検査と正確な同期により、宣言されていないパッケージや孤立したパッケージがプロジェクト環境に残ることを防ぎます。

## ブラウザーテストが実際に確認する内容

`tests/e2e_support.py` は一時ポートで実際のローカル Uvicorn/FastAPI サーバーを起動し、本番用のルーター、ミドルウェア、Jinja テンプレート、HTMX、および JavaScript を使用します。ユーザー、暗号化されたプロファイル、セッション、ジョブ、アップロードファイルには、破棄可能な SQLite と一時ディレクトリを使用します。Teradata と Unstructured の**サービス境界**には決定論的なフィクスチャを使用しますが、ブラウザーイベント、HTTP レスポンス、および認証はモック化しません。段階的ワークフローのテストでは、制御されたサービス結果を用いて実際の SQLite ジョブを完了させた後、ブラウザーによる実際のポーリングと次のフォーム操作を検証します。

| 領域 | ブラウザー操作 | バックエンド／サービス検査 |
|---|---|---|
| 認証 | ログイン失敗、ログイン、ログアウト、ロール別ナビゲーション | 匿名アクセスの拒否、無効化ユーザー、パスワードリセット／インポート時のセッション失効、最後の管理者の保護 |
| システム設定 | 接続の作成／編集／削除のキャンセルと確定、外部キーの保存／維持／消去、ユーザーの作成／ロール変更／無効化／有効化／リセット | 新規プロファイルがシークレットを継承しないこと、空欄の更新でシークレットが維持されること、無効な PEM／インポートの処理、管理者限定の変更操作 |
| 接続管理 | 接続／切断、ヘルスチェック、一覧表示、行選択、削除のキャンセルと確定 | ランタイムのアクティブ化、セッション分離、切断状態と権限のガード、削除検証 |
| 作成 | アップロード、3 種類のドキュメントモード、ルート／プロバイダー／モデル／アルゴリズム／チャンキング／エンリッチメント、長いキー、キュー登録／ポーリング／キャンセル | 7 種類のジョブ、検証、暗号化されたコマンド、部分的失敗、インデックス準備完了、再試行／タイムアウト／破損ペイロードの処理 |
| 段階的 CSV ワークフロー | 解析 → 生成 → ロード → ロード済み実行の選択という 2 種類のフロー | マニフェストのコントラクト、ファイルの解析／変換、接続の関連付け、中断されたロードの拒否 |
| 検索 | 一覧／選択、質問、類似検索、BookRAG API のモード／top_k／送信、消去 | GET/POST API の検証とレスポンススキーマ、認証、コンテキスト欠落、セッション別履歴 |
| メタデータガバナンス | 未選択状態での更新、ロード、編集、CSV エクスポート／インポート、自動入力、読み取り専用ビューアー | 書き込み前の CSV 全体検証、無効／空／切断／未認可リクエスト |
| ドキュメント関係 | 未選択状態での更新、初期化、追加／編集／エクスポート／削除 | 関係の検証、CSV インポート、永続化／スキーマルール、権限 |
| JSON Inspector | フィルタリング、結果なしの場合の詳細消去／復元 | 許可されたルート、パストラバーサルの拒否、不正なドキュメント |
| レイアウト／セキュリティ | デスクトップ／ラップトップ／タブレット幅、無効化／非表示コントロール、CSP に準拠した確認と行選択 | Origin 検証、シークレットの秘匿化、ロール降格の即時反映 |
| 永続化／運用 | ブラウザーでの SQLite ジョブ進捗とキャンセル | マイグレーション／バックアップ、ジョブ取得の競合、古い試行のフェンシング、アーティファクトライフサイクル、wheel 除外 |

## 読み取り専用の実環境確認

これは **CI または通常のテスト検出では実行されません**。設定済み SQLite ファイルのトランザクション整合性を保ったスナップショットを読み取り、PEM は一時ディレクトリ内にのみ実体化し、期限を指定した別の SDK プロセスを起動します。

```powershell
.venv\Scripts\python.exe scripts/check_live_connection.py --read-only-live --timeout 90
# Optional: --profile-id <saved profile ID>
```

操作は接続／認証、`SELECT 1`、`VSManager.list()`、`VSManager.health()` に限定されます。認証情報の漏洩を防ぐため、SDK の生の出力とエラーは抑制されます。Health が例外なく返ることはそのまま報告されますが、一覧に含まれるすべてのストアが正常であることを保証するものではありません。元のアプリケーションレコード／アップロードは変更されません。このヘルパー自体にも、明示的な有効化、スナップショット、タイムアウト、出力安全性のテストがあります。

## この受け入れ基準の限界

- 自動テストは、実際の Vector Store の作成／削除、実テーブルの上書き、実際のドキュメントメタデータの変更、または課金対象となる解析／モデルリクエストの送信を行いません。
- 実環境でのリモート書き込み受け入れには、専用の破棄可能な Teradata データベース、個別のテスト認証情報、および承認済みの Unstructured／モデル利用枠が必要です。
- CSV 行は最初の書き込み前に検証されますが、SQL が途中で失敗した場合にリモートトランザクション全体が完全に成功または完全に失敗することを保証するものではありません。
- ジョブリカバリは、すべての外部操作を再開できる仕組みではありません。中断された CSV ロードを調査し、確認せずに別のロードを開始しないでください。アプリケーションは一度に 1 件のバックグラウンドジョブを実行します。
- このスイートは行カバレッジ率を計算しません。ブラウザーシナリオは、負荷テスト、侵入テスト、またはすべてのブラウザー／デバイス組み合わせのテストにはなりません。

個別の実行レポート、スクリーンショット、および環境固有の証跡は、公開ドキュメントではなく、追跡対象外のローカルディレクトリまたは明示的にレビューされた CI アーティファクトに保存してください。変更を提出する前に、[公開前検査](publishing_ja.md) を参照してください。
