# hackathon-pm-agent
---
## 🛠 開発ログ

### 2026/06/27：DevOps基盤の構築完了
- **実施内容**:
  - Google Cloud側でWorkload Identity連携（WIF）の設定を完了（プールおよびプロバイダの作成、IAMバインディング）。
  - Google Cloud側のAPI有効化（IAM Service Account Credentials API, Cloud Run Admin API）を実施。
  - GitHub Actionsによる自動デプロイライン（CI/CD）の構築完了。
  - Cloud Runへの自動デプロイ成功を確認（エンドポイント発行済み）。
- **成果**:
  - `git push` するだけで自動的にコンテナがビルドされ、Cloud Runへ反映される「まわす・とどける」環境が完成。

### ⏭️ 次回実施予定
- **タスク**:
  - AIエージェント（`main.py`）へのGemini APIの実装開始。
  - 最小限のプロンプトで、AIがタスクを解釈し回答するロジックの構築。
- **目標**:
  - ローカル環境でGemini APIが正常に動作することを確認する。
