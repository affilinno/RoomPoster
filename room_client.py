"""楽天ROOM「コレ!」投稿のコア(Playwright)。

- ブラウザ起動(自動化検知の緩和つき)
- ログイン判定
- 商品URL + コメント(+画像)での投稿

ROOM のUIに依存するため、セレクタは config.SELECTORS で集中管理し、
ここでは「候補を順に試す」ヘルパ経由で扱う。
"""
from __future__ import annotations

import random
import re
from contextlib import contextmanager
from urllib.parse import quote

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

import config


def to_collect_url(url: str) -> str:
    """入力をROOMのコレ直リンク(mix?itemcode=...)に正規化する。

    - ROOMのmix URL → そのまま
    - 楽天市場の商品URL(item.rakuten.co.jp/{shop}/{itemId}/) → itemCode 導出
    - それ以外 → itemCode そのものとみなす
    """
    u = (url or "").strip()
    # 既に mix/collect ならそのまま
    if "room.rakuten.co.jp/mix/collect" in u:
        return u
    # mix?itemcode= は真っ白対策で mix/collect?itemcode= に補正
    if "room.rakuten.co.jp/mix?" in u:
        return u.replace("/mix?", "/mix/collect?")
    m = re.search(r"item\.rakuten\.co\.jp/([^/]+)/([^/?#]+)", u)
    code = f"{m.group(1)}:{m.group(2)}" if m else u
    return f"https://room.rakuten.co.jp/mix/collect?itemcode={quote(code)}&scid=we_room_upc60"


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

        if config.MOBILE:
            ctx_kwargs = {
                "user_agent": config.MOBILE_UA,
                "viewport": {"width": 390, "height": 844},
                "is_mobile": True,
                "has_touch": True,
                "device_scale_factor": 3,
            }
        else:
            ctx_kwargs = {
                "user_agent": config.DESKTOP_UA,
                "viewport": {"width": 1280, "height": 900},
            }

        context = browser.new_context(
            storage_state=storage_state,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            **ctx_kwargs,
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


def _hide_overlays(page: Page) -> None:
    """クリックを遮るオーバーレイ(ヘッダーの div.background 等)を無効化する。"""
    try:
        page.evaluate(
            "() => { document.querySelectorAll('.background, .modal-backdrop, .overlay')"
            ".forEach(function(e){ e.style.display='none'; e.style.pointerEvents='none'; }); }"
        )
    except Exception:
        pass


def _exists(page: Page, selectors: list[str], timeout: int = 3000) -> bool:
    for sel in selectors:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=timeout)
            return True
        except PWTimeout:
            continue
    return False


