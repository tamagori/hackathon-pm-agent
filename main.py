import os
import json
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from google.auth import default
from google.adk.events import RequestInput
from google.adk import Agent, Context, Event, Workflow
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part, GenerateContentConfig

# --- Constants ---
GEMINI_MODEL = "gemini-2.5-flash"

api = FastAPI()
session_service = InMemorySessionService()
    
# ADK 2.0 用の環境変数インジェクション
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GOOGLE_CLOUD_PROJECT"] = "ai-agent-hackathon-2026"
os.environ["GOOGLE_CLOUD_LOCATION"] = "asia-northeast1"

def node_message(node_name: str, text: str) -> str:
    return f"[NODE] {node_name}\n{text}"

# ==========================================
# 1. 構造化出力のための Pydantic モデル定義
# ==========================================

class ReviewResultSchema(BaseModel):
    is_pass: bool = Field(
        description="コードに重大な問題やバグがなければ true、修正が必要なら false"
    )
    review_summary: str = Field(
        description="判定の要約。レビューを通過するかどうかの理由"
    )
    findings: str = Field(
        description="具体的な指摘内容、修正すべき点、改善案"
    )

class AutoFixResultSchema(BaseModel):
    fixed_code_diff: str = Field(
        description="指摘に基づいて自動修正されたコード差分"
    )

class PMDecisionSchema(BaseModel):
    is_approved: bool = Field(...)
    pm_comments: str = Field(...)

class ReviewResponseSchema(BaseModel):
    status: str
    session_id: str
    pr_id: str
    current_retry_count: int | None = None
    review: dict

# ==========================================
# 2. エージェントの定義 (Schemaを割り当て)
# ==========================================

# エージェントがコード差分をレビューする
review_agent = Agent(
    model=GEMINI_MODEL,
    name="ai_review_agent",
    description="ソースコードをレビューし、JSON形式で合否を判定する",
    instruction="""
    あなたは厳格かつフェアなコードレビュアーAIです。
    提供されたコード差分（Diff）をレビューしてください。
    指定されたスキーマに従い、必ずJSONフォーマットで結果を返してください。
    【出力ルール】
    判定結果は必ず以下のJSONのみを出力してください。
    {
      "is_pass": true,
      "review_summary": "判定理由の要約",
      "findings": "具体的な指摘内容 / 修正案"
    }
    このJSON以外のテキスト（挨拶や補足説明）は一切不要です。
    """,
    output_schema=ReviewResultSchema,
)

# エージェントがコード差分を自動修正する
auto_fix_agent = Agent(
    model=GEMINI_MODEL,
    name="auto_fix_agent",
    description="レビュー指摘を元にコード差分を自動修正する",
    instruction="""
    あなたはコード修正専用のAIです。
    提供された元のコード差分とレビュー指摘を受け取り、
    指摘を反映した修正済みのコード差分を返してください。
    出力は必ずJSONで、以下の形式のみを返してください。
    {
      "fixed_code_diff": "修正済みのコード差分"
    }
    他のテキストは一切不要です。
    """,
    output_schema=AutoFixResultSchema,
)

# コード修正後の差分を更新するためのイベントを生成する関数
def update_code_diff_after_fix(node_input: AutoFixResultSchema, ctx: Context):
    yield Event(
        message=node_message(
            "update_code_diff_after_fix",
            "auto_fix_agent の出力を state['code_diff'] に反映しました。修正後のコード差分を review_agent に渡します。\n\n"
            f"修正済みコード差分:\n{node_input.fixed_code_diff}"
        ),
        state={
            "code_diff": node_input.fixed_code_diff,
            "current_node": "update_code_diff_after_fix",
        },
    )

