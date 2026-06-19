"""設定とセッション解決。

- 認証セッション(Cookie)は、環境変数 AUTH_STATE_B64 があればそれを優先し、
  無ければローカルの auth_state.json を使う。
- 楽天ROOMの各URL・フォームのセレクタはここで集中管理する。
  ※ ROOM のWeb UI 変更に弱い箇所なので、壊れたらまずここを直す。
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

# --- パス -------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
AUTH_STATE_FILE = ROOT / "auth_state.json"
# 環境変数からCookieを復元するときの実体ファイル(.gitignore 済み)
RUNTIME_AUTH_STATE_FILE = ROOT / ".auth_state.runtime.json"
SCHEDULE_FILE = ROOT / "schedule.json"

# --- 実行設定 ---------------------------------------------------------------

# HEADLESS=0 で画面ありデバッグ。既定はヘッドレス。
HEADLESS = os.environ.get("HEADLESS", "1") != "0"

# ROOM_MOBILE=1 でモバイルUA・モバイル表示で動かす。
# ROOMの「コレ」投稿画面はモバイル向けで、デスクトップUAだと描画されない場合がある。
MOBILE = os.environ.get("ROOM_MOBILE", "0") != "0"

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.5 Mobile/15E148 Safari/604.1"
)

# 連投検知回避のため、同一実行で複数投稿する際の最小/最大待機秒数。
MIN_GAP_SEC = int(os.environ.get("MIN_GAP_SEC", "30"))
MAX_GAP_SEC = int(os.environ.get("MAX_GAP_SEC", "90"))

# 投稿のついでにフィードでランダムに「スキ(いいね)」する件数。0で無効。
LIKE_COUNT = int(os.environ.get("ROOM_LIKE_COUNT", "10"))
# スキを回すフィードURL(アイテム一覧)。
FEED_URL = os.environ.get("ROOM_FEED_URL", "https://room.rakuten.co.jp/items")
# スキ(いいね)ボタンのセレクタ。isLiked/isDisabled は除外する。
LIKE_SELECTOR = os.environ.get("ROOM_LIKE_SELECTOR", ".icon-like.right")

# 1要素あたりの待機タイムアウト(ミリ秒)。
DEFAULT_TIMEOUT_MS = int(os.environ.get("DEFAULT_TIMEOUT_MS", "30000"))

# --- 楽天ROOM URL -----------------------------------------------------------

ROOM_BASE_URL = "https://room.rakuten.co.jp/"
# 「コレ!」(商品をROOMに収集)を開始する画面。
# 環境により導線が異なるため ROOM_COLLECT_URL で上書き可能。
COLLECT_URL = os.environ.get(
    "ROOM_COLLECT_URL",
    "https://room.rakuten.co.jp/items/select",
)
# ログイン状態の判定に使うURL(マイページ。ログイン必須)。
MYPAGE_URL = "https://room.rakuten.co.jp/myprofile"

# このいずれかがURLに含まれていたら「ログイン画面へリダイレクトされた=未ログイン」。
LOGIN_URL_MARKERS = [
    "login.account.rakuten.com",
    "grp01.id.rakuten.co.jp",
    "id.rakuten.co.jp",
    "/login",
]

# --- セレクタ ----------------------------------------------------------------
# ※ ROOM のUIに合わせて要確認・調整。複数候補をカンマ区切りで持ち、
#   先に見つかったものを使う(room_client.py 側で順に試行)。

SELECTORS = {
    # ログイン済みかどうかの判定に使う「ログイン後だけ存在する」要素。
    "logged_in_marker": [
        "a[href*='/myprofile']",
        "[data-testid='user-menu']",
        "img.user-icon",
    ],
    # ログイン画面に飛ばされたことを示す要素(未ログイン判定)。
    "login_marker": [
        "input#loginInner_u",
        "input[name='u']",
        "form[action*='login']",
    ],
    # コメント(感想)入力欄。mix/collect の実DOMより。
    "comment_textarea": [
        "#collect-content",
        "textarea[name='content']",
        "textarea[ng-model='$parent.content']",
    ],
    # 画像添付の input[type=file](ROOMは商品画像が自動。原則未使用)。
    "file_input": [
        "input[type='file']",
    ],
    # 投稿(コレ!する)実行ボタン。ng-click=collect()。
    "post_submit": [
        "button.collect-btn",
        "button[ng-click='collect()']",
    ],
    # 投稿完了を示す要素(収集後に「この商品を削除」リンクが出る)。
    "post_done": [
        "a[ng-click='deleteCollect()']",
        ".delete-button",
        "text=コレしました",
    ],
}


def resolve_storage_state() -> str:
    """Playwright に渡す storage_state ファイルのパスを返す。

    AUTH_STATE_B64 があれば復号して .auth_state.runtime.json に書き出す。
    無ければローカル auth_state.json を使う。
    """
    b64 = os.environ.get("AUTH_STATE_B64")
    if b64:
        raw = base64.b64decode(b64)
        RUNTIME_AUTH_STATE_FILE.write_bytes(raw)
        return str(RUNTIME_AUTH_STATE_FILE)

    if AUTH_STATE_FILE.exists():
        return str(AUTH_STATE_FILE)

    raise FileNotFoundError(
        "認証セッションが見つかりません。AUTH_STATE_B64 を設定するか、"
        "import_cookies.py で auth_state.json を生成してください。"
    )


def load_schedule() -> list[dict]:
    if not SCHEDULE_FILE.exists():
        return []
    return json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))


def save_schedule(entries: list[dict]) -> None:
    SCHEDULE_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
