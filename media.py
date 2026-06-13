"""画像の解決(オプション)。

- 画像URL(http/https): 実行時にダウンロードして一時ファイルへ保存。
  楽天の商品画像は ?_ex=700x700 を付与して高解像度化する。
- リポジトリ内パス: そのまま返す。
- 取得失敗・不在はスキップ(None)し、呼び出し側はコメントのみで投稿を続行する。

画像が指定されたときだけ import される(post.py 側で遅延 import)。
"""
from __future__ import annotations

import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent

# 楽天の商品画像ドメイン(高解像度化の対象判定に使用)。
_RAKUTEN_IMAGE_HOSTS = ("thumbnail.image.rakuten.co.jp", "image.rakuten.co.jp")


def _highres_rakuten(url: str) -> str:
    """楽天の商品画像URLに ?_ex=700x700 を付与して高解像度化する。"""
    parsed = urlparse(url)
    if parsed.hostname and any(h in parsed.hostname for h in _RAKUTEN_IMAGE_HOSTS):
        if "_ex=" not in (parsed.query or ""):
            new_query = (parsed.query + "&" if parsed.query else "") + "_ex=700x700"
            return urlunparse(parsed._replace(query=new_query))
    return url


def _download(url: str) -> str | None:
    url = _highres_rakuten(url)
    try:
        suffix = Path(urlparse(url).path).suffix or ".jpg"
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 RoomPoster"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp, open(fd, "wb") as f:
            f.write(resp.read())
        return tmp
    except Exception as e:
        print(f"[warn] 画像DL失敗: {url} ({e})")
        return None


def resolve_images(specs: list[str] | None) -> list[str]:
    """画像指定(URL or ローカルパスの配列)を、実在するローカルパス配列に解決する。"""
    if not specs:
        return []
    resolved: list[str] = []
    for spec in specs:
        spec = spec.strip()
        if not spec:
            continue
        if spec.startswith("http://") or spec.startswith("https://"):
            path = _download(spec)
            if path:
                resolved.append(path)
        else:
            local = (ROOT / spec).resolve()
            if local.exists():
                resolved.append(str(local))
            else:
                print(f"[warn] 画像が存在しません(スキップ): {spec}")
    return resolved
