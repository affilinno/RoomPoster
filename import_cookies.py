"""(ローカル用)通常ブラウザの楽天Cookieから auth_state.json を生成する。

楽天は X の auth_token/ct0 のような単一トークンではなく、複数の認証Cookieで
ログイン状態を保持する。確実なのは「ログイン済みブラウザのCookieをまるごと
エクスポートする」方法。

--- 手順(クッキーでログイン)---
 1. 普段のブラウザで楽天(https://room.rakuten.co.jp/)にログインしておく。
 2. Cookie拡張で楽天のCookieをJSONエクスポートする。
    例) Chrome拡張「Cookie-Editor」: room.rakuten.co.jp を開く →
        拡張アイコン → Export → "Export as JSON"(クリップボードにJSON)。
        ※「EditThisCookie」など他拡張のJSONでも可。
 3. その内容を cookies.json として保存し、本スクリプトに渡す:
        python import_cookies.py --cookies-file cookies.json
    既定では楽天ドメイン(domainに "rakuten" を含む)のCookieだけ取り込む。
 4. 生成された auth_state.json でログインできるか確認(任意):
        python import_cookies.py --cookies-file cookies.json --verify
 5. GitHub Secret 用に base64 を出力:
        python import_cookies.py --cookies-file cookies.json --base64

生成物: auth_state.json(Playwright storage_state 形式)。
これを base64 化して GitHub Secret AUTH_STATE_B64 に登録する。

※ Cookie-Editor で1サイトずつしか出せない場合は、必要なら
  grp01.id.rakuten.co.jp など複数ドメイン分を結合して1つのJSON配列にする。
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "auth_state.json"

# ブラウザ拡張の sameSite 表記 → Playwright 表記。
_SAMESITE_MAP = {
    "no_restriction": "None",
    "none": "None",
    "lax": "Lax",
    "strict": "Strict",
    "unspecified": "Lax",
    "": "Lax",
}


def _normalize(cookie: dict) -> dict | None:
    """ブラウザ拡張形式の Cookie を Playwright storage_state 形式へ寄せる。

    name/value が無いものは None を返してスキップする。
    """
    name = cookie.get("name")
    value = cookie.get("value")
    if not name or value is None:
        return None

    same_site = _SAMESITE_MAP.get(str(cookie.get("sameSite", "")).lower(), "Lax")
    secure = bool(cookie.get("secure", True))
    # Playwright は sameSite=None のとき secure=True を要求する。
    if same_site == "None":
        secure = True

    out = {
        "name": name,
        "value": value,
        "domain": cookie.get("domain", ".rakuten.co.jp"),
        "path": cookie.get("path", "/"),
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "secure": secure,
        "sameSite": same_site,
    }
    # expires(任意)。無ければセッションCookie扱い(-1)。
    exp = cookie.get("expirationDate") or cookie.get("expires")
    try:
        out["expires"] = float(exp) if exp else -1
    except (TypeError, ValueError):
        out["expires"] = -1
    return out


def _verify() -> int:
    """生成した auth_state.json でROOMにログインできるか確認する。"""
    try:
        from room_client import browser_page, ensure_logged_in
    except Exception as e:  # playwright 未導入など
        print(f"[warn] 確認をスキップ(依存未導入?): {e}")
        return 0
    try:
        with browser_page() as page:
            ensure_logged_in(page)
        print("[ok] ログイン状態を確認できました。")
        return 0
    except Exception as e:
        print(f"[error] ログイン確認に失敗: {e}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="楽天CookieからPlaywrightセッションを生成")
    parser.add_argument(
        "--cookies-file",
        required=True,
        help="ブラウザ拡張でエクスポートしたCookieのJSONファイル",
    )
    parser.add_argument(
        "--domain-filter",
        default="rakuten",
        help="この文字列を domain に含むCookieだけ取り込む(既定: rakuten)",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="ドメインで絞り込まず全Cookieを取り込む",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="生成後、実際にROOMへログインできるか確認する(Playwright必要)",
    )
    parser.add_argument(
        "--base64",
        action="store_true",
        help="生成後、GitHub Secret 用に auth_state.json のbase64を出力する",
    )
    args = parser.parse_args()

    raw = json.loads(Path(args.cookies_file).read_text(encoding="utf-8"))
    # Cookie-Editor は配列、拡張によっては {"cookies":[...]} の場合もある。
    if isinstance(raw, dict) and "cookies" in raw:
        raw = raw["cookies"]

    cookies = []
    skipped = 0
    for c in raw:
        if not args.no_filter and args.domain_filter not in str(c.get("domain", "")):
            continue
        norm = _normalize(c)
        if norm is None:
            skipped += 1
            continue
        cookies.append(norm)

    if not cookies:
        print("[error] 取り込めるCookieがありません。"
              "--no-filter を試すか、エクスポート内容を確認してください。")
        return 2

    storage_state = {"cookies": cookies, "origins": []}
    OUT.write_text(
        json.dumps(storage_state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[ok] {OUT} を生成しました(取り込み={len(cookies)} / スキップ={skipped})。")

    rc = 0
    if args.verify:
        rc = _verify()

    if args.base64:
        b64 = base64.b64encode(OUT.read_bytes()).decode()
        print("\n--- AUTH_STATE_B64(GitHub Secret に貼り付け)---")
        print(b64)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
