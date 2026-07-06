# Asian Breeze Blog Tools

Debaser Magazineの最新音楽記事をスクレイピングして、はてなブログ用の紹介記事パーツをGemini APIを使って自動生成するコマンドラインツールです。

## セットアップ

### 依存関係のインストール
```bash
pip install beautifulsoup4 google-genai
```

### APIキーの設定
Gemini APIキーを環境変数に設定してください。
```bash
export GEMINI_API_KEY="your_api_key_here"
```

## 使い方
最新の記事を取得してはてなブログ用パーツを生成します。
```bash
python3 debaser_blog_generator.py
```

### オプション
- `--category`: 記事のカテゴリ（`music`, `art`, `onscreen`, `culturecommunity`, `all`）を指定します（デフォルトは `music`）。
- `--format`: 出力形式（`text` または `json`）を指定します。
- `--output`: 生成結果をテキストファイルとして保存します。

例：
```bash
python3 debaser_blog_generator.py --format json --output result.json
```
