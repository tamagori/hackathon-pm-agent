import os
from fastapi import FastAPI
from google.auth import default
import google.generativeai as genai

app = FastAPI()

# サーバー起動時に一瞬だけGeminiを動かす最小限のテストロジック
@app.on_event("startup")
def test_gemini_connection():
    print("=== [AI Agent] Gemini APIの実装を開始します ===")
    try:
        # 【修正箇所】明示的にcloud-platformスコープを要求し、フィルターを解放します
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        credentials, project_id = default(scopes=scopes) # 引数にscopesを手渡す
        genai.configure(credentials=credentials)
        
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        print("[AI Agent] Geminiに接続中...")
        response = model.generate_content("ハッカソン開発の開始にあたり、1言熱い応援メッセージをください！")
        
        print("\n--- 🤖 Geminiからの返答 ---")
        print(response.text)
        print("----------------------------\n")
        print("[AI Agent] 接続テストに成功しました！")
        
    except Exception as e:
        print(f"[AI Agent] 接続テストに失敗しました。理由: {e}")

@app.get("/")
def read_root():
    return {"message": "Hello World! PM Agent base-line is running with Gemini API ready!"}

if __name__ == "__main__":
    import uvicorn
    # 既存のCloud Run用ポート受付処理をそのまま維持
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
