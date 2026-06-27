import os
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    # 最終的にはここに「PMレビュー＆SOSエージェント」のロジックを組み込みます
    return {"message": "Hello World! PM Agent base-line is running!"}

if __name__ == "__main__":
    import uvicorn
    # Cloud Runは環境変数 PORT で指定されたポートで待受ける必要があります
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
