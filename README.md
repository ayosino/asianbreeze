# Asian Breeze Blog Tools

Debaser Magazineの最新音楽記事をスクレイピングして、はてなブログ用の紹介記事パーツをGemini APIを使って自動生成し、さらにはてなブログへ直接自動投稿できるコマンドラインツールです。

## 主な機能
- **最新記事の自動取得**: RSSフィードまたはHTMLスクレイピングによるデベイサーマガジンの最新音楽記事の自動収集。
- **インテリジェント生成**:
  - 紹介対象アーティストの「ジャンル」「経歴・作風」の作成。
  - 「元記事が公開された趣旨」の要約（約150文字）。
  - 日本の読者の関心を惹くキャッチーな「ブログ記事のタイトル」の自動生成。
- **YouTube動画の自動埋め込み**:
  - アーティストのおすすめMVをYouTubeから自動で検索。
  - 「最新動画」と「最も再生回数の多い動画」をそれぞれ選別し、はてなブログ埋め込み用タグ（`[https://...:embed]`）を生成。
- **はてなブログへの自動投稿**: メール投稿用APIアドレスへのメール送信による記事の全自動投稿（Markdown形式）。

---

## セットアップ

### 依存関係のインストール
```bash
pip install beautifulsoup4 google-genai
```

### 環境変数の設定
Gemini APIキー、およびはてなブログ投稿メール送信用SMTPサーバーの認証情報を環境変数に設定してください。

```bash
# Gemini APIキー
export GEMINI_API_KEY="your_gemini_api_key"

# 自動投稿用SMTP設定 (例: Gmailのアプリパスワードを使用する場合)
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="your_gmail_address@gmail.com"
export SMTP_PASSWORD="your_gmail_app_password"
```

*※ Gmailで送信する場合は、事前にGoogleアカウントの設定から「2段階認証プロセス」を有効化し、「アプリパスワード」を発行して `SMTP_PASSWORD` に指定する必要があります。*

---

## 使い方

### 1. 記事パーツの生成（プレビュー）
最新の記事を取得し、はてなブログ用の記事テキストをコンソールに表示します。
```bash
python3 debaser_blog_generator.py
```

### 2. はてなブログへの自動投稿の実行
`--publish` フラグを追加すると、自動で記事を作成し、はてなブログの指定のメール投稿アドレス（APIアドレス）にメール送信（投稿）を行います。
```bash
python3 debaser_blog_generator.py --publish --publish-email "saxvecja0a@f.hatena.ne.jp"
```
*(※ `--publish-email` を省略した場合も、デフォルトで `saxvecja0a@f.hatena.ne.jp` に送信されます)*

### その他のオプション
- `--category`: 記事のカテゴリ（`music`, `art`, `onscreen`, `culturecommunity`, `all`）を指定します（デフォルトは `music`）。
- `--format`: 出力形式（`text` または `json`）を指定します。
- `--output`: 生成結果をテキストファイルまたはJSONファイルとして保存します。
- `--model`: 使用するGeminiモデル名（デフォルト: `gemini-2.5-flash`）。
