"""楽天ROOM「コレ!」投稿のコア(Playwright)。

- ブラウザ起動(自動化検知の緩和つき)
- ログイン判定
- 商品URL + コメント(+画像)での投稿

ROOM のUIに依存するため、セレクタは config.SELECTORS で集中管理し、
ここでは「候補を順に試す」ヘルパ経由で扱う。
"""
from __future__ import annotations

from contextlib import contextmanager

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

import config


# --- 自動化検知の緩和スクリプト ----------------------------------------------
# navigator.webdriver を隠し、自動化フラグの痕跡を減らす。
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP', 'ja']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || {runtime: {}};
"""


@contextmanager
def browser_page():
    """ログイン済みCookieを読み込んだ Page を返すコンテキストマネージャ。"""
    storage_state = config.resolve_storage_state()
    with sync_playwright() as p:
        launch_kwargs = {
            "headless": config.HEADLESS,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }
        # 実Chromeがあれば優先(検知緩和)。無ければ同梱Chromium。
        try:
            browser = p.chromium.launch(channel="chrome", **launch_kwargs)
        except Exception:
            browser = p.chromium.launch(**launch_kwargs)

        context = browser.new_context(
            storage_state=storage_state,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        context.add_init_script(STEALTH_JS)
        context.set_default_timeout(config.DEFAULT_TIMEOUT_MS)

        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


def _first_visible(page: Page, selectors: list[str], timeout: int = 5000):
    """候補セレクタを順に試し、最初に見つかった可視要素の Locator を返す。"""
    last_err = None
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except PWTimeout as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    raise RuntimeError(f"要素が見つかりません: {selectors}")


def _exists(page: Page, selectors: list[str], timeout: int = 3000) -> bool:
    for sel in selectors:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=timeout)
            return True
        except PWTimeout:
            continue
    return False


def ensure_logged_in(page: Page) -> None:
    """ROOM を開いてログイン状態を確認する。未ログインなら例外。

    判定は URL ベースを主とする(myprofile はログイン必須ページなので、
    未ログインだと楽天は必ずログイン画面へリダイレクトする)。
    セレクタ判定は補助。
    """
    page.goto(config.MYPAGE_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)  # リダイレクト確定待ち
    url = page.url.lower()

    # 未ログイン: ログイン系ドメイン/パスへ飛ばされている、またはログインフォームあり
    if any(p in url for p in config.LOGIN_URL_MARKERS) or _exists(
        page, config.SELECTORS["login_marker"], timeout=2000
    ):
        raise RuntimeError(
            "未ログイン状態です。Cookie(auth_state)が失効しています。"
            "import_cookies.py で取り直し、AUTH_STATE_B64 を更新してください。"
            f"(URL={page.url})"
        )

    # ログイン済み: myprofile に留まっている、または肯定マーカーが取れた
    if "myprofile" in url or _exists(page, config.SELECTORS["logged_in_marker"], timeout=4000):
        return

    # どちらとも言い切れない(UI差異)。致命ではないが警告。
    print(f"[warn] ログイン状態を断定できませんでした(URL={page.url})。続行します。")


def post_collect(
    page: Page,
    *,
    url: str,
    comment: str,
    image_paths: list[str] | None = None,
) -> None:
    """ROOMのコレ直リンク(mix/collect?itemcode=...)を開いて「コレ!」投稿する。

    url        : ROOMのコレ直リンク(GAS側で itemcode を解決済み)
    comment    : コメント本文(改行可)
    image_paths: 添付する画像のローカルパス(任意)
    """
    # 1) コレ直リンクを開く(コメント入力画面)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)  # AngularJS SPA の描画待ち

    # ログイン画面に飛ばされていないか念のため確認
    cur = page.url.lower()
    if any(p in cur for p in config.LOGIN_URL_MARKERS):
        raise RuntimeError(f"コレ画面でログイン画面へ遷移しました(未ログイン)。URL={page.url}")

    # 2) コメント入力
    textarea = _first_visible(page, config.SELECTORS["comment_textarea"])
    textarea.click()
    textarea.fill(comment)

    # 3) 画像添付(任意)
    if image_paths:
        try:
            file_input = page.locator(config.SELECTORS["file_input"][0])
            file_input.set_input_files(image_paths)
            page.wait_for_timeout(2000)  # アップロード反映待ち
        except Exception as e:  # 画像失敗で投稿全体を落とさない
            print(f"[warn] 画像添付に失敗。コメントのみで投稿します: {e}")

    # 4) 投稿実行
    post_button = _first_visible(page, config.SELECTORS["post_submit"])
    post_button.click()

    # 5) 完了確認(取れなくても致命ではない)
    if _exists(page, config.SELECTORS["post_done"], timeout=8000):
        print("[ok] 投稿完了を確認しました。")
    else:
        print("[info] 完了マーカー未確認(UI差異の可能性)。投稿は送信済みの想定。")
