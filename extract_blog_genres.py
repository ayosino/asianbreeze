import urllib.request
import base64
import xml.etree.ElementTree as ET
import re
import argparse
import os
from collections import Counter

def parse_args():
    parser = argparse.ArgumentParser(description="はてなブログの既投稿からジャンル一覧を抽出・整理するスクリプト")
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
        "--max-pages",
        type=int,
        default=15,
        help="確認するエントリー一覧の最大ページ数 (デフォルト: 15)"
    )
    return parser.parse_args()

def main():
    args = parse_args()
    
    url = f"https://blog.hatena.ne.jp/{args.hatena_id}/{args.hatena_blog_id}/atom/entry"
    auth_str = f"{args.hatena_id}:{args.hatena_api_key}"
    auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f"Basic {auth_b64}",
        'User-Agent': 'GenreExtractor/1.0'
    }
    
    print(f"はてなID: {args.hatena_id}")
    print(f"ブログID: {args.hatena_blog_id}")
    print("はてなブログから過去の記事を取得し、ジャンル情報を抽出しています...")
    
    current_url = url
    pages_checked = 0
    genres_counter = Counter()
    articles_scanned = 0
    skipped_drafts = 0
    
    while current_url and pages_checked < args.max_pages:
        try:
            req = urllib.request.Request(current_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
            root = ET.fromstring(xml_data)
            
            entries = root.findall("{http://www.w3.org/2005/Atom}entry")
            if not entries:
                break
                
            for entry in entries:
                # 下書きチェック
                draft_el = entry.find("{http://www.w3.org/2007/app}control/{http://www.w3.org/2007/app}draft")
                if draft_el is not None and draft_el.text == "yes":
                    skipped_drafts += 1
                    # 下書きの記事からもジャンルを抽出対象にする場合は、ここでcontinueしない
                
                content_el = entry.find("{http://www.w3.org/2005/Atom}content")
                if content_el is not None and content_el.text:
                    content = content_el.text
                    articles_scanned += 1
                    
                    # 単一アーティスト紹介時の「* **ジャンル**: シューゲイザー、ドリームポップ」を抽出
                    match = re.search(r'\*\s*\*\*ジャンル\*\*:\s*(.*)', content)
                    if match:
                        genres_str = match.group(1).strip()
                        genres = [g.strip() for g in re.split(r'[、,，]', genres_str) if g.strip()]
                        for genre in genres:
                            genres_counter[genre] += 1
            
            # 次のページリンクの取得
            next_url = None
            for link in root.findall("{http://www.w3.org/2005/Atom}link"):
                if link.get("rel") == "next":
                    next_url = link.get("href")
                    break
            current_url = next_url
            pages_checked += 1
            print(f"ページ {pages_checked} を処理完了...")
        except Exception as e:
            print(f"データの取得中にエラーが発生しました: {e}")
            break

    print("\n==========================================")
    print("           ジャンル抽出結果のまとめ        ")
    print("==========================================")
    print(f"スキャンした記事数: {articles_scanned}")
    print(f"スキップした下書き数: {skipped_drafts}")
    print(f"検出されたユニークなジャンル数: {len(genres_counter)}")
    print("\n■ 出現頻度の高い順:")
    
    # 頻度順にソートして出力
    sorted_genres = genres_counter.most_common()
    for genre, count in sorted_genres:
        print(f"  - {genre}: {count}回")
        
    print("\n■ はてなブログでおすすめのカテゴリ設計:")
    # ジャンルをグループ化して提案
    categories_proposal = {
        "ロック・オルタナティブ系": ["インディーロック", "オルタナティブロック", "シューゲイザー", "ポストパンク", "マスロック", "ノイズポップ"],
        "ポップ・エレクトロ系": ["インディーポップ", "ドリームポップ", "シンセポップ", "エレクトロニカ", "シティポップ", "レトロポップ"],
        "アコースティック・シンガーソングライター系": ["フォーク", "アコースティック", "シンガーソングライター", "インディフォーク"],
        "R&B・ヒップホップ・ブラックミュージック系": ["R&B", "ソウル", "ヒップホップ", "ローファイヒップホップ"]
    }
    
    for group, items in categories_proposal.items():
        matched = [f"{item} ({genres_counter[item]}回)" for item in items if genres_counter[item] > 0]
        if matched:
            print(f"\n【{group}】")
            for m in matched:
                print(f"  - {m}")

if __name__ == "__main__":
    main()
