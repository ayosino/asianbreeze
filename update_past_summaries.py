import urllib.request
import base64
import xml.etree.ElementTree as ET
import re
import argparse
import os
import sys

# SDK検出
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

def parse_args():
    parser = argparse.ArgumentParser(description="はてなブログの過去記事の概要（元記事の概要）を2行以内に自動要約・更新するスクリプト")
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
        "--api-key",
        default=os.environ.get("GEMINI_API_KEY"),
        help="Gemini APIキー (指定しない場合は環境変数 GEMINI_API_KEY を使用)"
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
        help="実際に更新せず、要約予定の内容を表示する"
    )
    return parser.parse_args()

def summarize_text_to_two_lines(api_key: str, text: str) -> str:
    """Gemini APIを使用してテキストを2行以内に要約する"""
    prompt = (
        "以下の文章はブログの「元記事の概要」セクションです。著作権保護に配慮し、"
        "この記事がどのような意図・文脈で公開されたものなのかを、簡潔に2行以内の日本語（改行を含めて最大2行、です・ます調）で要約してください。\n"
        "余計な前置きや説明は含めず、要約された2行のテキストのみを返してください。\n\n"
        f"元の文章:\n{text}\n"
    )
    model_name = 'gemini-2.5-flash' if HAS_NEW_SDK else 'gemini-1.5-flash'
    
    if HAS_NEW_SDK:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return resp.text.strip()
    else:
        genai_legacy.configure(api_key=api_key)
        model = genai_legacy.GenerativeModel(model_name)
        resp = model.generate_content(prompt)
        return resp.text.strip()

def main():
    args = parse_args()
    
    gemini_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("エラー: Gemini APIキーが指定されていません。--api-key引数か環境変数 GEMINI_API_KEY を設定してください。")
        sys.exit(1)
        
    url = f"https://blog.hatena.ne.jp/{args.hatena_id}/{args.hatena_blog_id}/atom/entry"
    auth_str = f"{args.hatena_id}:{args.hatena_api_key}"
    auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f"Basic {auth_b64}",
        'Content-Type': 'application/xml; charset=utf-8',
        'User-Agent': 'SummaryUpdater/1.0'
    }
    
    # XML名前空間の登録
    ET.register_namespace('', 'http://www.w3.org/2005/Atom')
    ET.register_namespace('app', 'http://www.w3.org/2007/app')
    ET.register_namespace('hatenablog', 'http://www.hatena.ne.jp/info/xmlns#hatenablog')
    
    current_url = url
    pages_checked = 0
    updated_count = 0
    checked_count = 0
    
    print(f"■ 開始: 過去記事の「元記事の概要」2行要約アップデート")
    print(f"対象ブログ: {args.hatena_blog_id}")
    if args.dry_run:
        print("※テストモード (DRY RUN) で実行中。実際には更新されません。")
    print("------------------------------------------")
    
    while current_url and pages_checked < args.max_pages:
        try:
            req = urllib.request.Request(current_url, headers={
                'Authorization': f"Basic {auth_b64}",
                'User-Agent': 'SummaryUpdater/1.0'
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
                
                # 「### 元記事の概要\n(文章)\n\n---」の部分を抽出
                match = re.search(r'(### 元記事の概要\s*\n)(.*?)(\n\s*---)', content, re.DOTALL)
                if not match:
                    continue
                    
                original_summary = match.group(2).strip()
                
                # 既に2行以内でかつ短い場合はスキップ判定（文字数120字未満かつ改行数が1以下）
                lines_count = original_summary.count('\n') + 1
                if lines_count <= 2 and len(original_summary) < 120:
                    continue
                    
                print(f"【要更新】記事: 「{title}」")
                print(f"  - 元の概要 ({lines_count}行):\n{original_summary}")
                
                try:
                    # Geminiで2行に要約
                    new_summary = summarize_text_to_two_lines(gemini_key, original_summary)
                    print(f"  - 新しい概要 (要約後):\n{new_summary}")
                    
                    # 本文内の概要を置き換え
                    # マッチした部分全体の置き換え
                    # match.group(1) は '### 元記事の概要\n', match.group(3) は '\n\n---'
                    replacement_text = f"{match.group(1)}{new_summary}{match.group(3)}"
                    new_content = content.replace(match.group(0), replacement_text)
                    
                    # XML要素のテキストを更新
                    content_el.text = new_content
                except Exception as e:
                    print(f"  -> 要約生成エラー: {e}")
                    continue
                
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
    print(f"要約を更新した記事数: {updated_count}")

if __name__ == "__main__":
    main()
