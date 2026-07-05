import os
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Google ADK 関連のインポート
from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

app = FastAPI()

# 1. ADKエージェントの定義（model, name, description, instruction）
# WIFの権限（Agent Platformユーザー）があるため、APIキーなしでVertex AI経由で駆動します
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

# 受信データの構造（疎通確認用）
class ReviewRequest(BaseModel):
    code_diff: str

@app.get("/")
def read_root():
    return {"message": "Google ADK PM Agent baseline is running!"}

@app.post("/review")
async def run_review(request: ReviewRequest):
    try:
        print(f"[ADK Agent] レビューリクエストを受信しました。")
        
        # 2. ADKのセッションサービスとランナーの初期化（プログラム実行パターン）
        session_service = InMemorySessionService()
        runner = Runner(agent=review_agent, session_service=session_service)
        
        # 3. セッションを開始してクエリを実行
        session_id = "hackathon-test-session"
        # ADKのqueryメソッドにコード差分を投入
        response = runner.query(
            session_id=session_id,
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
    uvicorn.run(app, host="0.0.0.0", port=port)
