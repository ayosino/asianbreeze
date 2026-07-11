#!/usr/bin/env python3
"""
Debaser Magazine, StreetVoice Blow, What The Duck Blog Post Generator for Hatena Blog
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

# 許可されたジャンル一覧（固定小分類カテゴリ）
ALLOWED_GENRES = [
    "インディーロック", "オルタナティブロック", "シューゲイザー", "ポストパンク", "マスロック", "ノイズポップ",
    "インディーポップ", "ドリームポップ", "シンセポップ", "エレクトロニカ", "シティポップ", "レトロポップ",
    "フォーク", "アコースティック", "シンガーソングライター", "インディフォーク",
    "R&B", "ソウル", "ヒップホップ", "ローファイヒップホップ",
    "ノイズ/インダストリアル", "ノーウェーブ"
]


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
        description="音楽メディア最新記事からはてなブログ用パーツを自動生成・API投稿するスクリプト"
    )
    parser.add_argument(
        "--site",
        choices=["debaser", "streetvoice", "whattheduck", "koreanindie", "fungjaizine", "pophariini", "whiteboardjournal"],
        default="debaser",
        help="対象にする情報取得元サイト (デフォルト: debaser)"
    )
    parser.add_argument(
        "--category",
        choices=["music", "art", "onscreen", "culturecommunity", "all"],
        default="music",
        help="対象にする記事カテゴリ (debaserサイト選択時のみ有効, デフォルト: music)"
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="重複チェックを無視して強制的に記事生成・投稿を実行する"
    )
    parser.add_argument(
        "--max-check-pages",
        type=int,
        default=5,
        help="重複チェック時に遡るはてなブログのエントリー一覧の最大ページ数 (デフォルト: 5)"
    )
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="下書き保存ではなく予約投稿として公開する（最初の記事を8:00、以降2時間間隔でスケジュール）"
    )
    return parser.parse_args()


def rule_based_artist_extraction(title: str) -> str:
    """Gemini API呼び出しが失敗した際などのルールベースのアーティスト名抽出フォールバック"""
    title = title.strip(' "“’‘”')
    
    # タイトルのカッコ書きなどを事前にトリミング (例: เดิมเดิม (Once) -> Once)
    title_clean = re.sub(r'\(.*?\)', '', title).strip()
    title_clean = re.sub(r'（.*?）', '', title_clean).strip()
    
    # 1. "Artist on structure, freedom..." パターン
    if " on " in title_clean:
        parts = title_clean.split(" on ")
        return parts[0].strip()
    
    # 2. "Title" - Artist's... パターン
    if " - " in title_clean:
        parts = title_clean.split(" - ")
        candidate = parts[1].strip()
        candidate = re.sub(r"['’]s\b.*", "", candidate, flags=re.IGNORECASE)
        return candidate
    
    # 3. Artist: Title または Title: Artist on... パターン
    if ":" in title_clean:
        parts = title_clean.split(":")
        if " on " in parts[1]:
            subparts = parts[1].split(" on ")
            return subparts[0].strip()
        if len(parts[0]) < 25:
            return parts[0].strip()
        return parts[1].strip()
        
    return "Unknown"


def extract_article_content_from_url(url: str) -> str:
    """記事詳細ページのURLから本文を抽出する"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read()
        soup = BeautifulSoup(html, 'html.parser')
        
        # WordPress (.entry-content), Wix (article), Squarespace (.blog-item-content) 等に対応
        content_el = (
            soup.find('article') or 
            soup.find(class_='blog-item-content') or 
            soup.find(class_='entry-content') or 
            soup.find(class_='post-content')
        )
        if content_el:
            return content_el.get_text(separator='\n').strip()
        else:
            return soup.get_text(separator='\n').strip()
    except Exception as e:
        print_status(f"URLからの本文抽出に失敗しました ({url}): {e}", "warning")
        return ""