# 人間のPMによる承認作業
def request_pm_approval(ctx: Context):
    review_summary = ctx.state["review_result"].review_summary
    findings = ctx.state["review_result"].findings
    code_to_approve = ctx.state.get("code_to_approve", ctx.state.get("code_diff", ""))

    yield RequestInput(
        message=node_message(
            "request_pm_approval",
            (
                "以下のレビュー結果とコードを確認し、approve または reject を返してください。\n\n"
                f"レビュー要約: {review_summary}\n"
                f"指摘内容: {findings}\n\n"
                "承認対象コード:\n"
                f"{code_to_approve}\n\n"
                "回答例:\n"
                "- approve\n"
                "- reject: この箇所を修正してください..."
            )
        )
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

def evaluate_review_result(node_input: ReviewResultSchema, ctx: Context):
    """【エッジ: AIの合否判定】ノードAが返したJSONを解析して分岐"""
    current_retry = ctx.state.get("retry_count", 0)
    if node_input.is_pass:
        yield Event(
            message=node_message(
                "evaluate_review_result",
                f"レビューを通過しました。summary: {node_input.review_summary}\nレビュー内容: {node_input.findings}"
                ),
            state={
                "review_result": node_input.model_dump(),
                "retry_count": current_retry,
                "code_to_approve": ctx.state.get("code_diff"),
                "current_node": "evaluate_review_result",
            },
            route="pm_approval_route"
            )
    else:
        current_retry += 1
        if current_retry > ctx.state.get("max_retries", 3):
            yield Event(
                message=node_message(
                    "evaluate_review_result",
                    f"""PMへエスカレーションします。PMと対応方法をすり合わせてください。summary: {node_input.review_summary}\nレビュー内容: {node_input.findings}"""
                ),
                state={
                    "review_result": node_input.model_dump(),
                    "retry_count": current_retry,
                    "current_node": "evaluate_review_result",
                    },
                route="sos_route"
            )
        else:
            yield Event(
                message=node_message(
                    "evaluate_review_result",
                    f"修正が必要です。summary: {node_input.review_summary}\nレビュー内容: {node_input.findings}\nレビュー対象コード: {ctx.state.get('code_diff')}"
                ),
                state={
                    "review_result": node_input.model_dump(),
                    "retry_count": current_retry,
                    "current_node": "evaluate_review_result",
                },
                route="auto_fix_route"
            )

def evaluate_pm_human_decision(node_input: PMDecisionSchema, ctx: Context):
    """【エッジ: PMの承認判定】ノードCが返したJSONを解析して分岐"""
    if node_input.is_approved:
        yield Event(
            message=node_message(
                "evaluate_pm_human_decision",
                "PM が approve しました。ワークフローを終了します。"
            ),
            state={
                "pm_review_result": node_input.model_dump(),
                "current_node": "evaluate_pm_human_decision",
            },
            route="pm_approval_route"
        )
        return  # 承認なら終了
    else:
        yield Event(
            message=node_message(
                "evaluate_pm_human_decision",
                f"PMから差し戻しがありました。\nコメント: {node_input.pm_comments}\nレビュー対象コード: {ctx.state.get('code_to_approve', ctx.state.get('code_diff'))}"
            ),
            state={
                "retry_count": 0,
                "pm_review_result": node_input.model_dump(),
                "code_diff": ctx.state.get("code_to_approve", ctx.state.get("code_diff")),
                "current_node": "evaluate_pm_human_decision",
            },
            route="auto_fix_route"
        )

# ==========================================
# 4. 静的ワークフロー（Graph）の定義
# ==========================================
pr_review_pipeline = Workflow(
    name="advanced_pr_pipeline",
    edges=[
        # AIレビュールート
        ("START", review_agent, evaluate_review_result),
        # AIレビューの結果に基づいた分岐(OK：PM承認へ、NG：差し戻し or SOS)
        (
            evaluate_review_result,
            {
                "pm_approval_route": request_pm_approval,
                "auto_fix_route": auto_fix_agent,
                "sos_route": slack_agent,
            },
        ),
        (request_pm_approval, evaluate_pm_human_decision),
        (evaluate_pm_human_decision, {"auto_fix_route": auto_fix_agent}),
        (auto_fix_agent, update_code_diff_after_fix, review_agent),
    ]
)

# ==========================================
# 5. FastAPI エンドポイント
# ==========================================
class ReviewRequest(BaseModel):
    # GitHub Pull Request ID
    pr_id: str
    # コード差分
    code_diff: str
    # レビューの最大リトライ回数
    max_retries: int = 3

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
                    "retry_count": 0,
                    "pr_id": request.pr_id,
                    "code_diff": request.code_diff,
                }
            )
        except Exception:
            session = await session_service.get_session(
                session_id=session_id,
                user_id=user_id,
                app_name=app_name,
            )
        
        prompt_text = (
            f"下記のPR {request.pr_id} のコード差分をレビューしてください。\n"
            "結果は必ずJSONで返してください。\n"
            "出力項目: is_pass, review_summary, findings\n"
            f"{request.code_diff}"
        )
        new_message = Content(
            role="user", 
            parts=[Part.from_text(text=prompt_text)]
        )
        
        print("[Workflow] 完全自律型ワークフローを非同期実行します...")

        last_node = None
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message,
        ):
            text = ""

            # テキストが含まれるイベントだけを安全に処理
            if event.message and getattr(event.message, "parts", None):
                for part in event.message.parts:
                    part_text = getattr(part, "text", None)
                    if part_text is not None:
                        text = part_text.strip()
                        break

            if text:
                last_node = text.splitlines()[0] if text.startswith("[NODE]") else last_node

            # 1. これが「最終回答」のイベントかどうかをチェック
            if event.is_final_response():
                print(f"[LOG] 途中ノードの最終応答を受信: {last_node}")
        
        latest_session = await session_service.get_session(
            session_id=session_id,
            user_id=user_id,
            app_name=app_name,
        )

        # 最終的な回答（構造化）を返却
        return ReviewResponseSchema(
            status="success",
            session_id=session_id,
            pr_id=request.pr_id,
            current_retry_count=latest_session.state.get("retry_count"),
            review={
                "is_ai_review_passed": latest_session.state.get("review_result", {}).get("is_pass"),
                "ai_review_summary": latest_session.state.get("review_result", {}).get("review_summary"),
                "ai_review_findings": latest_session.state.get("review_result", {}).get("findings"),
                "pm_review_result": latest_session.state.get("pm_review_result", {}).get("is_approved"),
                "pm_comments": latest_session.state.get("pm_review_result", {}).get("pm_comments"),
                "final_code_diff": latest_session.state.get("code_to_approve", latest_session.state.get("code_diff")),
                "current_node": latest_session.state.get("current_node"),
            },
        )
        
    except Exception as e:
        print(f"[Workflow] エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(api, host="0.0.0.0", port=port)
