# Asian Breeze Blog Tools

Debaser Magazineの最新音楽記事をスクレイピングして、はてなブログ用の紹介記事パーツをGemini APIを使って自動生成し、さらにはてなブログへ直接自動投稿（API公開）できるコマンドラインツールです。

## 主な機能
- **最新記事の自動取得**: RSSフィードまたはHTMLスクレイピングによるデベイサーマガジンの最新音楽記事の自動収集。
- **インテリジェント生成**:
  - 紹介対象アーティストの「ジャンル」「経歴・作風」の作成。
  - 「元記事が公開された趣旨」の要約（約150文字）。
  - 日本の読者の関心を惹くキャッチーな「ブログ記事のタイトル」の自動生成。
- **YouTube動画の自動埋め込み**:
  - アーティストのおすすめMVをYouTubeから自動で検索。
  - 「最新動画」と「最も再生回数の多い動画」をそれぞれ選別し、はてなブログ埋め込み用タグ（`[https://...:embed]`）を生成。
- **はてなブログへの自動投稿（API）**: はてなブログ公式の AtomPub API を使用して、Markdown形式の記事を下書き（または本番公開）として自動投稿。

---

## セットアップ

### 依存関係のインストール
```bash
pip install beautifulsoup4 google-genai
```

### 環境変数の設定
Gemini APIキー、およびはてなブログのAPI認証情報を環境変数に設定してください。

```bash
# Gemini APIキー
export GEMINI_API_KEY="your_gemini_api_key"

# はてなブログAPI設定
export HATENA_ID="ayosino"                          # はてなID
export HATENA_BLOG_ID="ayosino.hatenablog.com"      # ブログのドメイン
export HATENA_API_KEY="saxvecja0a"                  # はてなブログAPIキー（APIパスコード）
```

*※ APIキー（APIパスコード）は、はてなブログ管理画面の「設定」>「詳細設定」の下部にある「AtomPub」セクションから取得できます。*

---

## 使い方

### 1. 記事パーツの生成（プレビュー）
最新の記事を取得し、はてなブログ用の記事テキストをコンソールに表示します。
```bash
python3 debaser_blog_generator.py
```

### 2. はてなブログへの自動投稿（API）の実行
`--publish` フラグを追加すると、自動で記事を作成し、はてなブログへ直接API投稿（デフォルトでは「下書き」として投稿）を行います。
```bash
python3 debaser_blog_generator.py --publish
```

#### その他のAPIオプション:
- `--hatena-id`: はてなIDをコマンド引数で指定。
- `--hatena-blog-id`: ブログID（ドメイン）をコマンド引数で指定。
- `--hatena-api-key`: APIキーをコマンド引数で指定（デフォルトは `saxvecja0a`）。
- `--no-draft`: 下書き保存ではなく、直接公開状態で投稿します。

例（下書きではなく直接公開する場合）:
```bash
python3 debaser_blog_generator.py --publish --no-draft
```

### その他のオプション
- `--category`: 記事のカテゴリ（`music`, `art`, `onscreen`, `culturecommunity`, `all`）を指定します（デフォルトは `music`）。
- `--format`: 出力形式（`text` または `json`）を指定します。
- `--output`: 生成結果をテキストファイルまたはJSONファイルとして保存します。
- `--model`: 使用するGeminiモデル名（デフォルト: `gemini-2.5-flash`）。
