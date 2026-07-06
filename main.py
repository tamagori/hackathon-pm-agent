import os
import json
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from google.auth import default
from google.adk.agents.llm_agent import Agent
from google.adk.workflow import Workflow, START, END
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import Event
from google.genai.types import Content, Part, GenerateContentConfig

# --- Constants ---
GEMINI_MODEL = "gemini-2.5-flash"

api = FastAPI()
session_service = InMemorySessionService()
    
# ADK 2.0 用の環境変数インジェクション
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GOOGLE_CLOUD_PROJECT"] = "ai-agent-hackathon-2026"
os.environ["GOOGLE_CLOUD_LOCATION"] = "asia-northeast1"

# ==========================================
# 1. 構造化出力のための Pydantic モデル定義
# ==========================================

class ReviewResultSchema(BaseModel):
    """ノードA (AIレビュー) の出力用スキーマ"""
    is_pass: bool = Field(description="コードに重大な問題やバグがなければ true、修正が必要なら false")
    reason: str = Field(description="判定に至った理由や、開発者への具体的な修正・改善のアドバイス。日本語で記入すること。")

class PMApprovalSchema(BaseModel):
    """ノードB (PM承認) の出力用スキーマ"""
    is_approved: bool = Field(description="仕様やビジネス要件を満たしており、マージして良ければ true、却下なら false")
    feedback: str = Field(description="PMとしてのフィードバックコメント。日本語で記入すること。")


# ==========================================
# 2. エージェントの定義 (Schemaを割り当て)
# ==========================================

# [ノードA: AIがレビューする]
review_agent = Agent(
    model=GEMINI_MODEL,
    name="ai_review_agent",
    description="ソースコードをレビューし、JSON形式で合否を判定する",
    instruction="""
    あなたは厳格かつフェアなコードレビュアーAIです。
    提供されたコード差分（Diff）をレビューしてください。
    指定されたスキーマに従い、必ずJSONフォーマットで結果を返してください。
    【出力ルール】
    判定結果は必ず以下のようなJSONのみで出力してください。
    {
      "is_pass": true,
      "reason": "開発者への具体的なフィードバック"
    }
    ※これ以外の挨拶や解説文は一切不要です。
    """,
    output_schema=ReviewResultSchema,
    output_key="review_result"
)

# [ノードB: PM承認]
pm_approval_agent = Agent(
    model=GEMINI_MODEL,
    name="pm_approval_agent",
    description="AIレビューを通過したコードに対し、仕様や要件の観点から最終承認をJSONで行う",
    instruction="""
    あなたはプロジェクトマネージャー（PM）AIです。
    AIレビューを通過したコードと理由を確認し、仕様を満たしているか判断します。
    指定されたスキーマに従い、必ずJSONフォーマットで結果を返してください。
    【出力ルール】
    判定結果は必ず以下のようなJSONのみで出力してください。
    {
      "is_approved": true,
      "feedback": "PMとしてのフィードバック"
    }
    ※これ以外の挨拶や解説文は一切不要です。
    """,
    output_schema=PMApprovalSchema,
    output_key="approval_result"
)

# [ノードC: 担当者へ差し戻し] (ここは開発者へのメッセージなので通常のテキスト出力)
feedback_agent = Agent(
    model=GEMINI_MODEL,
    name="feedback_agent",
    description="開発者へ差し戻しのフィードバックを作成する",
    instruction="""
    あなたは開発者をサポートするAIです。
    直前のプロセスによるレビュー結果（不合格や却下理由）を受け取り、
    開発者が次に何を修正すべきか、モチベーションを下げないように丁寧で具体的な改善案をテキストで提示してください。
    """
)

# [ノードD: SlackへSOS] (ここもSlack通知用のテキスト出力)
slack_agent = Agent(
    model=GEMINI_MODEL,
    name="slack_sos_agent",
    description="泥沼化しているPRについて、人間のPMへエスカレーション文面を作成する",
    instruction="""
    あなたはPMのサポートAIです。
    これまでのレビュープロセスが難航している状況を要約し、
    人間のPMへSlackで送信するための「至急フォローをお願いします（SOS）」メッセージを作成してください。
    """
)

# ==========================================
# 3. ルーター関数の定義 (JSONをパースして完全自律化)
# ==========================================

def evaluate_review_result(output: ReviewResultSchema):
    """【エッジ: AIの合否判定】ノードAが返したJSONを解析して分岐"""
    if output.is_pass:
        yield Event(route="pass_route", payload="AIレビュー合格")
    else:
        yield Event(route="fail_route", payload="AIレビュー不合格")

