import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from google.adk.agents.llm_agent import Agent
from google.adk import Workflow
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import Event  # 静的グラフの分岐に必須
from google.genai.types import Content, Part

# --- Constants ---
GEMINI_MODEL = "vertex/gemini-2.5-flash"

api = FastAPI()
session_service = InMemorySessionService()

# --- 1. エージェントの定義 ---
review_agent = Agent(
    model=GEMINI_MODEL,
    name="pm_review_agent",
    description="ソースコードをレビューし、問題点を指摘する",
    instruction="""
    あなたは優秀なプロジェクトマネージャー（PM）の相棒となるAIです。
    提供されたコード差分（Diff）をレビューし、バグやリスクがあれば、開発者が素直に受け取れるよう、角を立てず丁寧な言葉で指摘してください。
    """
)

slack_agent = Agent(
    model=GEMINI_MODEL,
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
# 2. ルーター関数の定義（デコレータ不要）
# ==========================================
def check_retry_and_escalate(ctx):
    """
    セッションの状態から現在のリトライ回数と上限値を比較し、
    次にどのエージェントを起動するかを決定するルーターノード
    """
    # 状態から現在のリトライ回数を取得してカウントアップ
    current_retry = ctx.state.get("retry_count", 0) + 1
    ctx.state["retry_count"] = current_retry

    input_data = ctx.state.get("last_input", "No input")
    
    # 条件判定とルート（Event）の発行
    if current_retry > ctx.state.get("max_retries", 3):
        # 🌟 SOSルートへペイロードを乗せて発行
        yield Event(route="sos_route", payload=input_data)
    else:
        # 🌟 通常ルートへペイロードを乗せて発行
        yield Event(route="normal_route", payload=input_data)

# ==========================================
# 3. 静的ワークフロー（Graph）の定義
# ==========================================
pr_review_pipeline = Workflow(
    name="pr_static_pipeline",
    edges=[
        # ① 開始時、まずはルーター関数で回数をチェックする
        ("START", check_retry_and_escalate),
        
        # ② ルーター関数の出力（Eventのroute値）に応じて進路を分岐
        (check_retry_and_escalate, {
            "sos_route": slack_agent,      # 上限超過なら Slackエスカレーションへ
            "normal_route": review_agent   # 上限未満なら レビューエージェントへ
        })
        
        # ※ slack_agent, review_agent 実行後は自動的にフロー終了となります
    ]
)

# 3. FastAPI エンドポイント
class ReviewRequest(BaseModel):
    pr_id: str             # GitHubのPR番号などをセッションIDのベースにする
    code_diff: str
    max_retries: int = 3   # ユーザー設定可能なリトライ上限（デフォルト3）

@api.post("/review")
async def run_review(request: ReviewRequest):
    try:
        # PRごとにユニークなセッションIDを作成し、過去の会話や状態（カウント）を保持
        session_id = f"github-pr-{request.pr_id}"
        user_id = "github_actions_bot"
        app_name = "pm-workflow-platform"
        
        # セッションを明示的に作成（必須）
        await session_service.create_session(
            session_id=session_id,
            user_id=user_id,
            app_name=app_name,
            state={
                "last_input": request.code_diff, 
                "max_retries": request.max_retries
            }
        )
        
        # ランナーの初期化
        runner = Runner(
            agent=pr_review_pipeline, 
            session_service=session_service,
            app_name=app_name
        )
        
        prompt_text = f"以下のコード差分をチェックしてください：\n{request.code_diff}"
        new_message = Content(
            role="user", 
            parts=[Part.from_text(text=prompt_text)]
        )
        
        agent_response_text = ""
        
        print("[Workflow] 静的ワークフローを非同期実行します...")
        
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message,
        ):
            # 1. これが「最終回答」のイベントかどうかをチェック
            if event.is_final_response():
                # 2. 最終回答イベントの中にメッセージがあるか安全に確認
                if event.message and event.message.parts:
                    # 3. 最初のパーツからテキストを取り出す
                    agent_response_text = event.message.parts[0].text
                    break  # 最終回答が得られたのでループを抜ける
        
        return {
            "status": "success",
            "adk_version": "2.0 Static Graph",
            "session_id": session_id,
            "agent_response": agent_response_text
        }
        
    except Exception as e:
        print(f"[Workflow] エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(api, host="0.0.0.0", port=port)
