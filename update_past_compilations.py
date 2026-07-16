import urllib.request
import urllib.parse
import base64
import xml.etree.ElementTree as ET
import re
import argparse
import os
import sys
import json

def parse_args():
    parser = argparse.ArgumentParser(description="はてなブログの過去のまとめ記事（is_compilation = True）に、最初のアーティストの人気YouTube動画を自動挿入するスクリプト")
    parser.add_argument(
        "--hatena-id",
        default=os.environ.get("HATENA_ID"),
        help="はてなID"
    )
    parser.add_argument(
        "--hatena-blog-id",
        default=os.environ.get("HATENA_BLOG_ID"),
        help="はてなブログID / ドメイン"
    )
    parser.add_argument(
        "--hatena-api-key",
        default=os.environ.get("HATENA_API_KEY"),
        help="はてなブログAPIキー/APIパスコード"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=15,
        help="遡って確認する最大ページ数 (デフォルト: 15)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際に更新せず、更新予定の内容を表示する"
    )
    return parser.parse_args()

def get_youtube_videos(query: str) -> list:
    """YouTubeで検索を行い、上位の動画リストを取得する"""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
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
        print(f"YouTube検索中にエラーが発生しました: {e}")
    return []

def parse_view_count(views_str: str) -> int:
    """再生回数の文字列を数値に変換する"""
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

def main():
    args = parse_args()
    if not args.hatena_id or not args.hatena_blog_id or not args.hatena_api_key:
        print("エラー: はてなブログの認証情報（HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY）が不足しています。環境変数またはコマンドライン引数で設定してください。")
        sys.exit(1)
        
    url = f"https://blog.hatena.ne.jp/{args.hatena_id}/{args.hatena_blog_id}/atom/entry"
    auth_str = f"{args.hatena_id}:{args.hatena_api_key}"
    auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f"Basic {auth_b64}",
        'Content-Type': 'application/xml; charset=utf-8',
        'User-Agent': 'CompilationUpdater/1.0'
    }
    
    # XML名前空間の登録
    ET.register_namespace('', 'http://www.w3.org/2005/Atom')
    ET.register_namespace('app', 'http://www.w3.org/2007/app')
    ET.register_namespace('hatenablog', 'http://www.hatena.ne.jp/info/xmlns#hatenablog')
    
    current_url = url
    pages_checked = 0
    updated_count = 0
    checked_count = 0
    
    print(f"■ 開始: まとめ記事（is_compilation）へのYouTube動画挿入プログラム")
    print(f"対象ブログ: {args.hatena_blog_id}")
    if args.dry_run:
        print("※テストモード (DRY RUN) で実行中。実際には更新されません。")
    print("------------------------------------------")
    
    while current_url and pages_checked < args.max_pages:
        try:
            req = urllib.request.Request(current_url, headers={
                'Authorization': f"Basic {auth_b64}",
                'User-Agent': 'CompilationUpdater/1.0'
            })
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
            root = ET.fromstring(xml_data)
            
            entries = root.findall("{http://www.w3.org/2005/Atom}entry")
            if not entries:
                break
                
            for entry in entries:
                checked_count += 1
                title_el = entry.find("{http://www.w3.org/2005/Atom}title")
                title = title_el.text if title_el is not None else "No Title"
                
                content_el = entry.find("{http://www.w3.org/2005/Atom}content")
                if content_el is None or not content_el.text:
                    continue
                
                content = content_el.text
                
                # まとめ記事（is_compilation = True）かチェック
                if "紹介アーティスト一覧" not in content and "### 紹介アーティスト一覧" not in content:
                    continue
                
                # 最初のアーティスト名を抽出
                comp_list_match = re.search(r'### 紹介アーティスト一覧\s*\n\s*(.*)', content, re.DOTALL)
                if not comp_list_match:
                    continue
                
                artists_block = comp_list_match.group(1)
                artist_name_match = re.search(r'\*\s*\*\*([^*]+)\*\*:', artists_block)
                if not artist_name_match:
                    continue
                
                first_artist_name = artist_name_match.group(1).strip()
                print(f"【まとめ記事検出】: 「{title}」")
                print(f"  - 最初のアーティスト: {first_artist_name}")
                
                # YouTubeで人気動画（最も再生回数が多いもの）を検索
                videos = get_youtube_videos(first_artist_name)
                if not videos:
                    print("  -> YouTubeで動画が見つかりませんでした。")
                    continue
                
                # 最も再生回数が多いものを選択
                sorted_videos = sorted(videos, key=lambda v: parse_view_count(v.get('views', '')), reverse=True)
                most_viewed_video = sorted_videos[0]
                embed_tag = most_viewed_video.get("hatena_embed")
                
                # 本文の更新処理
                # 1. 既存の動画セクションがあれば削除
                cleaned_content = re.sub(r'\n\s*---\s*\n\s*### 注目アーティスト動画・MV.*?(?=\n\s*\*\(※この記事は)', '', content, flags=re.DOTALL)
                
                # 2. 動画セクションを構築
                video_section = f"\n\n---\n\n### 注目アーティスト動画・MV\nここでは紹介されたアーティストの中から **{first_artist_name}** の人気動画をご紹介します。\n\n{embed_tag}\n\n"
                
                # 3. *(※この記事は の直前に挿入
                new_content = re.sub(r'(\n\s*\*\(※この記事は)', f"{video_section}\\1", cleaned_content)
                
                if new_content == content:
                    print("  -> 既に最新の動画リンクが設定されています。")
                    continue
                
                print(f"  -> 更新予定のYouTube動画: {most_viewed_video.get('title')} ({most_viewed_video.get('views')})")
                
                # XML要素のテキストを更新
                content_el.text = new_content
                
                # Edit URL の取得
                edit_url = None
                for link in entry.findall("{http://www.w3.org/2005/Atom}link"):
                    if link.get("rel") == "edit":
                        edit_url = link.get("href")
                        break
                        
                if not edit_url:
                    print("  -> エラー: 編集用URLが見つかりません。")
                    continue
                    
                if not args.dry_run:
                    try:
                        # XMLシリアライズ
                        updated_xml = ET.tostring(entry, encoding='utf-8')
                        
                        # PUTリクエスト
                        put_req = urllib.request.Request(edit_url, data=updated_xml, headers=headers, method='PUT')
                        with urllib.request.urlopen(put_req, timeout=10) as put_resp:
                            put_resp.read()
                        print(f"  -> 更新完了！")
                    except Exception as e:
                        print(f"  -> エラー: API更新に失敗しました: {e}")
                else:
                    print(f"  -> [DRY RUN] 更新の準備ができました。")
                    
                updated_count += 1
                
            next_url = None
            for link in root.findall("{http://www.w3.org/2005/Atom}link"):
                if link.get("rel") == "next":
                    next_url = link.get("href")
                    break
            current_url = next_url
            pages_checked += 1
            
        except Exception as e:
            print(f"エントリーリスト取得中にエラーが発生しました: {e}")
            break
            
    print("------------------------------------------")
    print("■ 処理完了")
    print(f"チェックした過去記事数: {checked_count}")
    print(f"動画を挿入/更新したまとめ記事数: {updated_count}")

if __name__ == "__main__":
    main()