def fetch_latest_article(site: str, category: str) -> Dict[str, str]:
    """最新記事の取得 (RSSフィードを優先し、失敗時はHTMLスクレイピングを行う)"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # Custom handling for Korean Indie (WordPress REST API)
    if site == "koreanindie":
        wp_api_url = "https://www.koreanindie.com/wp-json/wp/v2/posts?per_page=5"
        print_status(f"WordPress REST APIから最新記事を取得中 ({site}): {wp_api_url} ...", "info")
        try:
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(wp_api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
                content_data = response.read().decode('utf-8')
            posts = json.loads(content_data)
            if posts:
                latest_post = posts[0]
                title = latest_post.get('title', {}).get('rendered', '').strip()
                link = latest_post.get('link', '').strip()
                
                excerpt_html = latest_post.get('excerpt', {}).get('rendered', '')
                description = BeautifulSoup(excerpt_html, 'html.parser').get_text(separator='\n').strip()
                
                content_html = latest_post.get('content', {}).get('rendered', '')
                content_text = BeautifulSoup(content_html, 'html.parser').get_text(separator='\n').strip()
                
                return {
                    'title': title,
                    'link': link,
                    'description': description,
                    'content_text': content_text,
                    'source': f"{site.upper()} WP-API"
                }
        except Exception as e:
            print_status(f"WordPress REST APIの取得に失敗しました: {e}", "warning")

    # Custom handling for Fungjaizine (HTML scraping)
    elif site == "fungjaizine":
        site_url = "https://fungjaizine.com/"
        print_status(f"HTMLスクレイピングから最新記事を取得中 ({site}): {site_url} ...", "info")
        try:
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(site_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
                html_data = response.read().decode('utf-8')
            
            soup = BeautifulSoup(html_data, 'html.parser')
            found_articles = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.startswith('http'):
                    full_url = href
                else:
                    href_clean = href.lstrip('/')
                    full_url = f"https://fungjaizine.com/{href_clean}"
                    
                path = full_url.replace('https://fungjaizine.com', '')
                parts = [p for p in path.strip('/').split('/') if p]
                
                if len(parts) >= 2 and parts[0] in ['article', 'news', 'interview', 'trending_news', 'quick_read']:
                    title = a.text.strip()
                    if not title:
                        img = a.find('img')
                        if img and img.get('alt'):
                            title = img.get('alt').strip()
                    if not title:
                        h_tag = a.find(['h1', 'h2', 'h3', 'h4']) or a.parent.find(['h1', 'h2', 'h3', 'h4'])
                        if h_tag:
                            title = h_tag.text.strip()
                    
                    if full_url not in [x['link'] for x in found_articles]:
                        found_articles.append({'title': title or 'Untitled', 'link': full_url})
            
            if found_articles:
                latest = found_articles[0]
                print_status(f"最新記事のURLを特定しました: {latest['link']}。詳細コンテンツを取得します...", "info")
                
                # Fetch details page
                art_req = urllib.request.Request(latest['link'], headers=headers)
                with urllib.request.urlopen(art_req, timeout=10, context=ssl_context) as response:
                    art_content = response.read().decode('utf-8')
                art_soup = BeautifulSoup(art_content, 'html.parser')
                
                title = latest['title']
                if title == 'Untitled' or not title:
                    h1_tag = art_soup.find('h1')
                    if h1_tag:
                        title = h1_tag.text.strip()
                    else:
                        title_tag = art_soup.find('title')
                        if title_tag:
                            title = title_tag.text.strip()
                
                content_el = (
                    art_soup.find('article') or 
                    art_soup.find(class_='blog-item-content') or 
                    art_soup.find(class_='entry-content') or 
                    art_soup.find(class_='post-content') or
                    art_soup.find(class_='content') or
                    art_soup.find(id='content') or
                    art_soup.find(class_='post')
                )
                
                if content_el:
                    content_text = content_el.get_text(separator='\n').strip()
                else:
                    content_text = art_soup.get_text(separator='\n').strip()
                    
                return {
                    'title': title or 'Untitled',
                    'link': latest['link'],
                    'description': title,
                    'content_text': content_text,
                    'source': 'FUNGJAIZINE HTML Scrape'
                }
        except Exception as e:
            print_status(f"FungjaizineのHTMLスクレイピングに失敗しました: {e}", "warning")

    # 1. 各サイトのRSSフィードURL設定
    if site == "debaser":
        feed_url = f"https://debasermagazine.com/{category}?format=rss" if category != "all" else "https://debasermagazine.com/music?format=rss"
    elif site == "streetvoice":
        feed_url = "https://blow.streetvoice.com/feed/"
    elif site == "whattheduck":
        feed_url = "https://www.whattheduckmusic.com/blog-feed.xml"
    elif site == "pophariini":
        feed_url = "https://pophariini.com/feed/"
    elif site == "whiteboardjournal":
        feed_url = "https://www.whiteboardjournal.com/category/music/feed/"
    else:
        raise ValueError(f"不明なサイトです: {site}")

    print_status(f"RSSフィードから最新記事を取得中 ({site}): {feed_url} ...", "info")
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
            
            # encoded要素からの本文取得 (WordPress, Squarespace対応)
            encoded_el = latest_item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
            content_html = encoded_el.text if encoded_el is not None else ""
            
            if content_html:
                soup = BeautifulSoup(content_html, 'html.parser')
                content_text = soup.get_text(separator='\n').strip()
            else:
                # WixなどのようにRSSにencoded本文が含まれない場合はURLから動的抽出
                print_status("RSSに本文が含まれていないため、記事URLから直接抽出します...", "info")
                content_text = extract_article_content_from_url(link)
                if not content_text:
                    content_text = description
                
            return {
                'title': title,
                'link': link,
                'description': description,
                'content_text': content_text,
                'source': f"{site.upper()} RSS"
            }
    except Exception as e:
        print_status(f"RSSフィードの取得/解析に失敗しました: {e}。HTMLスクレイピングを試みます...", "warning")

    # 2. 各サイトのHTMLスクレイピング・フォールバック
    print_status(f"スクレイピングによる最新記事取得を試みます...", "info")
    try:
        if site == "debaser":
            site_url = "https://debasermagazine.com/"
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
                excerpt_el = item.find(class_='summary-excerpt')
                excerpt = excerpt_el.text.strip() if excerpt_el else ""
                items.append({'title': title, 'link': link, 'excerpt': excerpt})
            if items:
                latest = items[0]
                content_text = extract_article_content_from_url(latest['link'])
                return {
                    'title': latest['title'],
                    'link': latest['link'],
                    'description': latest['excerpt'],
                    'content_text': content_text or latest['excerpt'],
                    'source': 'DEBASER HTML Scrape'
                }

        elif site == "streetvoice":
            site_url = "https://blow.streetvoice.com/"
            req = urllib.request.Request(site_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                html_data = response.read()
            soup = BeautifulSoup(html_data, 'html.parser')
            links = []
            for a in soup.find_all('a'):
                href = a.get('href', '')
                if re.search(r'blow\.streetvoice\.com/\d+/?$', href):
                    title = a.text.strip()
                    if len(title) > 5:
                        links.append({'title': title, 'link': href})
            if links:
                latest = links[0]
                content_text = extract_article_content_from_url(latest['link'])
                return {
                    'title': latest['title'],
                    'link': latest['link'],
                    'description': latest['title'],
                    'content_text': content_text,
                    'source': 'STREETVOICE HTML Scrape'
                }

        elif site == "whattheduck":
            site_url = "https://www.whattheduckmusic.com/"
            req = urllib.request.Request(site_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                html_data = response.read()
            soup = BeautifulSoup(html_data, 'html.parser')
            links = []
            for a in soup.find_all('a'):
                href = a.get('href', '')
                if '/post/' in href:
                    if not href.startswith('http'):
                        href = "https://www.whattheduckmusic.com" + href
                    title = a.text.strip() or a.get('aria-label', '').strip()
                    if len(title) > 1:
                        links.append({'title': title, 'link': href})
            if links:
                latest = links[0]
                content_text = extract_article_content_from_url(latest['link'])
                return {
                    'title': latest['title'],
                    'link': latest['link'],
                    'description': latest['title'],
                    'content_text': content_text,
                    'source': 'WHATTHEDUCK HTML Scrape'
                }

        raise ValueError("対応するスクレイピングロジックが見つかりません。")
    except Exception as e:
        print_status(f"最新記事の取得に完全に失敗しました: {e}", "error")
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
            f"以下は海外の音楽メディア記事のタイトルと本文です。この記事で紹介されている中心的な音楽アーティストまたはバンド名を抽出してください。\n"
            f"回答はアーティスト/バンド名のみとし、余計な説明や引用符、句読点は一切含めないでください。\n"
            f"もし特定のアーティストではなくイベントやコンピレーションなどの場合は、主役となるアーティスト名、または最も関連するアーティスト名を1つだけ抽出してください。判断が難しい場合は 'Unknown' と返してください。\n\n"
            f"タイトル: {title}\n"
            f"本文: {content_text[:1000]}\n"
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

        class ArtistIntro(BaseModel):
            name: str = Field(description="アーティスト名")
            description: str = Field(description="アーティストの簡単な紹介（日本語、1行以内・100文字程度）")

        class HatenaBlogParts(BaseModel):
            is_compilation: bool = Field(description="この記事が『New Music Friday』や『フェス出演者紹介』、『新曲まとめ』など、複数のアーティストをオムニバス形式で紹介する記事である場合はTrue、単一のアーティスト紹介記事である場合はFalse。記事内に3組以上のアーティストが登場する場合は原則Trueにしてください")
            blog_title: str = Field(description="はてなブログ記事のキャッチーなタイトル（日本語、50文字以内、例: 【K-Indie】Kuang Programの深淵なるノイズロックの世界、または 【タイ】Maho Rasop 2024 出演者ラインナップ紹介 など）")
            genre: List[str] = Field(description=f"アーティストのジャンル（単一アーティスト紹介時（is_compilationがFalse）のみ使用、最大3つ。必ず次のリスト内の文字列のみから選択してください: {', '.join(ALLOWED_GENRES)}。どれにも当てはまらない場合は空リストにしてください。複数紹介時は空リスト）")
            bio_style: str = Field(description="経歴・作風（単一アーティスト紹介時（is_compilationがFalse）のみ使用、300文字程度。複数紹介時は空文字列）")
            youtube_query: str = Field(description="YouTube検索クエリ（単一アーティスト紹介時（is_compilationがFalse）のみ使用。複数紹介時は空文字列）")
            article_purpose: str = Field(description="元記事の趣旨（なぜこの記事が書かれたのか、どのような文脈・意図（例：新譜のリリース、周年記念、シーンの現状紹介など）で公開されたかを100文字〜150文字程度で簡潔に説明。口調は「です」「ます」）")
            compilation_artists: List[ArtistIntro] = Field(description="複数アーティスト紹介記事（is_compilationがTrue）の場合のみ、紹介されているアーティスト名と1行以内の紹介文のリスト。単一アーティストの場合は空リスト")

        user_prompt = (
            f"# Context\n"
            f"あなたはアジアのインディーズ音楽（K-Indie、台湾インディー、タイポップスなど）に精通したカルチャーライターです。\n"
            f"渡された海外メディアの記事情報を元に、日本のリスナー向けにアーティストを紹介するブログ記事のパーツを生成してください。\n\n"
            f"# Input Data\n"
            f"- 元記事タイトル: {title}\n"
            f"- アーティスト名: {artist_name}\n"
            f"- 元記事の本文（参考情報）: \n{content_text[:3000]}\n\n"
            f"# Constraints\n"
            f"- 元記事が『New Music Friday』や『フェス』『新曲まとめ（Short Stuff等）』のように、複数のアーティストを紹介しているオムニバス形式の記事である場合は、is_compilationをTrueに設定し、紹介されている各アーティスト名と1行以内の日本語紹介文をcompilation_artistsにリストアップしてください。\n"
            f"- 単一アーティストの紹介記事である場合は、is_compilationをFalseに設定し、ジャンル、経歴・作風、YouTube検索クエリを生成してください。\n"
            f"- ジャンル（genre）を決定する際は、必ず次のリストの中から最も適合するものを最大3つ選択してください。リストにない他のジャンルは一切含めないでください。どれにも当てはまらない場合は、空リスト（[]）にしてください。\n"
            f"  許可リスト: {', '.join(ALLOWED_GENRES)}\n"
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
            
            genres_str = "、".join(result_data.get('genre', []))
            text_format = (
                f"ブログタイトル: {result_data.get('blog_title', '')}\n"
                f"1. ジャンル: {genres_str}\n"
                f"2. 経歴・作風: {result_data.get('bio_style', '')}\n"
                f"3. YouTube検索クエリ: {result_data.get('youtube_query', '')}\n"
                f"4. 元記事の趣旨: {result_data.get('article_purpose', '')}"
            )
            
            return {
                "title": title,
                "link": link,
                "artist_name": artist_name,
                "blog_title": result_data.get('blog_title', ''),
                "genre": result_data.get('genre', []),
                "bio_style": result_data.get('bio_style', ''),
                "youtube_query": result_data.get('youtube_query', ''),
                "article_purpose": result_data.get('article_purpose', ''),
                "is_compilation": result_data.get('is_compilation', False),
                "compilation_artists": result_data.get('compilation_artists', []),
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
        "is_compilation": False,
        "compilation_artists": [],
        "text_output": text_output
    }


def assemble_markdown_post(
    site: str,
    blog_parts: Dict[str, Any],
    latest_video: Dict[str, Any],
    most_viewed_video: Dict[str, Any]
) -> str:
    """はてなブログ用に各パーツをアセンブルして綺麗なMarkdown記事を作成する"""
    site_names = {
        "debaser": "Debaser Magazine",
        "streetvoice": "Blow (StreetVoice)",
        "whattheduck": "What The Duck",
        "koreanindie": "Korean Indie",
        "fungjaizine": "Fungjaizine",
        "pophariini": "Pop Hari Ini",
        "whiteboardjournal": "Whiteboard Journal"
    }
    site_name = site_names.get(site, site.upper())
    translate_url = f"https://translate.google.com/translate?sl=auto&tl=ja&u={urllib.parse.quote(blog_parts['link'])}"
    
    is_compilation = blog_parts.get("is_compilation", False)
    
    if is_compilation:
        artists_section = ""
        comp_artists = blog_parts.get("compilation_artists", [])
        for art in comp_artists:
            name = art.get("name", "").strip()
            desc = art.get("description", "").strip()
            if name and desc:
                artists_section += f"* **{name}**: {desc}\n"
                
        body = f"""海外のインディーズ音楽メディア「{site_name}」の最新記事から、紹介されている注目アーティストをまとめてご紹介します。

