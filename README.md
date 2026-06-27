# hackathon-pm-agent

## 💡 プロダクト概要
ハッカソンMVPゴール：『PMの相棒：自律型レビュー＆指摘ループ・マネージャー』のバックエンドシステム。
Pull Request（PR）の変更差分をトリガーに、Geminiが自律的にコードレビューを行い、PRコメントを自動投稿するエージェントシステムです。

---

## 🏗️ 現在のリポジトリステータス・実現内容

本リポジトリは、ハッカソンの要件（つくる・まわす・とどける）に基づき、**「本番品質のセキュアな自動デプロイインフラ」**と**「キーレスでのAI（Gemini）疎通導線」**の構築まで完了しています。

### 1. つくる（AI / パッケージ管理）
- **Vertex AI SDKのインテグレーション完了**
  - `main.py` 内に `google-cloud-aiplatform` を組み込み。FastAPIの起動時（`startup`）に、Google Cloud（Vertex AI）上の最新モデル `gemini-2.5-flash` を呼び出せる脳みそを実装済み。
- **拡張性の高いパッケージ管理構造**
  - パッケージ管理を `requirements.txt` に集約・外部ファイル化。Dockerfileをいじることなく、今後必要なライブラリ（LangGraphなど）を気軽に増減できる変化に強い構造へリファクタリング済み。

### 2. まわす ＆ とどける（CI/CD / インフラ / 認証）
- **完全キーレス（WIF）自動デプロイライン**
  - `git push main` をトリガーに、GitHub Actions（`deploy.yml`）から Workload Identity 連携（WIF）を経由して Google Cloud へキーレス認証するデプロイラインが完全開通。
- **Infrastructure as Code（設定自動化）の組み込み**
  - Cloud Runへのコンテナデプロイ時、専用のサービスアカウント（`GCP_SERVICE_ACCOUNT`）と認証スコープ（`cloud-platform`）を Actions 側から自動でガチッと固定してリビジョンを生成する仕組みを構築。手動設定への先祖返りリスクを排除。
- **疎通確認済みの死活監視エンドポイント**
  - Cloud Run上にWebサーバー（FastAPI）が常時待機（リクエスト0時は0インスタンス自動スケーリング）。URLアクセスによりコンテナが起動し、正常にGeminiからの応答がサーバーログに刻まれるファクトを確認済み。

---

## 📂 ファイル構成と役割

```text
├── .github/
│   └── workflows/
│       └── deploy.yml  # WIFキーレス認証によるCloud Runへの自動デプロイ設計図
├── Dockerfile          # uvマネージャーを使用した超高速コンテナビルドの設計図
├── requirements.txt    # 変化に強い、依存パッケージ管理用の外部ファイル
└── main.py             # FastAPIによるWeb受付 兼 Gemini(Vertex AI)起動疎通ロジック
