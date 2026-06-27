# 1. 軽量なPythonベースイメージを使用
FROM python:3.11-slim

# 2. 処理を高速化するための環境変数の設定（uv用のキャッシュ無効化など）
ENV UV_PROJECT_ENVIRONMENT=/usr/local
ENV UV_COMPILE_BYTECODE=1

# 3. 超高速パッケージマネージャー「uv」をインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 4. 作業ディレクトリを設定
WORKDIR /app

# 5. 【変更箇所】外部のrequirements.txtをコピーして、uvで超高速一括インストール
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# 6. アプリケーションのコードをコピー
COPY main.py .

# 7. アプリケーションを起動
CMD ["python", "main.py"]
