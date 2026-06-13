# RoomPoster セットアップ手順

楽天ROOMに Playwright で自動「コレ!」投稿するツールのセットアップ手順。
仕様は `specificationRoom.md` を参照。

## 0. 全体像

```
[GAS] 商品・コメント生成 → workflow_dispatch
   ▼
[GitHub Actions: post.yml] → Playwright
   ▼
[楽天ROOM] 「コレ!」投稿
```

3つの起動経路:
- **予約**: `schedule.json` に時刻つきで列挙(15分おきのcronが処理)
- **手動**: GitHub の Run workflow から `url`/`comment`/`image` を入力
- **GAS**: 時間トリガーで自動(ランダム投稿は `AffiliRoomPost.gs`)

---

## 1. ローカル準備

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## 2. ログインCookieの取得 → auth_state.json

楽天は複数Cookieでログイン状態を保持するため、**ログイン済みブラウザの
クッキーを取り込む**方式を使う(サーバー側ではログイン操作をしない=ボット検知対策)。

### 2-1. クッキーでログイン(推奨)

1. 普段のブラウザで楽天(https://room.rakuten.co.jp/)に**ログイン済み**にしておく。
2. Cookie拡張で楽天のクッキーをJSONエクスポートする。
   - 例) Chrome拡張 **「Cookie-Editor」**: `room.rakuten.co.jp` を開く →
     拡張アイコン → **Export** → **Export as JSON**(クリップボードにコピーされる)。
   - 「EditThisCookie」など他拡張のJSONでも可。
3. コピーした内容を `cookies.json` として保存(プロジェクト直下)。
4. 取り込み → `auth_state.json` を生成:

   ```bash
   python import_cookies.py --cookies-file cookies.json
   ```

   既定で「domainに `rakuten` を含むクッキー」だけ取り込む。
   うまくログインできない場合は、`grp01.id.rakuten.co.jp` など複数ドメインの
   クッキーもエクスポートして1つのJSON配列にまとめる(または `--no-filter`)。
5. ログインできるか確認(任意・Playwrightで実際にROOMを開く):

   ```bash
   python import_cookies.py --cookies-file cookies.json --verify
   ```

   `[ok] ログイン状態を確認できました。` が出れば成功。

> **補足(対話ログインでも可)**: 拡張を使わず `python login.py` で
> ヘッドありChromiumを開き、楽天にログイン→ROOM表示後にターミナルで Enter
> しても `auth_state.json` を作れる。

### 2-2. 注意

- `auth_state.json` / `cookies.json` はパスワード級。`.gitignore` 済み。共有・コミット禁止。

### ローカル動作確認(任意)

```bash
# 画面ありで単発投稿テスト
HEADLESS=0 python post.py --url "https://item.rakuten.co.jp/xxx/yyy/" --comment "テスト投稿"
```

> 楽天ROOMのUIに合わせて `config.py` の `SELECTORS` を調整する必要がある場合がある
> (投稿フォーム・商品URL入力欄・投稿ボタン等)。最初は `HEADLESS=0` で挙動を確認する。

## 3. GitHub リポジトリ設定

1. このプロジェクトを GitHub リポジトリにpush。
2. **Settings > Secrets and variables > Actions** に Secret を追加:
   - `AUTH_STATE_B64` = `auth_state.json` を base64化した文字列

   base64文字列は次で出力できる:

   ```bash
   python import_cookies.py --cookies-file cookies.json --base64
   # もしくは既存の auth_state.json から:
   python -c "import base64,pathlib;print(base64.b64encode(pathlib.Path('auth_state.json').read_bytes()).decode())"
   ```

3. **Settings > Actions > General > Workflow permissions** を
   **Read and write permissions** に設定(schedule.json のコミットに必要)。

## 4. 投稿のしかた

### A) 予約投稿
`schedule.json` を編集してpush。15分おきのcronが `time <= 現在(JST)` かつ
`posted=false` のものを投稿し、`posted=true` を書き戻す。

### B) 手動投稿
GitHub の **Actions > Post to Rakuten ROOM > Run workflow** で
`url` / `comment` / `image` を入力して実行。

### C) GAS自動投稿
`gas/README.md` を参照。`AffiliRoomPost.gs` の `postRandomDealToRoom` を
時間トリガーに設定すると、ランダムなジャンルのお得商品をAI紹介文つきで自動投稿。

## 5. メンテナンス

- **Cookie失効**: ジョブが「未ログイン」で失敗したら、手順2でCookieを取り直し、
  手順3のSecret `AUTH_STATE_B64` を更新する(主な保守作業)。
- **UI変更**: 楽天ROOMのUIが変わってセレクタが効かなくなったら
  `config.py` の `SELECTORS` を修正する。

## 6. 注意

- API非経由の自動投稿は楽天の規約上グレー。自分のアカウントで常識的な頻度に
  限定する(過度な自動化はアカウント制限・凍結のリスク)。
- 認証Cookieはパスワード級。`auth_state.json` は `.gitignore` 済み。絶対にコミット・
  共有しない。
