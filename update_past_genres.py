import urllib.request
import base64
import xml.etree.ElementTree as ET
import re
import argparse
import os

# 許可されたジャンル一覧（固定小分類カテゴリ）
ALLOWED_GENRES = [
    "インディーロック", "オルタナティブロック", "シューゲイザー", "ポストパンク", "マスロック", "ノイズポップ",
    "インディーポップ", "ドリームポップ", "シンセポップ", "エレクトロニカ", "シティポップ", "レトロポップ",
    "フォーク", "アコースティック", "シンガーソングライター", "インディフォーク",
    "R&B", "ソウル", "ヒップホップ", "ローファイヒップホップ"
]

def parse_args():
    parser = argparse.ArgumentParser(description="はてなブログの過去記事にジャンル小分類カテゴリを自動付与するスクリプト")
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
        help="遡って確認する最大ページ数 (デフォルト: 15)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際に更新せず、更新予定の内容を表示する"
    )
    return parser.parse_args()

def main():
    args = parse_args()
    
    url = f"https://blog.hatena.ne.jp/{args.hatena_id}/{args.hatena_blog_id}/atom/entry"
    auth_str = f"{args.hatena_id}:{args.hatena_api_key}"
    auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f"Basic {auth_b64}",
        'Content-Type': 'application/xml; charset=utf-8',
        'User-Agent': 'GenreUpdater/1.0'
    }
    
    # XML名前空間の登録
    ET.register_namespace('', 'http://www.w3.org/2005/Atom')
    ET.register_namespace('app', 'http://www.w3.org/2007/app')
    ET.register_namespace('hatenablog', 'http://www.hatena.ne.jp/info/xmlns#hatenablog')
    
    current_url = url
    pages_checked = 0
    updated_count = 0
    checked_count = 0
    
    print(f"■ 開始: 過去記事のカテゴリ更新プログラム")
    print(f"対象ブログ: {args.hatena_blog_id}")
    if args.dry_run:
        print("※テストモード (DRY RUN) で実行中。実際には更新されません。")
    print("------------------------------------------")
    
    while current_url and pages_checked < args.max_pages:
        try:
            req = urllib.request.Request(current_url, headers={
                'Authorization': f"Basic {auth_b64}",
                'User-Agent': 'GenreUpdater/1.0'
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
                
                # 記事本文の取得
                content_el = entry.find("{http://www.w3.org/2005/Atom}content")
                if content_el is None or not content_el.text:
                    continue
                
                content = content_el.text
                
                # 本文から「* **ジャンル**: シューゲイザー、ドリームポップ」などを抽出
                match = re.search(r'\*\s*\*\*ジャンル\*\*:\s*(.*)', content)
                if not match:
                    continue
                    
                genres_str = match.group(1).strip()
                genres = [g.strip() for g in re.split(r'[、,，]', genres_str) if g.strip()]
                if not genres:
                    continue
                
                # 現在のカテゴリを取得
                current_cats = [cat.get("term") for cat in entry.findall("{http://www.w3.org/2005/Atom}category") if cat.get("term")]
                
                # 許可されたジャンルリストと照らし合わせてフィルタリング
                assigned_genres = []
                for g in genres:
                    matched = None
                    for allowed in ALLOWED_GENRES:
                        if g.lower() == allowed.lower():
                            matched = allowed
                            break
                    if matched and matched not in assigned_genres:
                        assigned_genres.append(matched)
                
                # 1つも該当しなければ「不明」にする
                if not assigned_genres:
                    assigned_genres = ["不明"]
                
                # 追加すべきジャンルを特定
                missing_genres = [g for g in assigned_genres if g not in current_cats]
                if not missing_genres:
                    continue
                    
                print(f"【要更新】記事: 「{title}」")
                print(f"  - 現在のカテゴリ: {current_cats}")
                print(f"  - 追加するジャンル: {missing_genres}")
                
                # 新しいカテゴリ要素を追加
                for new_g in missing_genres:
                    cat_el = ET.Element("{http://www.w3.org/2005/Atom}category", term=new_g)
                    entry.append(cat_el)
                
                # 更新されたカテゴリ
                all_cats = current_cats + missing_genres
                
                # Edit URL (Member URI) の取得
                edit_url = None
                for link in entry.findall("{http://www.w3.org/2005/Atom}link"):
                    if link.get("rel") == "edit":
                        edit_url = link.get("href")
                        break
                        
                if not edit_url:
                    print("  -> エラー: 編集用URL(edit link)が見つかりません。")
                    continue
                    
                if not args.dry_run:
                    try:
                        # XML文字列へシリアライズ
                        updated_xml = ET.tostring(entry, encoding='utf-8')
                        
                        # PUTリクエストの送信
                        put_req = urllib.request.Request(edit_url, data=updated_xml, headers=headers, method='PUT')
                        with urllib.request.urlopen(put_req, timeout=10) as put_resp:
                            put_resp.read()
                        print(f"  -> 更新完了！ 新カテゴリ: {all_cats}")
                    except Exception as e:
                        print(f"  -> エラー: API更新に失敗しました: {e}")
                else:
                    print(f"  -> [DRY RUN] 更新後のカテゴリ構成: {all_cats}")
                    
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
    print(f"更新が必要だった記事数: {updated_count}")

if __name__ == "__main__":
    main()
