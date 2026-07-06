#!/usr/bin/env python3
"""
Debaser Magazine Blog Post Generator for Hatena Blog
最新の音楽記事からタイトルとアーティスト名を抽出し、はてなブログ用の紹介記事パーツを自動生成して AtomPub API で公開するスクリプト。
"""

import os
import sys
import argparse
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import re
import base64
from typing import Dict, Any, List

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
        description="Debaser Magazineの最新記事からはてなブログ用パーツを自動生成・API投稿するスクリプト"
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
    parser.add_argument(
        "--publish",
        action="store_true",
        help="はてなブログへの自動投稿（API公開）を実行する"
    )
    parser.add_argument(
        "--hatena-id",
        default=os.environ.get("HATENA_ID", "ayosino"),
        help="はてなID (デフォルト: ayosino)"
    )
    parser.add_argument(
        "--hatena-blog-id",
        default=os.environ.get("HATENA_BLOG_ID", "ayosino.hatenablog.com"),
        help="はてなブログID / ドメイン (デフォルト: ayosino.hatenablog.com)"
    )
    parser.add_argument(
        "--hatena-api-key",
        default=os.environ.get("HATENA_API_KEY", "saxvecja0a"),
        help="はてなブログAPIキー/APIパスコード (デフォルト: saxvecja0a)"
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        default=True,
        help="下書きとして投稿する (デフォルト: True)"
    )
    parser.add_argument(
        "--no-draft",
        action="store_false",
        dest="draft",
        help="下書きではなく直接公開する"
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


def get_youtube_videos(query: str, sort_param: str = None) -> List[Dict[str, str]]:
    """YouTubeで検索を行い、上位の動画リストを取得する"""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    if sort_param:
        url += f"&sp={sort_param}"
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
        
        match = re.search(r'var ytInitialData\s*=\s*({.*?});', html)
        if not match:
            match = re.search(r'window\["ytInitialData"\]\s*=\s*({.*?});', html)
            
        if match:
            data = json.loads(match.group(1))
            videos = []
            
            def find_videos(obj):
                if isinstance(obj, dict):
                    if 'videoRenderer' in obj:
                        vr = obj['videoRenderer']
                        video_id = vr.get('videoId')
                        title = vr.get('title', {}).get('runs', [{}])[0].get('text', '')
                        view_count = vr.get('viewCountText', {}).get('simpleText', '')
                        published_time = vr.get('publishedTimeText', {}).get('simpleText', '')
                        if video_id:
                            videos.append({
                                'id': video_id,
                                'title': title,
                                'views': view_count,
                                'published': published_time,
                                'url': f"https://www.youtube.com/watch?v={video_id}",
                                'hatena_embed': f"[https://www.youtube.com/watch?v={video_id}:embed]"
                            })
                    for val in obj.values():
                        find_videos(val)
                elif isinstance(obj, list):
                    for item in obj:
                        find_videos(item)
            
            find_videos(data)
            return videos
    except Exception as e:
        print_status(f"YouTube検索中にエラーが発生しました: {e}", "warning")
    return []


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
        from pydantic import BaseModel, Field

        class HatenaBlogParts(BaseModel):
            blog_title: str = Field(description="はてなブログ記事のキャッチーなタイトル（日本語、50文字以内、例: 【K-Indie】Kuang Programの深淵なるノイズロックの世界）")
            genre: List[str] = Field(description="アーティストのジャンル（シューゲイザー、ドリームポップ、オルタナティブロックなど、最大3つ）")
            bio_style: str = Field(description="経歴・作風（日本の音楽ファンが興味を持つような文脈を交え、300文字程度で簡潔かつ魅力的に解説。口調は「です」「ます」）")
            youtube_query: str = Field(description="YouTube検索クエリ（「アーティスト名 曲名 MV」の形式で、最も公式ミュージックビデオがヒットしやすい英語または現地語のクエリ）")
            article_purpose: str = Field(description="元記事の趣旨（なぜこの記事が書かれたのか、どのような文脈・意図（例：新譜のリリース、周年記念、シーンの現状紹介など）で公開されたかを100文字〜150文字程度で簡潔に説明。口調は「です」「ます」）")

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
                f"ブログタイトル: {result_data['blog_title']}\n"
                f"1. ジャンル: {genres_str}\n"
                f"2. 経歴・作風: {result_data['bio_style']}\n"
                f"3. YouTube検索クエリ: {result_data['youtube_query']}\n"
                f"4. 元記事の趣旨: {result_data['article_purpose']}"
            )
            
            return {
                "title": title,
                "link": link,
                "artist_name": artist_name,
                "blog_title": result_data['blog_title'],
                "genre": result_data['genre'],
                "bio_style": result_data['bio_style'],
                "youtube_query": result_data['youtube_query'],
                "article_purpose": result_data['article_purpose'],
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
        f"ブログタイトル: (日本の読者の興味を引くようなキャッチーな日本語のタイトル、50文字以内)\n"
        f"1. ジャンル: (例: シューゲイザー、ドリームポップ、オルタナティブロックなど、最大3つ)\n"
        f"2. 経歴・作風: (日本の音楽ファンが興味を持つような文脈を交え、300文字程度で簡潔かつ魅力的に解説)\n"
        f"3. YouTube検索クエリ: (「アーティスト名 曲名 MV」の形式で、最も公式ミュージックビデオがヒットしやすい英語または現地語のクエリ)\n"
        f"4. 元記事の趣旨: (なぜこの記事が書かれたのか、どのような背景や意図（例：新譜インタビュー、来日記念、シーン紹介など）で公開されたかを100文字〜150文字程度で簡潔に説明)\n\n"
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
    blog_title = f"【K-Indie】{artist_name}の最新ニュース"
    genres = []
    bio_style = ""
    yt_query = ""
    article_purpose = ""
    
    try:
        title_match = re.search(r"ブログタイトル:\s*(.*)", text_output)
        genre_match = re.search(r"1\.\s*ジャンル:\s*(.*)", text_output)
        bio_match = re.search(r"2\.\s*経歴・作風:\s*(.*)", text_output)
        yt_match = re.search(r"3\.\s*YouTube検索クエリ:\s*(.*)", text_output)
        purpose_match = re.search(r"4\.\s*元記事の趣旨:\s*(.*)", text_output)
        
        if title_match:
            blog_title = title_match.group(1).strip()
        if genre_match:
            genres = [g.strip() for g in re.split(r"[、,]", genre_match.group(1))]
        if bio_match:
            bio_style = bio_match.group(1).strip()
        if yt_match:
            yt_query = yt_match.group(1).strip()
        if purpose_match:
            article_purpose = purpose_match.group(1).strip()
    except Exception:
        pass
        
    return {
        "title": title,
        "link": link,
        "artist_name": artist_name,
        "blog_title": blog_title,
        "genre": genres,
        "bio_style": bio_style,
        "youtube_query": yt_query,
        "article_purpose": article_purpose,
        "text_output": text_output
    }


def assemble_markdown_post(
    blog_parts: Dict[str, Any],
    latest_video: Dict[str, Any],
    most_viewed_video: Dict[str, Any]
) -> str:
    """はてなブログ用に各パーツをアセンブルして綺麗なMarkdown記事を作成する"""
    genres_str = "、".join(blog_parts.get("genre", []))
    
    body = f"""海外音楽メディア「Debaser Magazine」の最新記事から、注目のインディーズアーティストをご紹介します。

### 元記事情報
* **紹介元の記事**: [{blog_parts['title']}]({blog_parts['link']})
* **メディア**: Debaser Magazine

---

### はじめに（元記事の紹介趣旨）
{blog_parts['article_purpose']}

---

### アーティスト紹介：**{blog_parts['artist_name']}**

* **ジャンル**: {genres_str}
* **経歴・作風**:
{blog_parts['bio_style']}

---

### おすすめ動画・MV

"""
    if latest_video:
        body += f"""#### 最新の動画
{latest_video.get('hatena_embed')}
* **動画タイトル**: {latest_video.get('title')}
* **公開日 / 再生回数**: {latest_video.get('published')} / {latest_video.get('views')}

"""
    if most_viewed_video:
        body += f"""#### 最も再生回数の多い動画
{most_viewed_video.get('hatena_embed')}
* **動画タイトル**: {most_viewed_video.get('title')}
* **公開日 / 再生回数**: {most_viewed_video.get('published')} / {most_viewed_video.get('views')}

"""
    body += "\n*(※この記事はDebaser Magazineの公開記事情報を元に、自動生成ツールによって作成されました。)*"
    return body


def publish_to_hatena_blog_api(
    hatena_id: str,
    blog_id: str,
    api_key: str,
    title: str,
    content: str,
    draft: bool = True
) -> bool:
    """はてなブログ AtomPub APIを利用して記事を投稿する"""
    url = f"https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry"
    
    # XMLペイロードの組み立て
    draft_val = "yes" if draft else "no"
    xml_data = f"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:app="http://www.w3.org/2007/app">
  <title>{title}</title>
  <author><name>{hatena_id}</name></author>
  <content type="text/x-markdown"><![CDATA[{content}]]></content>
  <app:control>
    <app:draft>{draft_val}</app:draft>
  </app:control>
</entry>
"""
    
    headers = {
        'Content-Type': 'application/xml; charset=utf-8',
        'User-Agent': 'DebaserBlogGenerator/1.0'
    }
    
    # Basic認証用の資格情報生成
    auth_str = f"{hatena_id}:{api_key}"
    auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    headers['Authorization'] = f"Basic {auth_b64}"
    
    req = urllib.request.Request(
        url,
        data=xml_data.encode('utf-8'),
        headers=headers,
        method='POST'
    )
    
    print_status(f"はてなブログ AtomPub APIに記事を投稿中 (宛先: {url}, 下書き: {draft_val}) ...", "info")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            resp_body = response.read().decode('utf-8')
        
        # 投稿URLをレスポンスから簡易パース
        published_url = ""
        link_match = re.search(r'<link rel="alternate" type="text/html" href="([^"]+)"/>', resp_body)
        if link_match:
            published_url = link_match.group(1)
            
        print_status("はてなブログへのAPI投稿に成功しました！", "success")
        if published_url:
            print_status(f"公開先URL (プレビュー): {published_url}", "success")
        return True
    except Exception as e:
        print_status(f"はてなブログへのAPI投稿中にエラーが発生しました: {e}", "error")
        if hasattr(e, 'read'):
            try:
                error_body = e.read().decode('utf-8')
                print(f"APIエラー詳細: {error_body}")
            except Exception:
                pass
        return False


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
        
    # YouTube検索の実行（生成されたYouTubeクエリを使用）
    yt_query = blog_parts["youtube_query"]
    latest_video = {}
    most_viewed_video = {}
    
    if yt_query:
        print_status(f"YouTubeで最新の動画リストを検索中: '{yt_query}' ...", "info")
        latest_videos = get_youtube_videos(yt_query, "CAI") # 最新アップロード順
        
        print_status(f"YouTubeで最も再生回数の多い動画リストを検索中: '{yt_query}' ...", "info")
        most_viewed_videos = get_youtube_videos(yt_query, "CAM%253D") # 再生回数順
        
        if latest_videos:
            latest_video = latest_videos[0]
            
        if most_viewed_videos:
            # 最新の動画と重複しないものを選択
            latest_id = latest_video.get('id') if latest_video else None
            for video in most_viewed_videos:
                if video.get('id') != latest_id:
                    most_viewed_video = video
                    break
            # もし他に適した動画がない場合は、最初の動画を選択
            if not most_viewed_video and most_viewed_videos:
                most_viewed_video = most_viewed_videos[0]
    
    # YouTube動画の埋め込み部分の組み立て
    youtube_embed_text = ""
    if latest_video or most_viewed_video:
        youtube_embed_text = "■ 実際のYouTube動画埋め込み\n"
        if latest_video:
            youtube_embed_text += (
                f"・最新の動画 (はてなブログ形式):\n"
                f"  {latest_video.get('hatena_embed')}\n"
                f"  (タイトル: {latest_video.get('title')} | 投稿: {latest_video.get('published')} | 再生数: {latest_video.get('views')})\n"
            )
        if most_viewed_video:
            youtube_embed_text += (
                f"・最も再生回数の多い動画 (はてなブログ形式):\n"
                f"  {most_viewed_video.get('hatena_embed')}\n"
                f"  (タイトル: {most_viewed_video.get('title')} | 投稿: {most_viewed_video.get('published')} | 再生数: {most_viewed_video.get('views')})\n"
            )

    # はてなブログへ投稿するMarkdown形式の完全な記事を作成
    complete_blog_post = assemble_markdown_post(blog_parts, latest_video, most_viewed_video)

    print("\n" + "="*50)
    print_status("生成されたはてなブログ用パーツ", "success")
    print(f"ブログ記事タイトル: {blog_parts['blog_title']}")
    print(f"元記事タイトル : {blog_parts['title']}")
    print(f"アーティスト名 : {blog_parts['artist_name']}")
    print("-"*50)
    
    # フォーマットに応じた出力
    if args.format == "text":
        output_content = (
            f"■ ブログ記事タイトル: {blog_parts['blog_title']}\n"
            f"■ 元記事タイトル: {blog_parts['title']}\n"
            f"■ 元記事URL: {blog_parts['link']}\n"
            f"■ アーティスト名: {blog_parts['artist_name']}\n\n"
            f"{blog_parts['text_output']}\n\n"
            f"{youtube_embed_text}"
        )
        print(output_content)
    else:
        # JSONフォーマット
        json_data = {
            "blog_title": blog_parts["blog_title"],
            "source_article": {
                "title": blog_parts["title"],
                "url": blog_parts["link"]
            },
            "artist_name": blog_parts["artist_name"],
            "genre": blog_parts["genre"],
            "bio_style": blog_parts["bio_style"],
            "youtube_query": blog_parts["youtube_query"],
            "article_purpose": blog_parts["article_purpose"],
            "youtube_embeds": {
                "latest": {
                    "title": latest_video.get("title"),
                    "url": latest_video.get("url"),
                    "hatena_embed": latest_video.get("hatena_embed"),
                    "views": latest_video.get("views"),
                    "published": latest_video.get("published")
                } if latest_video else None,
                "most_viewed": {
                    "title": most_viewed_video.get("title"),
                    "url": most_viewed_video.get("url"),
                    "hatena_embed": most_viewed_video.get("hatena_embed"),
                    "views": most_viewed_video.get("views"),
                    "published": most_viewed_video.get("published")
                } if most_viewed_video else None
            },
            "complete_markdown": complete_blog_post
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

    # はてなブログへの自動投稿処理
    if args.publish:
        print_status("はてなブログへの自動投稿（API）を開始します...", "info")
        if not args.hatena_api_key:
            print_status("はてなブログAPIキーが設定されていません。環境変数 HATENA_API_KEY を設定するか、--hatena-api-key オプションを使用してください。", "error")
            sys.exit(1)
            
        publish_to_hatena_blog_api(
            hatena_id=args.hatena_id,
            blog_id=args.hatena_blog_id,
            api_key=args.hatena_api_key,
            title=blog_parts['blog_title'],
            content=complete_blog_post,
            draft=args.draft
        )


if __name__ == "__main__":
    main()
