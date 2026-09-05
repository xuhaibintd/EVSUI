# AI エージェント向けリポジトリ指示

ソースコード、設定、データベース、ジョブ、スクリプト、テスト、依存関係、または内部設計を変更する前に、`detailed-design/INDEX.md`、`detailed-design/01_SYSTEM_ARCHITECTURE.md`、`detailed-design/14_MODULE_CATALOG.md` および対象機能の設計書を読むこと。

UI、HTML、Jinja2、HTMX、ブラウザー JavaScript、CSS、画面用ルーター、または画面テストを変更する前に、上記に加えて `detailed-design/UI_DESIGN.md` を全文読むこと。

`detailed-design/UI_DESIGN.md` は本リポジトリの UI 規範である。特に、トップの唯一の操作メッセージ、Vector Store 表の 6 列、Description と BookRAG の実データ判定、ローカルで即時に完了する行選択、エラー後のレイアウト維持、レスポンシブ表示、および変更後のブラウザー回帰確認を省略してはならない。

すべての変更報告には、影響を受けた設計書と規則 ID、変更したモジュール、成功経路と失敗経路の検証結果、および関連テストの結果を含めること。UI 変更では、関連するフロントエンド・バックエンドテストとブラウザー回帰確認を必須とする。
