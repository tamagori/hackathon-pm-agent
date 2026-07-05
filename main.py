import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Google ADK 2.0 正しいインポートパス
from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow  # 🌟 正解は単数形の `workflow`

api = FastAPI()

# ==========================================
# 1. エージェントの定義
# ==========================================
review_agent = Agent(
    model="gemini-2.5-flash",
    name="pm_review_agent",
    description="ソースコードをレビューし、問題点を指摘する",
    instruction="""
    あなたは優秀なプロジェクトマネージャー（PM）の相棒となるAIです。
    提供されたコード差分（Diff）をレビューし、バグやリスクがあれば、
    開発者が素直に受け取れるよう、角を立てず丁寧な言葉で指摘してください。
    """
)

slack_agent = Agent(
    model="gemini-2.5-flash",
    name="slack_sos_agent",
    description="レビュー結果を受け取り、PM宛のエスカレーション文面を作成する",
    instruction="""
    あなたはPMのサポートAIです。
    前のプロセス（レビュー担当AI）から、問題のあるコードの分析結果が渡されます。
    それを受け取り、人間のPMへSlackで送信するための「至急フォローをお願いします」という
    要約されたエスカレーション（SOS）メッセージを作成してください。
    """
)

# ==========================================
# 2. FastAPI エンドポイント
# ==========================================
class ReviewRequest(BaseModel):
    code_diff: str
    retry_count: int = 0

@api.get("/")
def read_root():
    return {"message": "DevOps PM Agent (ADK v2.0 Graph Engine) is running!"}

@api.post("/review")
async def run_review(request: ReviewRequest):
    try:
        session_service = InMemorySessionService()
        session_id = "hackathon-pr-session-graph"
        
        # 🌟 ここが ADK 2.0 の醍醐味：グラフ（エッジ）の動的構築
        if request.retry_count >= 3:
            print("[Workflow] ⚠️ 泥沼化を検知。レビュー ➔ SOS の直列グラフを実行します。")
            # START -> レビューAI -> SlackSOS AI へと出力を自動で受け渡すパイプライン
            active_workflow = Workflow(
                name="escalation_pipeline",
                edges=[("START", review_agent, slack_agent)]
            )
        else:
            print("[Workflow] 正常ルート：単一ノードのグラフを実行します。")
            active_workflow = Workflow(
                name="review_pipeline",
                edges=[("START", review_agent)]
            )

        # RunnerにはAgentではなく構築したWorkflowを渡す
        runner = Runner(
            agent=active_workflow, 
            session_service=session_service,
            app_name="pm-workflow-platform"
        )
        
        prompt_text = f"以下のコード差分をレビューしてください：\n{request.code_diff}"
        
        # ワークフローグラフの実行
        response = runner.run(
            session_id=session_id,
            text=prompt_text
        )
        
        return {
            "status": "success",
            "adk_version": "2.0 Graph Engine",
            "agent_response": response.text
        }
        
    except Exception as e:
        print(f"[Workflow] エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(api, host="0.0.0.0", port=port)
