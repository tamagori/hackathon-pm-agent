import os
from fastapi import FastAPI
from google.auth import default
import vertexai
from vertexai.generative_models import GenerativeModel

app = FastAPI()

# サーバー起動時に一瞬だけGeminiを動かす最小限のテストロジック
@app.on_event("startup")
def test_gemini_connection():
    print("=== [AI Agent] Gemini API (Vertex AI) の実装を開始します ===")
    try:
        # 1. 明示的にスコープを指定して認証情報を取得
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        credentials, project_id = default(scopes=scopes)
        
        # 2. Vertex AI SDK の初期化 (Cloud Runの環境変数のプロジェクトを自動利用)
        # プロジェクトIDが自動取得できない場合に備え、明示的な指定もカバーします
        current_project = project_id or "ai-agent-hackathon-2026"
        vertexai.init(project=current_project, location="asia-northeast1", credentials=credentials)
        
        # 3. Vertex AI 上の Gemini 2.5 Flash モデルを呼び出し
        model = GenerativeModel("gemini-2.5-flash")
        
        print("[AI Agent] Vertex AI 経由で Gemini に接続中...")
        response = model.generate_content("ハッカソン開発の開始にあたり、1言熱い応援メッセージをください！")
        
        print("\n--- 🤖 Geminiからの返答 ---")
        print(response.text)
        print("----------------------------\n")
        print("[AI Agent] 接続テストに成功しました！キーレス認証が完全開通しました。")
        
    except Exception as e:
        print(f"[AI Agent] 接続テストに失敗しました。理由: {e}")

@app.get("/")
def read_root():
    return {"message": "Hello World! PM Agent base-line is running with Vertex AI ready!"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
