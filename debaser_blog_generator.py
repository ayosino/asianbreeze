#!/usr/bin/env python3
"""
Debaser Magazine Blog Post Generator for Hatena Blog
最新の音楽記事からタイトルとアーティスト名を抽出し、はてなブログ用の紹介記事パーツを自動生成するスクリプト。
"""

import os
import sys
import argparse
import urllib.request
import xml.etree.ElementTree as ET
import json
import re
from typing import Dict, Any

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# Google GenAI SDK サポート (新旧両対応)
try:
    from google import genai
    from google.genai import types
    HAS_NEW_SDK = True
except ImportError:
    try:
        import google.generativeai as genai_legacy
        HAS_NEW_SDK = False
    except ImportError:
        HAS_NEW_SDK = None

# コンソール色出力定義
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_status(message: str, level: str = "info"):
    if level == "info":
        print(f"{Colors.BLUE}[*] {message}{Colors.ENDC}")
    elif level == "success":
        print(f"{Colors.GREEN}[+] {message}{Colors.ENDC}")
    elif level == "warning":
        print(f"{Colors.WARNING}[!] {message}{Colors.ENDC}")
    elif level == "error":
        print(f"{Colors.FAIL}[-] {message}{Colors.ENDC}")


def check_dependencies():
    """依存ライブラリのチェック"""
    missing_deps = []
    if not HAS_BS4:
        missing_deps.append("beautifulsoup4")
    if HAS_NEW_SDK is None:
        missing_deps.append("google-genai")
        
    if missing_deps:
        print_status("スクリプトの実行に必要なライブラリが不足しています。", "error")
        print("以下のコマンドを実行してインストールしてください:")
        print(f"  pip install {' '.join(missing_deps)}")
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    """コマンドライン引数のパース"""
    parser = argparse.ArgumentParser(
        description="Debaser Magazineの最新記事からはてなブログ用パーツを自動生成するスクリプト"
    )
    parser.add_argument(
        "--category",
        choices=["music", "art", "onscreen", "culturecommunity", "all"],
        default="music",
        help="対象にする記事カテゴリ (デフォルト: music)"
    )
    parser.add_argument(
        "--api-key",
        help="Gemini APIキー (指定しない場合は環境変数 GEMINI_API_KEY を使用)"
    )
    parser.add_argument(
        "--model",
        help="使用するGeminiモデル名 (デフォルト: google-genai使用時は gemini-2.5-flash, 旧SDK時は gemini-1.5-flash)"
    )
    parser.add_argument(
        "--output",
        help="生成結果を保存するファイルパス (例: post.txt または post.json)"
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="出力フォーマット (デフォルト: text)"
    )
    return parser.parse_args()


def rule_based_artist_extraction(title: str) -> str:
    """Gemini API呼び出しが失敗した際などのルールベースのアーティスト名抽出フォールバック"""
    title = title.strip(' "“’‘”')
    
    # 1. "Artist on structure, freedom..." パターン
    if " on " in title:
        parts = title.split(" on ")
        return parts[0].strip()
    
    # 2. "Title" - Artist's... パターン
    if " - " in title:
        parts = title.split(" - ")
        candidate = parts[1].strip()
        # 所有格（'s）の削除
        candidate = re.sub(r"['’]s\b.*", "", candidate, flags=re.IGNORECASE)
        return candidate
    
    # 3. Artist: Title または Title: Artist on... パターン
    if ":" in title:
        parts = title.split(":")
        if " on " in parts[1]:
            subparts = parts[1].split(" on ")
            return subparts[0].strip()
        if len(parts[0]) < 25:
            return parts[0].strip()
        return parts[1].strip()
        
    return "Unknown"


