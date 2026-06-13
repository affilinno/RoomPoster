"""実行エントリ。

2モード:
  1) 予約キュー処理(引数なし): schedule.json の中で time<=now かつ posted=false を投稿。
  2) 単発投稿: --url と --comment を渡して即時投稿(schedule.json は触らない)。

例:
  python post.py
  python post.py --url "https://item.rakuten.co.jp/shop/xxxx/" \
                 --comment "毎日使えるおすすめ!\nリピ確定です" \
                 --image "https://thumbnail.image.rakuten.co.jp/.../x.jpg"
"""
from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
import time

import config
from room_client import browser_page, ensure_logged_in, post_collect

JST = dt.timezone(dt.timedelta(hours=9))


def _unescape_newlines(text: str) -> str:
    """Actions の1行入力欄向け。リテラル \\n を実改行へ変換。"""
    return text.replace("\\n", "\n")


def _parse_time(value: str) -> dt.datetime:
    """ISO 8601。タイムゾーン無指定は JST 扱い。"""
    d = dt.datetime.fromisoformat(value)
    if d.tzinfo is None:
        d = d.replace(tzinfo=JST)
    return d


def _resolve_images(specs):
    if not specs:
        return []
    from media import resolve_images  # 画像指定時のみ読み込む

    return resolve_images(specs)


def run_single(url: str, comment: str, images: list[str] | None) -> None:
    comment = _unescape_newlines(comment)
    image_paths = _resolve_images(images)
    with browser_page() as page:
        ensure_logged_in(page)
        post_collect(page, url=url, comment=comment, image_paths=image_paths)
    print("[done] 単発投稿を実行しました。")


def run_schedule() -> None:
    entries = config.load_schedule()
    now = dt.datetime.now(JST)
    due = [
        e
        for e in entries
        if not e.get("posted") and _parse_time(e["time"]) <= now
    ]
    if not due:
        print("[info] 投稿対象(time<=now かつ posted=false)はありません。")
        return

    posted_any = False
    with browser_page() as page:
        ensure_logged_in(page)
        for i, entry in enumerate(due):
            if i > 0:
                gap = random.randint(config.MIN_GAP_SEC, config.MAX_GAP_SEC)
                print(f"[info] 連投回避のため {gap}s 待機します。")
                time.sleep(gap)
            comment = _unescape_newlines(entry.get("comment", ""))
            images = _resolve_images(entry.get("image") and [entry["image"]]
                                     or entry.get("images"))
            try:
                post_collect(
                    page,
                    url=entry["url"],
                    comment=comment,
                    image_paths=images,
                )
                entry["posted"] = True
                entry["posted_at"] = dt.datetime.now(JST).isoformat()
                posted_any = True
                print(f"[ok] 投稿: {entry['url']}")
            except Exception as e:
                print(f"[error] 投稿失敗(スキップ): {entry.get('url')} -> {e}")

    if posted_any:
        config.save_schedule(entries)
        print("[done] schedule.json を更新しました。")


def main() -> int:
    parser = argparse.ArgumentParser(description="楽天ROOM 投稿ツール")
    parser.add_argument("--url", help="楽天市場の商品URL(単発投稿)")
    parser.add_argument("--comment", help="コメント本文(単発投稿)")
    parser.add_argument(
        "--image",
        action="append",
        help="画像URL または リポジトリ内パス(複数指定可)",
    )
    args = parser.parse_args()

    if args.url:
        if not args.comment:
            print("[error] --url 指定時は --comment も必要です。", file=sys.stderr)
            return 2
        run_single(args.url, args.comment, args.image)
    else:
        run_schedule()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