### 元記事情報
* **紹介元の記事 (原文)**: [{blog_parts['title']}]({blog_parts['link']})
* **紹介元の記事 (日本語自動翻訳版)**: [Google翻訳で読む]({translate_url})
* **メディア**: {site_name}

---

### 元記事の概要
{blog_parts['article_purpose']}

---

### 紹介アーティスト一覧

{artists_section}
*(※この記事は {site_name} の公開記事情報を元に、自動生成ツールによって作成されました。)*"""
        return body

    genres_str = "、".join(blog_parts.get("genre", []))
    
    body = f"""海外のインディーズ音楽メディア「{site_name}」の最新記事から、注目のアーティストをご紹介します。

### 元記事情報
* **紹介元の記事 (原文)**: [{blog_parts['title']}]({blog_parts['link']})
* **紹介元の記事 (日本語自動翻訳版)**: [Google翻訳で読む]({translate_url})
* **メディア**: {site_name}

---

### 元記事の概要
{blog_parts['article_purpose']}

---

### アーティスト紹介：**{blog_parts['artist_name']}**

* **ジャンル**: {genres_str}
* **経歴・作風**:
{blog_parts['bio_style']}

---

### おすすめ動画・MV

"""
    def escape_markdown(text: str) -> str:
        if not text:
            return ""
        return re.sub(r'([\*\_\[\]\(\)])', r'\\\1', text)

    if latest_video:
        latest_title = escape_markdown(latest_video.get('title', ''))
        body += f"""#### 最新の動画
{latest_video.get('hatena_embed')}