def fetch_latest_article(category: str) -> Dict[str, str]:
    """最新記事の取得 (RSSフィードを優先し、失敗時はHTMLスクレイピングを行う)"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    }

    # 1. RSSフィードでの取得を試行
    if category != "all":
        feed_url = f"https://debasermagazine.com/{category}?format=rss"
        print_status(f"RSSフィードから最新記事を取得中: {feed_url} ...", "info")
        try:
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                rss_data = response.read()
            
            root = ET.fromstring(rss_data)
            items = root.findall('.//item')
            if items:
                latest_item = items[0]
                title = latest_item.find('title').text.strip()
                link = latest_item.find('link').text.strip()
                
                description_el = latest_item.find('description')
                description = description_el.text.strip() if description_el is not None else ""
                
                encoded_el = latest_item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
                content_html = encoded_el.text if encoded_el is not None else ""
                
                if content_html:
                    soup = BeautifulSoup(content_html, 'html.parser')
                    content_text = soup.get_text(separator='\n').strip()
                else:
                    content_text = description
                    
                return {
                    'title': title,
                    'link': link,
                    'description': description,
                    'content_text': content_text,
                    'source': 'RSS Feed'
                }
        except Exception as e:
            print_status(f"RSSフィードの取得/解析に失敗しました: {e}。HTMLスクレイピングを試みます...", "warning")

    # 2. HTMLスクレイピングでの取得（RSS失敗時、または category='all' の場合）
    site_url = "https://debasermagazine.com/"
    print_status(f"ホームページからHTMLをスクレイピング中: {site_url} ...", "info")
    try:
        req = urllib.request.Request(site_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html_data = response.read()
            
        soup = BeautifulSoup(html_data, 'html.parser')
        items = []
        for item in soup.find_all(class_='summary-item'):
            title_el = item.find(class_='summary-title-link')
            if not title_el:
                continue
            title = title_el.text.strip()
            link = title_el.get('href', '').strip()
            if not link.startswith('http'):
                link = "https://debasermagazine.com" + link
                
            date_el = item.find('time')
            date_obj = None
            if date_el:
                datetime_attr = date_el.get('datetime', '')
                if datetime_attr:
                    try:
                        from datetime import datetime
                        date_obj = datetime.strptime(datetime_attr, '%Y-%m-%d')
                    except ValueError:
                        pass
            
            excerpt_el = item.find(class_='summary-excerpt')
            excerpt = excerpt_el.text.strip() if excerpt_el else ""
            
            items.append({
                'title': title,
                'link': link,
                'date_obj': date_obj,
                'excerpt': excerpt
            })
            
        # カテゴリフィルタリング
        if category != "all":
            path_filter = f"/{category}/"
            filtered_items = [i for i in items if path_filter in i['link']]
            target_items = filtered_items if filtered_items else items
        else:
            target_items = items
            
        if not target_items:
            raise ValueError(f"カテゴリ '{category}' に該当する記事が見つかりませんでした。")
            
        # 日付でソートして最新のものを取得
        sorted_items = sorted(
            [i for i in target_items if i['date_obj']],
            key=lambda x: x['date_obj'],
            reverse=True
        )
        latest = sorted_items[0] if sorted_items else target_items[0]
        
        # 記事詳細ページから本文のテキストを抽出
        article_text = ""
        try:
            print_status(f"記事詳細ページから本文を取得中: {latest['link']} ...", "info")
            req_article = urllib.request.Request(latest['link'], headers=headers)
            with urllib.request.urlopen(req_article, timeout=10) as resp_article:
                article_html = resp_article.read()
            article_soup = BeautifulSoup(article_html, 'html.parser')
            content_el = article_soup.find(class_='blog-item-content') or article_soup.find(class_='entry-content')
            if content_el:
                article_text = content_el.get_text(separator='\n').strip()
            else:
                article_text = latest['excerpt']
        except Exception as e:
            print_status(f"詳細ページの取得に失敗したため、抜粋を使用します: {e}", "warning")
            article_text = latest['excerpt']
            
        return {
            'title': latest['title'],
            'link': latest['link'],
            'description': latest['excerpt'],
            'content_text': article_text,
            'source': 'HTML Scraping'
        }
    except Exception as e:
        print_status(f"最新記事の取得に失敗しました: {e}", "error")
        sys.exit(1)


def generate_content_with_gemini(
    api_key: str,
    model_name: str,
    title: str,
    link: str,
    description: str,
    content_text: str,
    output_format: str
) -> Dict[str, Any]:
    """Gemini APIを使用してアーティスト名抽出とはてなブログ記事パーツ生成を行う"""
    
    # モデルのデフォルト設定
    if not model_name:
        model_name = 'gemini-2.5-flash' if HAS_NEW_SDK else 'gemini-1.5-flash'

    print_status(f"Gemini APIを呼び出し中 (モデル: {model_name}) ...", "info")

    # 1. 新しい google-genai SDK を使用する場合
    if HAS_NEW_SDK:
        client = genai.Client(api_key=api_key)
        
        # アーティスト名の抽出
        artist_prompt = (
            f"以下は海外の音楽メディア記事のタイトルと要約です。この記事で紹介されている中心的な音楽アーティストまたはバンド名を抽出してください。\n"
            f"回答はアーティスト/バンド名のみとし、余計な説明や引用符、句読点は一切含めないでください。\n"
            f"もし特定のアーティストではなくイベントやコンピレーションなどの場合は、主役となるアーティスト名、または最も関連するアーティスト名を1つだけ抽出してください。判断が難しい場合は 'Unknown' と返してください。\n\n"
            f"タイトル: {title}\n"
            f"概要: {description}\n"
        )
        try:
            resp_artist = client.models.generate_content(
                model=model_name,
                contents=artist_prompt
            )
            artist_name = resp_artist.text.strip()
        except Exception as e:
            print_status(f"Geminiによるアーティスト名抽出に失敗しました: {e}。ルールベースで抽出します。", "warning")
            artist_name = rule_based_artist_extraction(title)
            
        if not artist_name or artist_name.lower() == 'unknown':
            artist_name = rule_based_artist_extraction(title)
            
        # はてなブログ記事パーツの生成
        # Pydanticを使用した構造化出力を定義 (JSONフォーマット時、またはパースの安定性のために使用)
        from pydantic import BaseModel, Field
        from typing import List

        class HatenaBlogParts(BaseModel):
            genre: List[str] = Field(description="アーティストのジャンル（シューゲイザー、ドリームポップ、オルタナティブロックなど、最大3つ）")
            bio_style: str = Field(description="経歴・作風（日本の音楽ファンが興味を持つような文脈を交え、300文字程度で簡潔かつ魅力的に解説。口調は「です」「ます」）")
            youtube_query: str = Field(description="YouTube検索クエリ（「アーティスト名 曲名 MV」の形式で、最も公式ミュージックビデオがヒットしやすい英語または現地語のクエリ）")

        user_prompt = (
            f"# Context\n"
            f"あなたはアジアのインディーズ音楽（K-Indie、台湾インディー、タイポップスなど）に精通したカルチャーライターです。\n"
            f"渡された海外メディアの記事情報を元に、日本のリスナー向けにアーティストを紹介するブログ記事のパーツを生成してください。\n\n"
            f"# Input Data\n"
            f"- 元記事タイトル: {title}\n"
            f"- アーティスト名: {artist_name}\n"
            f"- 元記事の本文（参考情報）: \n{content_text[:3000]}\n\n"
            f"# Constraints\n"
            f"- 事実が不明瞭な場合は、嘘を書かずに一般的な音楽的特徴から推測される作風として記述してください。\n"
            f"- 口調は「〜です」「〜ます」の、知的で洗練されたトーンに統一してください。\n"
        )

        try:
            # 構造化出力で生成
            resp_blog = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=HatenaBlogParts,
                    temperature=0.3
                )
            )
            result_data = json.loads(resp_blog.text)
            
            # 指定形式のテキスト表示用フォーマット
            genres_str = "、".join(result_data['genre'])
            text_format = (
                f"1. ジャンル: {genres_str}\n"
                f"2. 経歴・作風: {result_data['bio_style']}\n"
                f"3. YouTube検索クエリ: {result_data['youtube_query']}"
            )
            
            return {
                "title": title,
                "link": link,
                "artist_name": artist_name,
                "genre": result_data['genre'],
                "bio_style": result_data['bio_style'],
                "youtube_query": result_data['youtube_query'],
                "text_output": text_format
            }
        except Exception as e:
            print_status(f"構造化データの生成に失敗しました: {e}。通常のテキスト生成に切り替えます。", "warning")
            
    # 2. レガシーな google-generativeai SDK または新SDKでのテキストフォールバック
    if not HAS_NEW_SDK:
        genai_legacy.configure(api_key=api_key)
        model = genai_legacy.GenerativeModel(model_name)
        
        # アーティスト名の抽出
        artist_prompt = (
            f"Extract the primary music artist or band name from this article title: '{title}'.\n"
            f"Return ONLY the artist/band name. No explanation, no quotes."
        )
        try:
            resp_artist = model.generate_content(artist_prompt)
            artist_name = resp_artist.text.strip()
        except Exception:
            artist_name = rule_based_artist_extraction(title)
    
    # テキストプロンプトでのブログ生成
    raw_prompt = (
        f"# Context\n"
        f"あなたはアジアのインディーズ音楽（K-Indie、台湾インディー、タイポップスなど）に精通したカルチャーライターです。\n"
        f"渡された海外メディアの記事情報を元に、日本のリスナー向けにアーティストを紹介するブログ記事のパーツを生成してください。\n\n"
        f"# Input Data\n"
        f"- 元記事タイトル: {title}\n"
        f"- アーティスト名: {artist_name}\n"
        f"- 元記事本文（参考情報）: \n{content_text[:3000]}\n\n"
        f"# Output Format (指定形式)\n"
        f"1. ジャンル: (例: シューゲイザー、ドリームポップ、オルタナティブロックなど、最大3つ)\n"
        f"2. 経歴・作風: (日本の音楽ファンが興味を持つような文脈を交え、300文字程度で簡潔かつ魅力的に解説)\n"
        f"3. YouTube検索クエリ: (「アーティスト名 曲名 MV」の形式で、最も公式ミュージックビデオがヒットしやすい英語または現地語のクエリ)\n\n"
        f"# Constraints\n"
        f"- 事実が不明瞭な場合は、嘘を書かずに一般的な音楽的特徴から推測される作風として記述してください。\n"
        f"- 口調は「〜です」「〜ます」の、知的で洗練されたトーンに統一してください。\n"
    )
    
    if HAS_NEW_SDK:
        client = genai.Client(api_key=api_key)
        resp_blog = client.models.generate_content(model=model_name, contents=raw_prompt)
    else:
        resp_blog = model.generate_content(raw_prompt)
        
    text_output = resp_blog.text.strip()
    
    # テキスト出力からJSONを簡易パース
    genres = []
    bio_style = ""
    yt_query = ""
    
    try:
        # 正規表現でテキストから各項目を抽出
        genre_match = re.search(r"1\.\s*ジャンル:\s*(.*)", text_output)
        bio_match = re.search(r"2\.\s*経歴・作風:\s*(.*)", text_output)
        yt_match = re.search(r"3\.\s*YouTube検索クエリ:\s*(.*)", text_output)
        
        if genre_match:
            genres = [g.strip() for g in re.split(r"[、,]", genre_match.group(1))]
        if bio_match:
            bio_style = bio_match.group(1).strip()
        if yt_match:
            yt_query = yt_match.group(1).strip()
    except Exception:
        pass
        
    return {
        "title": title,
        "link": link,
        "artist_name": artist_name,
        "genre": genres,
        "bio_style": bio_style,
        "youtube_query": yt_query,
        "text_output": text_output
    }


def main():
    # 依存ライブラリの確認
    check_dependencies()
    
    # 引数の取得
    args = parse_args()
    
    # APIキーの取得
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print_status("GEMINI_API_KEY が設定されていません。", "error")
        print("APIキーを設定してからスクリプトを実行してください。")
        print("設定方法:")
        print("  export GEMINI_API_KEY=\"あなたのAPIキー\"")
        print("または引数で指定:")
        print("  python debaser_blog_generator.py --api-key \"あなたのAPIキー\"")
        sys.exit(1)
        
    # 最新記事の取得
    article = fetch_latest_article(args.category)
    
    print("\n" + "="*50)
    print_status("取得した記事情報", "success")
    print(f"元記事タイトル : {article['title']}")
    print(f"元記事リンク     : {article['link']}")
    print(f"情報取得元     : {article['source']}")
    print("="*50 + "\n")
    
    # Geminiを使用したコンテンツの生成
    try:
        blog_parts = generate_content_with_gemini(
            api_key=api_key,
            model_name=args.model,
            title=article['title'],
            link=article['link'],
            description=article['description'],
            content_text=article['content_text'],
            output_format=args.format
        )
    except Exception as e:
        print_status(f"Gemini APIによるブログパーツの生成中にエラーが発生しました: {e}", "error")
        sys.exit(1)

    print("\n" + "="*50)
    print_status("生成されたはてなブログ用パーツ", "success")
    print(f"元記事タイトル : {blog_parts['title']}")
    print(f"アーティスト名 : {blog_parts['artist_name']}")
    print("-"*50)
    
    # フォーマットに応じた出力
    if args.format == "text":
        output_content = (
            f"■ 元記事タイトル: {blog_parts['title']}\n"
            f"■ 元記事URL: {blog_parts['link']}\n"
            f"■ アーティスト名: {blog_parts['artist_name']}\n\n"
            f"{blog_parts['text_output']}"
        )
        print(output_content)
    else:
        # JSONフォーマット
        json_data = {
            "source_article": {
                "title": blog_parts["title"],
                "url": blog_parts["link"]
            },
            "artist_name": blog_parts["artist_name"],
            "genre": blog_parts["genre"],
            "bio_style": blog_parts["bio_style"],
            "youtube_query": blog_parts["youtube_query"]
        }
        output_content = json.dumps(json_data, indent=2, ensure_ascii=False)
        print(output_content)
    print("="*50 + "\n")
    
    # ファイルへの書き出し
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_content)
            print_status(f"結果をファイルに保存しました: {args.output}", "success")
        except Exception as e:
            print_status(f"ファイル保存中にエラーが発生しました: {e}", "error")


if __name__ == "__main__":
    main()
