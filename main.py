import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Google ADK 関連のインポート
from google.adk.app import App
from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

# FastAPIのアプリケーション
api = FastAPI()

# 1. ADKエージェントの定義（スタッフ）
review_agent = Agent(
    model="gemini-2.5-flash",
    name="pm_review_agent",
    description="ソースコードの差分を検出し、レビューと指摘を行うPMの相棒エージェントです。",
    instruction="""
    あなたは優秀なプロジェクトマネージャー（PM）の相棒となるAIエージェントです。
    提出されたコード差分（Diff）をレビューし、以下の基準で出力してください：
    1. 修正が必要な問題点（バグやリスク）があるか
    2. 修正すべき内容を、開発者が一発で理解できるよう、角を立てず丁寧な言葉で言語化する
    """
)

# 2. ADKアプリケーションの定義（部署）
adk_app = App(
    name="pm-review-platform",
    agents=[review_agent]
)

# 受信データの構造
class ReviewRequest(BaseModel):
    code_diff: str

@api.get("/")
def read_root():
    return {"message": "Google ADK PM Agent (App Structured) is running!"}

@api.post("/review")
async def run_review(request: ReviewRequest):
    try:
        print(f"[ADK Agent] レビューリクエストを受信しました。")
        
        # 3. Runnerには Agent ではなく App を渡す
        session_service = InMemorySessionService()
        runner = Runner(
            app=adk_app,
            session_service=session_service
        )
        
        session_id = "hackathon-test-session"
        
        # どのエージェントに処理させるかを指定して実行
        response = runner.query(
            session_id=session_id,
            agent_name="pm_review_agent",
            text=f"以下のコード差分をレビューしてください：\n\n{request.code_diff}"
        )
        
        return {
            "status": "success",
            "agent_response": response.text
        }
        
    except Exception as e:
        print(f"[ADK Agent] エラーが発生しました: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(api, host="0.0.0.0", port=port)