* **動画タイトル**: {latest_title}
* **公開日 / 再生回数**: {latest_video.get('published')} / {latest_video.get('views')}

"""
    if most_viewed_video:
        most_viewed_title = escape_markdown(most_viewed_video.get('title', ''))
        body += f"""#### 人気動画
{most_viewed_video.get('hatena_embed')}

* **動画タイトル**: {most_viewed_title}
* **公開日 / 再生回数**: {most_viewed_video.get('published')} / {most_viewed_video.get('views')}

"""
    body += f"\n*(※この記事は {site_name} の公開記事情報を元に、自動生成ツールによって作成されました。)*"
    return body


def publish_to_hatena_blog_api(
    hatena_id: str,
    blog_id: str,
    api_key: str,
    title: str,
    content: str,
    categories: List[str] = None,
    draft: bool = True,
    updated_time: str = None
) -> bool:
    """はてなブログ AtomPub APIを利用して記事を投稿する"""
    url = f"https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry"
    
    # カテゴリタグの生成
    category_tags = ""
    if categories:
        for cat in categories:
            category_tags += f'  <category term="{cat}" />\n'
            
    # 投稿日時の設定 (予約投稿用)
    updated_tag = f"  <updated>{updated_time}</updated>\n" if updated_time else ""
            
    # 予約投稿用のフラグ設定
    scheduled_tag = ""
    if updated_time:
        scheduled_tag = "    <hatenablog:scheduled>yes</hatenablog:scheduled>\n"
        draft_val = "yes"
    else:
        draft_val = "yes" if draft else "no"
            
    # XMLペイロードの組み立て (特殊文字崩れ防止のためCDATAでラップ)
    xml_data = f"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:app="http://www.w3.org/2007/app"
       xmlns:hatenablog="http://www.hatena.ne.jp/info/xmlns#hatenablog">
  <title>{title}</title>
  <author><name>{hatena_id}</name></author>
  <content type="text/x-markdown"><![CDATA[{content}]]></content>
{updated_tag}{category_tags}  <app:control>
    <app:draft>{draft_val}</app:draft>
{scheduled_tag}  </app:control>
</entry>
"""
    
    headers = {
        'Content-Type': 'application/xml; charset=utf-8',
        'User-Agent': 'DebaserBlogGenerator/1.0'
    }
    
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


