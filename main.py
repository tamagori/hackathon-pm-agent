import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Google ADK 関連のインポート
from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflows import Workflow  # 🌟 拡張性の要：Workflowをインポート

api = FastAPI()

# ==========================================
# 1. エージェント（ノード）の定義
# ==========================================
# ① レビュー担当エージェント
review_agent = Agent(
    model="gemini-2.5-flash",
    name="pm_review_agent",
    description="ソースコードの差分を検出し、レビューと指摘を行う",
    instruction="""
    あなたは優秀なプロジェクトマネージャー（PM）の相棒となるAIです。
    提供されたコード差分（Diff）をレビューし、バグやリスクがあれば、
    開発者が素直に受け取れるよう、角を立てず丁寧な言葉で指摘してください。
    """
)

# ② Slack通知（SOS）担当エージェント
slack_agent = Agent(
    model="gemini-2.5-flash",
    name="slack_sos_agent",
    description="泥沼化を検知した際に、人間のPMへSOSの文章を生成する",
    instruction="""
    あなたはPMのサポートAIです。開発者が同じPRで何度も修正につまずいています。
    人間のPM（あなたの上司）に向けて、Slackで送信するためのエスカレーション（SOS）メッセージを作成してください。
    「至急、人間による直接のフォローアップが必要です」というニュアンスを含めてください。
    """
)

# ==========================================
# 2. Workflow（グラフ）の定義
# ==========================================
# ※ADKのバージョンや仕様に応じて、細かなルーティング構文は調整可能ですが、
# 今回は「状態（retry_count）に応じて動的に呼び出すエージェントを切り替える」
# というWorkflowのオーケストレーションの基礎をRunner側で制御する確実な手法をとります。
pm_workflow = Workflow(name="pm_review_pipeline")
pm_workflow.add_node("ReviewStep", review_agent)
pm_workflow.add_node("SlackSOSStep", slack_agent)


# ==========================================
# 3. FastAPI エンドポイント
# ==========================================
# テスト用に retry_count（現在のやり直し回数）を受け取れるように拡張
class ReviewRequest(BaseModel):
    code_diff: str
    retry_count: int = 0  # デフォルトは0（初回レビュー）

@api.get("/")
def read_root():
    return {"message": "DevOps PM Agent (Workflow Version) is running!"}

@api.post("/review")
async def run_review(request: ReviewRequest):
    try:
        print(f"[Pipeline] リクエスト受信 (現在のやり直し回数: {request.retry_count}回)")
        
        session_service = InMemorySessionService()
        session_id = "hackathon-pr-session-001"
        
        # 🌟 条件分岐（ルーターロジック）
        # やり直しが3回以上なら、レビューを諦めて強制的にSlack SOSエージェントへ流す
        if request.retry_count >= 3:
            print("[Pipeline] ⚠️ 泥沼化を検知。Slack SOSルートへ分岐します。")
            target_agent = slack_agent
            prompt_text = f"以下のコード修正で{request.retry_count}回目のスタックが発生しました。SOS文を作ってください。\nコード: {request.code_diff}"
        else:
            print("[Pipeline] 正常ルート：コードレビューを実行します。")
            target_agent = review_agent
            prompt_text = f"以下のコード差分をレビューしてください：\n{request.code_diff}"

        # 実行（Workflowのコンポーネントとして動的にAgentを呼び出す）
        runner = Runner(
            agent=target_agent, 
            session_service=session_service,
            app_name="pm-workflow-app"
        )
        
        response = runner.query(
            session_id=session_id,
            text=prompt_text
        )
        
        return {
            "status": "success",
            "route_taken": "Slack_SOS" if request.retry_count >= 3 else "Normal_Review",
            "agent_response": response.text
        }
        
    except Exception as e:
        print(f"[Pipeline] エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(api, host="0.0.0.0", port=port)