def evaluate_pm_approval(output: PMApprovalSchema):
    """【エッジ: PM承認の分岐】ノードBが返したJSONを解析して分岐"""
    if output.is_approved:
        yield Event(route="approve_route", payload="PM承認完了")
    else:
        yield Event(route="reject_route", payload="PM却下")

def check_risk_hedge(ctx):
    """【エッジ: リスクヘッジの条件分岐】リトライ回数等からSOSか通常の差し戻しか判定する"""
    current_retry = ctx.state.get("retry_count", 0) + 1
    ctx.state["retry_count"] = current_retry
    max_retries = ctx.state.get("max_retries", 3)
    
    is_deadline_tight = ctx.state.get("is_deadline_tight", False)
    
    if current_retry >= max_retries or is_deadline_tight:
        yield Event(route="sos_route", payload="泥沼化・強制エスカレーション")
    else:
        yield Event(route="normal_return_route", payload="通常の差し戻し")

# ==========================================
# 4. 静的ワークフロー（Graph）の定義
# ==========================================
pr_review_pipeline = Workflow(
    name="advanced_pr_pipeline",
    edges=[
        (START, review_agent),
        (review_agent, evaluate_review_result),
        (
            evaluate_review_result,
            {
            "pass_route": pm_approval_agent,
            "fail_route": check_risk_hedge
            }
        ),
        (pm_approval_agent, evaluate_pm_approval),
        (
            evaluate_pm_approval,
            {
            "approve_route": END, # 承認時は即終了（マージOK）
            "reject_route": feedback_agent
            }
        ),
        (
            check_risk_hedge,
            {
            "normal_return_route": feedback_agent,
            "sos_route": slack_agent
            }
        )
    ]
)

# ==========================================
# 5. FastAPI エンドポイント
# ==========================================
class ReviewRequest(BaseModel):
    pr_id: str
    code_diff: str
    max_retries: int = 3
    is_deadline_tight: bool = False

@api.post("/review")
async def run_review(request: ReviewRequest):
    try:
        session_id = f"github-pr-{request.pr_id}"
        user_id = "github_actions_bot"
        app_name = "pm-workflow-platform"

        runner = Runner(
            agent=pr_review_pipeline, 
            session_service=session_service,
            app_name=app_name
        )
        
        try:
            session = await session_service.create_session(
                session_id=session_id,
                user_id=user_id,
                app_name=app_name,
                state={
                    "max_retries": request.max_retries,
                    "is_deadline_tight": request.is_deadline_tight,
                    "retry_count": 0
                }
            )
        except Exception:
            session = await session_service.get_session(
                session_id=session_id,
                user_id=user_id,
                app_name=app_name,
            )
        
        prompt_text = f"以下のコード差分をチェックし、ワークフローに従って対応してください：\n{request.code_diff}"
        new_message = Content(
            role="user", 
            parts=[Part.from_text(text=prompt_text)]
        )

        is_pass = None
        is_approved = None
        reason = None
        feedback = None
        agent_response_text = ""
        
        print("[Workflow] 完全自律型ワークフローを非同期実行します...")
        
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message,
        ):
            # イベントにテキストが含まれている場合、すべてJSONかテキストとしてチェック
            if event.message and event.message.parts:
                text = event.message.parts[0].text.strip()
                
                # 1. まずJSONとしてパースを試みる（AIの判定結果）
                try:
                    data = json.loads(text)
                    if "is_pass" in data and is_pass is None:
                        is_pass = data["is_pass"]
                        reason = data.get("reason", "")
                    if "is_approved" in data and is_approved is None:
                        is_approved = data["is_approved"]
                        feedback = data.get("feedback", "")
                    
                    # JSONだった場合、それはエージェントの「思考結果」なので、
                    # 最終回答には「AIが判定しました」という簡潔なテキストを入れる
                    agent_response_text = "AIによる判定が完了しました。"
                except json.JSONDecodeError:
                    # 2. JSONでなければ、それは人間への説明文（agent_response）
                    agent_response_text = text
                    
            # 1. これが「最終回答」のイベントかどうかをチェック
            if event.is_final_response():
                break
        
        latest_session = await session_service.get_session(
            session_id=session_id,
            user_id=user_id,
            app_name=app_name,
        )

        # 最終的な回答（テキスト）を返却
        return {
            "status": "success",
            "session_id": session_id,
            "current_retry_count": latest_session.state.get("retry_count"),
            "is_pass": is_pass,
            "is_approved": is_approved,
            "reason": reason,
            "feedback": feedback,
            "agent_response": agent_response_text
        }
        
    except Exception as e:
        print(f"[Workflow] エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(api, host="0.0.0.0", port=port)