def check_duplicate(
    hatena_id: str,
    blog_id: str,
    api_key: str,
    source_url: str,
    max_pages: int = 5
) -> bool:
    """Hatena Blogの過去記事をチェックし、指定されたソースURLの記事がすでに紹介されているか調べる"""
    url = f"https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry"
    
    # 比較のためにURLを正規化（プロトコルと末尾のスラッシュを無視）
    def clean_url(u: str) -> str:
        u = re.sub(r'^https?://', '', u)
        u = u.rstrip('/')
        return u
        
    cleaned_source = clean_url(source_url)
    
    auth_str = f"{hatena_id}:{api_key}"
    auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f"Basic {auth_b64}",
        'User-Agent': 'DebaserBlogGenerator/1.0'
    }
    
    current_url = url
    pages_checked = 0
    
    print_status(f"既に公開されている記事の重複チェックを開始します (上限: {max_pages}ページ)...", "info")
    
    while current_url and pages_checked < max_pages:
        try:
            req = urllib.request.Request(current_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                
            root = ET.fromstring(xml_data)
            
            # 各エントリーをチェック
            entries = root.findall("{http://www.w3.org/2005/Atom}entry")
            for entry in entries:
                title_el = entry.find("{http://www.w3.org/2005/Atom}title")
                title = title_el.text if title_el is not None else ""
                
                content_el = entry.find("{http://www.w3.org/2005/Atom}content")
                content = content_el.text if (content_el is not None and content_el.text is not None) else ""
                
                summary_el = entry.find("{http://www.w3.org/2005/Atom}summary")
                summary = summary_el.text if (summary_el is not None and summary_el.text is not None) else ""
                
                text_to_check = content + "\n" + summary
                
                # コンテンツ内の紹介元URLをチェック
                found_urls = re.findall(r'https?://[^\s\)\]\"\'\>\<\,\;]+', text_to_check)
                for f_url in found_urls:
                    if clean_url(f_url) == cleaned_source:
                        print_status("重複記事が見つかりました！", "warning")
                        print_status(f"  重複する公開済記事: {title}", "warning")
                        print_status(f"  紹介元URL: {source_url}", "warning")
                        return True
                        
            # 次のページURLを取得
            next_url = None
            for link in root.findall("{http://www.w3.org/2005/Atom}link"):
                if link.get("rel") == "next":
                    next_url = link.get("href")
                    break
            
            current_url = next_url
            pages_checked += 1
            
        except Exception as e:
            print_status(f"はてなブログ過去記事の取得中にエラーが発生しました: {e}", "warning")
            if hasattr(e, 'read'):
                try:
                    error_body = e.read().decode('utf-8')
                    print(f"APIエラー詳細: {error_body}")
                except Exception:
                    pass
            raise e
            
    print_status("重複する記事は見つかりませんでした。", "success")
    return False


def get_next_schedule_time(
    hatena_id: str,
    blog_id: str,
    api_key: str,
    max_pages: int = 5
) -> str:
    """今日のはてなブログ投稿状況を確認し、次の予約投稿日時（JST）を決定する"""
    import datetime
    
    tz_jst = datetime.timezone(datetime.timedelta(hours=9))
    now_jst = datetime.datetime.now(tz_jst)
    today_str = now_jst.strftime('%Y-%m-%d')
    
    url = f"https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry"
    auth_str = f"{hatena_id}:{api_key}"
    auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f"Basic {auth_b64}",
        'User-Agent': 'DebaserBlogGenerator/1.0'
    }
    
    current_url = url
    pages_checked = 0
    scheduled_hours = []
    
    print_status("本日の投稿状況を確認し、予約投稿時間を決定します...", "info")
    
    while current_url and pages_checked < max_pages:
        try:
            req = urllib.request.Request(current_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
            root = ET.fromstring(xml_data)
            
            entries = root.findall("{http://www.w3.org/2005/Atom}entry")
            for entry in entries:
                # 下書きは無視する
                draft_el = entry.find("{http://www.w3.org/2007/app}control/{http://www.w3.org/2007/app}draft")
                if draft_el is not None and draft_el.text == "yes":
                    continue
                
                updated_el = entry.find("{http://www.w3.org/2005/Atom}updated")
                if updated_el is not None and updated_el.text:
                    dt_str = updated_el.text
                    match = re.match(r'^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})', dt_str)
                    if match:
                        entry_date = match.group(1)
                        entry_hour = int(match.group(2))
                        if entry_date == today_str:
                            scheduled_hours.append(entry_hour)
            
            # 次のページURLを取得
            next_url = None
            for link in root.findall("{http://www.w3.org/2005/Atom}link"):
                if link.get("rel") == "next":
                    next_url = link.get("href")
                    break
            current_url = next_url
            pages_checked += 1
        except Exception as e:
            print_status(f"投稿スケジュール確認中にエラーが発生しました（デフォルトで判定します）: {e}", "warning")
            break

    # 次の投稿スロットを計算 (8:00から開始、2時間ごと。現在時刻より5分以上先であること)
    target_hour = 8
    while True:
        target_time = now_jst.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        # もしターゲット時刻が現在時刻＋5分より過去、または既にその時間枠に投稿がある場合は次へ
        if target_hour in scheduled_hours or target_time <= now_jst + datetime.timedelta(minutes=5):
            target_hour += 2
        else:
            break
            
    scheduled_dt = now_jst.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    print_status(f"決定した予約投稿時刻: {scheduled_dt.strftime('%Y-%m-%d %H:%M:%S')} JST", "success")
    return scheduled_dt.isoformat()


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
        sys.exit(1)
        
    # 最新記事の取得
    article = fetch_latest_article(args.site, args.category)
    
    print("\n" + "="*50)
    print_status("取得した記事情報", "success")
    print(f"情報取得元     : {article['source']}")
    print(f"元記事タイトル : {article['title']}")
    print(f"元記事リンク     : {article['link']}")
    print("="*50 + "\n")
    
    # 重複チェックの実行
    is_duplicate = False
    if not args.force:
        # はてなブログの認証情報が存在するか確認
        if args.hatena_id and args.hatena_blog_id and args.hatena_api_key:
            try:
                is_duplicate = check_duplicate(
                    hatena_id=args.hatena_id,
                    blog_id=args.hatena_blog_id,
                    api_key=args.hatena_api_key,
                    source_url=article['link'],
                    max_pages=args.max_check_pages
                )
            except Exception as e:
                if args.publish:
                    print_status("重複チェック中にエラーが発生したため、処理を中断します（--publish指定時）。", "error")
                    sys.exit(1)
                else:
                    print_status("認証情報の不整合または通信エラーのため、重複チェックをスキップして処理を続行します。", "warning")
        else:
            if args.publish:
                print_status("はてなブログの認証情報が設定されていないため、処理を中断します（--publish指定時）。", "error")
                sys.exit(1)
            else:
                print_status("はてなブログの認証情報が設定されていないため、重複チェックをスキップします。", "warning")
                
    if is_duplicate:
        print_status("取得した記事はすでに紹介済みのため、処理を終了します。", "warning")
        sys.exit(0)
    
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
        
    # YouTube検索の実行
    yt_query = blog_parts.get("youtube_query")
    is_compilation = blog_parts.get("is_compilation", False)
    latest_video = {}
    most_viewed_video = {}
    
    if yt_query and not is_compilation:
        print_status(f"YouTubeで動画リストを検索中: '{yt_query}' ...", "info")
        videos = get_youtube_videos(yt_query, None)
        
        if videos:
            # 再生回数の数値化用ヘルパー
            def parse_view_count(views_str: str) -> int:
                if not views_str:
                    return 0
                s = views_str.lower().strip()
                s = s.replace('views', '').replace('view', '').replace(',', '').strip()
                s = s.replace('回', '').replace('再生', '').strip()
                
                multiplier = 1
                if 'billion' in s or 'b' in s:
                    multiplier = 1000000000
                    s = re.sub(r'[a-z]', '', s).strip()
                elif 'million' in s or 'm' in s:
                    multiplier = 1000000
                    s = re.sub(r'[a-z]', '', s).strip()
                elif 'k' in s:
                    multiplier = 1000
                    s = re.sub(r'[a-z]', '', s).strip()
                elif '億' in s:
                    multiplier = 100000000
                    s = s.replace('億', '').strip()
                elif '万' in s:
                    multiplier = 10000
                    s = s.replace('万', '').strip()
                try:
                    return int(float(s) * multiplier)
                except ValueError:
                    match = re.search(r'([\d\.]+)', s)
                    if match:
                        try:
                            return int(float(match.group(1)) * multiplier)
                        except ValueError:
                            pass
                    return 0

            # 公開日の数値（日数）化用ヘルパー（小さいほど新しい）
            def parse_published_to_days(pub_str: str) -> int:
                if not pub_str:
                    return 99999
                s = pub_str.lower().strip()
                match = re.search(r'(\d+)\s*(year|month|week|day|hour|minute|年|か月|月|週|日|時間|分)', s)
                if not match:
                    if 'second' in s or 'minute' in s or 'hour' in s or '秒' in s or '分' in s or '時間' in s or 'now' in s:
                        return 0
                    return 99999
                val = int(match.group(1))
                unit = match.group(2)
                if unit in ['year', '年']:
                    return val * 365
                elif unit in ['month', 'か月', '月']:
                    return val * 30
                elif unit in ['week', '週']:
                    return val * 7
                elif unit in ['day', '日']:
                    return val
                elif unit in ['hour', 'minute', '時間', '分']:
                    return 0
                return 99999

            # 1. 再生回数が多い順にソート (人気動画用)
            by_views = sorted(videos, key=lambda v: parse_view_count(v.get('views', '')), reverse=True)
            # 2. 公開日が新しい（日数が小さい）順にソート (最新動画用)
            by_date = sorted(videos, key=lambda v: parse_published_to_days(v.get('published', '')))
            
            # 人気動画の選定 (再生数トップ)
            most_viewed_video = by_views[0]
            
            # 最新の動画の選定 (公開日が一番新しく、かつ人気動画と異なる動画を優先)
            most_viewed_id = most_viewed_video.get('id')
            for video in by_date:
                if video.get('id') != most_viewed_id:
                    latest_video = video
                    break
            # もし結果が1つしかないなど、別動画が見つからない場合は同じものにする
            if not latest_video:
                latest_video = most_viewed_video
    
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
                f"・関連性の高い動画 (はてなブログ形式):\n"
                f"  {most_viewed_video.get('hatena_embed')}\n"
                f"  (タイトル: {most_viewed_video.get('title')} | 投稿: {most_viewed_video.get('published')} | 再生数: {most_viewed_video.get('views')})\n"
            )

    # はてなブログへ投稿するMarkdown形式の完全な記事を作成
    complete_blog_post = assemble_markdown_post(args.site, blog_parts, latest_video, most_viewed_video)

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
            print_status("はてなブログAPIキーが設定されていません。", "error")
            sys.exit(1)
            
        # サイトに応じた国別カテゴリの判定
        site_categories = {
            "streetvoice": ["台湾"],
            "koreanindie": ["韓国"],
            "whattheduck": ["タイ"],
            "fungjaizine": ["タイ"],
            "pophariini": ["インドネシア"],
            "whiteboardjournal": ["インドネシア"]
        }
        categories = list(site_categories.get(args.site, []))
        
        # 国別カテゴリに加え、Geminiが抽出したジャンル（小分類）カテゴリを追加
        is_compilation = blog_parts.get("is_compilation", False)
        genres = blog_parts.get("genre", [])
        assigned_genres = []
        
        if genres:
            for g in genres:
                g_clean = g.strip()
                # ALLOWED_GENRESと大文字小文字を無視してマッチング
                matched = None
                for allowed in ALLOWED_GENRES:
                    if g_clean.lower() == allowed.lower():
                        matched = allowed
                        break
                if matched:
                    if matched not in categories:
                        categories.append(matched)
                        assigned_genres.append(matched)
                        
        # 1つも該当するジャンルがなく、かつまとめ記事でない場合は「不明」を付与
        if not is_compilation and not assigned_genres:
            if "不明" not in categories:
                categories.append("不明")
            
        # 予約投稿日時の決定
        updated_time = None
        draft_to_publish = args.draft
        
        # アーティスト紹介の情報が不足しているか判定
        insufficient_info = False
        is_compilation = blog_parts.get("is_compilation", False)
        
        if not is_compilation:
            artist_name = blog_parts.get("artist_name", "").strip()
            bio_style = blog_parts.get("bio_style", "").strip()
            if not artist_name or artist_name.lower() == "unknown" or not bio_style or bio_style.lower() == "unknown":
                insufficient_info = True
                print_status("アーティスト名または紹介文の取得が不十分なため、情報不足と判定しました。", "warning")

        if args.scheduled:
            if insufficient_info:
                print_status("情報不足と判定されたため、予約投稿を行わず下書き（下書き保存）として投稿します。", "warning")
                draft_to_publish = True
            else:
                try:
                    updated_time = get_next_schedule_time(
                        hatena_id=args.hatena_id,
                        blog_id=args.hatena_blog_id,
                        api_key=args.hatena_api_key,
                        max_pages=args.max_check_pages
                    )
                    draft_to_publish = False  # 予約投稿にするため下書き状態を解除して公開(予約)で投稿
                except Exception as e:
                    print_status(f"予約投稿時刻の取得に失敗したため、下書きとして投稿します: {e}", "warning")
                    draft_to_publish = True
            
        publish_to_hatena_blog_api(
            hatena_id=args.hatena_id,
            blog_id=args.hatena_blog_id,
            api_key=args.hatena_api_key,
            title=blog_parts['blog_title'],
            content=complete_blog_post,
            categories=categories,
            draft=draft_to_publish,
            updated_time=updated_time
        )


if __name__ == "__main__":
    main()