def ensure_logged_in(page: Page) -> None:
    """ROOM のトップページを開いてログイン状態を確認する。未ログインなら例外。

    まず通常どおり https://room.rakuten.co.jp/ に入り、ページに埋め込まれた
    ログインユーザー情報(roomUser)で判定する。
    """
    page.goto(config.ROOM_BASE_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    url = page.url.lower()

    # ログイン画面へリダイレクトされていたら未ログイン。
    if any(p in url for p in config.LOGIN_URL_MARKERS):
        raise RuntimeError(
            "未ログイン状態です。Cookie(auth_state)が失効しています。"
            "import_cookies.py で取り直し、AUTH_STATE_B64 を更新してください。"
            f"(URL={page.url})"
        )

    # ページ内の roomUser からログイン済みユーザーを判定。
    content = page.content()
    if ('roomUser.isShortLogin = false' in content
            or '"type":"member"' in content
            or '"username"' in content):
        return

    # 断定できない場合(UI差異)。致命ではないが警告して続行。
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
    # 1) コレ直リンクを開く(コメント入力画面)。mix?itemcode= は mix/collect へ解決される。
    url = to_collect_url(url)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)  # AngularJS SPA の描画 + itemcode解決待ち

    # ログイン画面に飛ばされていないか念のため確認
    cur = page.url.lower()
    if any(p in cur for p in config.LOGIN_URL_MARKERS):
        raise RuntimeError(f"コレ画面でログイン画面へ遷移しました(未ログイン)。URL={page.url}")

    # クリックを遮るオーバーレイ(ヘッダーの div.background 等)を無効化。
    _hide_overlays(page)

    # 2) コメント欄が出ない=無効/販売終了などの商品。投稿せず例外で弾く。
    try:
        textarea = _first_visible(page, config.SELECTORS["comment_textarea"], timeout=8000)
    except PWTimeout:
        raise RuntimeError(
            f"コメント欄が見つかりません(無効/販売終了のitemcodeの可能性)。URL={page.url}"
        )

    # 3) コメント入力。実クリックで focus してから入力(AngularJSが確実に反応する方式)。
    try:
        textarea.click(timeout=5000)
    except Exception:
        _hide_overlays(page)
        textarea.click(force=True)
    textarea.fill(comment)

    # 4) 画像添付(任意)。ROOMは商品画像が自動。input が無ければスキップ(待たない)。
    if image_paths:
        file_inputs = page.locator(config.SELECTORS["file_input"][0])
        if file_inputs.count() > 0:
            try:
                file_inputs.first.set_input_files(image_paths)
                page.wait_for_timeout(2000)
            except Exception as e:
                print(f"[warn] 画像添付に失敗。コメントのみで投稿します: {e}")
        else:
            print("[info] 画像入力欄なし。コメントのみで投稿します。")

    # 5) 投稿ボタンの有効化(ng-disabled 解除)を待つ。
    post_button = _first_visible(page, config.SELECTORS["post_submit"])
    for _ in range(12):
        try:
            if not post_button.is_disabled():
                break
        except Exception:
            break
        page.wait_for_timeout(500)

    # 6) 実クリックで投稿(オーバーレイを消してから)。
    _hide_overlays(page)
    try:
        post_button.click(timeout=6000)
    except Exception:
        _hide_overlays(page)
        post_button.click(force=True, timeout=5000)

    # 7) 完了確認(再投稿を避けるため開き直さない。その場で判定)。
    #    成功するとコレ画面から遷移する/「この商品を削除」等が出るので、それで判定。
    page.wait_for_timeout(3000)
    if ("mix/collect" not in page.url.lower()
            or _exists(page, config.SELECTORS["post_done"], timeout=5000)):
        print("[ok] コレ完了を確認しました。")
    else:
        print("[info] 完了マーカー未確認(UI差異の可能性)。送信は実行済みの想定。")


def like_random_items(page: Page, count: int = 10) -> int:
    """フィード(items)でランダムに「スキ(いいね)」をつける。

    ROOMのブックマークレットの挙動を踏襲:
      - `.icon-like.right` のうち isLiked/isDisabled でないものが対象
      - 1クリックごとに 1〜2秒待機、0〜2件ランダムにスキップ
    投稿の付随処理なので、失敗しても例外にせず件数を返す(0=スキップ)。
    """
    if count <= 0:
        return 0
    try:
        sel = f"{config.LIKE_SELECTOR}:not(.isLiked):not(.isDisabled)"

        page.goto(config.FEED_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)  # SPA描画待ち

        # 初回ナビゲートで真っ白になることがあるので、ボタンが出なければリロード。
        for attempt in range(3):
            try:
                page.wait_for_selector(sel, timeout=6000)
                break
            except PWTimeout:
                print(f"[info] スキ対象が未描画。リロードします({attempt + 1}/3)。")
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

        # 対象を増やすため少しスクロール
        for _ in range(3):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1500)

        # ElementHandle で固定取得(クリックでclassが変わってもズレない)
        handles = page.query_selector_all(sel)
        if not handles:
            print("[warn] スキ対象が見つかりませんでした。スキはスキップします。")
            return 0

        liked = 0
        i = 0
        while liked < count and i < len(handles):
            h = handles[i]
            try:
                # ブックマークレットと同様 DOMのclickを発火(オーバーレイの影響を受けない)
                h.dispatch_event("click")
                liked += 1
                page.wait_for_timeout(random.randint(1000, 2000))  # 1〜2秒待機
            except Exception:
                pass
            i += 1 + random.randint(0, 2)  # 0〜2件スキップ
        print(f"[ok] スキを {liked} 件つけました。")
        return liked
    except Exception as e:
        print(f"[warn] スキ処理でエラー(無視): {e}")
        return 0
