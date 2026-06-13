"""(ローカル用)手動ログインしてセッション(auth_state.json)を保存する。

ヘッドあり Chromium を起動するので、画面で楽天にログイン(2段階認証含む)し、
ROOM のマイページまで到達したらターミナルで Enter を押す。
その時点の storage_state を auth_state.json に保存する。

  python login.py
"""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "auth_state.json"

LOGIN_URL = "https://grp01.id.rakuten.co.jp/rms/nid/vc?service_id=top&return_url=https%3A%2F%2Froom.rakuten.co.jp%2F"


def main() -> int:
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False)
        except Exception:
            browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo")
        page = context.new_page()
        page.goto(LOGIN_URL)

        print("=" * 60)
        print("ブラウザで楽天にログインし、ROOM が表示されたら")
        print("このターミナルで Enter を押してください。")
        print("=" * 60)
        input()

        context.storage_state(path=str(OUT))
        print(f"[ok] {OUT} を保存しました。")
        context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
