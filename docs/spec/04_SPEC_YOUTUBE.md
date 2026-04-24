# SPEC_YOUTUBE.md — YouTube Data API v3 / OAuth2 連携モジュール仕様書

バージョン: 1.1.0
作成日: 2026-04-24
対応 Issue: #4
ステータス: 仕様確定 v1.1.0（実装未着手）

---

## 概要

OBS録画で生成したMP4ファイルを YouTube Data API v3 を通じて自動アップロードするモジュール（`youtube_uploader.py`）の仕様を定義する。OAuth2認証フロー・動画アップロード・サムネイルセット・進捗通知を担当する。コントローラー（`app.py`）から呼び出され、YouTube以外の処理には関与しない。

---

## 機能仕様

- OAuth2認証（初回ブラウザフロー・2回目以降リフレッシュトークン自動更新）を行う
- 認証後、指定のMP4ファイルを YouTube にアップロードする
- アップロード時にタイトル・説明文・カテゴリ・タグ・公開設定を自動セットする
- タイトルは礼拝情報（日付・タイトル・聖書箇所・説教者）から規則に従って生成する
- アップロード後、別 API でサムネイル画像をセットする
- Resumable Upload を使用し、大容量MP4（1GB超）に対応する
- アップロード進捗（0〜100%）をコールバック関数で通知する（GUIのプログレスバーに反映）
- 認証失敗・クォータ超過・ネットワーク断などのエラーは例外として呼び出し元に伝播させる

---

## インターフェース定義

### モジュール構成

```
youtube_uploader.py
```

### 1. 認証

```python
def authenticate(credentials_path: str, token_path: str) -> googleapiclient.discovery.Resource:
```

- `credentials_path`: Google Cloud Console からダウンロードした credentials.json のパス
- `token_path`: トークンを保存・読み込みするファイルのパス（token.json）
- 戻り値: 認証済みの YouTube API サービスオブジェクト
- 例外: `FileNotFoundError`（credentials_path が存在しない場合）、`AuthenticationError`（ブラウザ認証キャンセル）

### 2. 動画アップロード

```python
def upload_video(
    service: googleapiclient.discovery.Resource,
    video_path: str,
    title: str,
    description: str,
    thumbnail_path: str | None,
    privacy: str,
    progress_callback: Callable[[int], None] | None = None,
) -> dict:
```

- `service`: authenticate() で取得した認証済みサービスオブジェクト
- `video_path`: アップロードするMP4ファイルのパス
- `title`: YouTube 動画タイトル（build_title() で生成した文字列を渡す）
- `description`: YouTube 動画説明文（build_description() で生成した文字列を渡す）
- `thumbnail_path`: サムネイル画像ファイルのパス。None の場合はサムネイル設定を省略する
- `privacy`: 公開設定。"public"（公開）または "unlisted"（限定公開）
- `progress_callback`: アップロード進捗を 0〜100 の整数で受け取るコールバック関数。None の場合は通知しない
- 戻り値: アップロード後の情報を格納した辞書
  - `video_id` (str): YouTube 動画ID（例: `"dQw4w9WgXcQ"`）
  - `video_url` (str): YouTube 動画URL（例: `"https://youtu.be/dQw4w9WgXcQ"`）
- 例外: `FileNotFoundError`、`ValueError`（privacy が不正値）、`QuotaExceededError`、`UploadError`

### 3. サムネイルアップロード（プライベートメソッド）

```python
def _set_thumbnail(
    service: googleapiclient.discovery.Resource,
    video_id: str,
    thumbnail_path: str,
) -> None:
```

- 外部から直接呼び出すメソッドではなく、`upload_video()` の内部から呼び出されるプライベートメソッド
- `thumbnail_path` が指定されている場合（`upload_video(thumbnail_path=...)` に値を渡した場合）のみ呼び出される
- `thumbnail_path=None` が渡された場合は `upload_video()` 内でスキップされ、`_set_thumbnail()` は呼び出されない
- `service`: authenticate() で取得した認証済みサービスオブジェクト
- `video_id`: サムネイルをセットする動画の video_id
- `thumbnail_path`: サムネイル画像ファイルのパス（PNG 推奨）
- 例外: `FileNotFoundError`、`ThumbnailError`（画像形式不正・サイズ超過等）

### 4. タイトル生成

```python
def build_title(
    date: datetime.date,
    title: str,
    scripture: str,
    preacher: str,
) -> str:
```

- 生成規則: `{年}年{月}月{日}日 「{title}」 {scripture} {preacher}師`
- 例: `2026年4月19日 「忘れ得じ、彼のパリサイびと」 ヨハネの福音書3章1〜15節 前田重雄師`
- 月・日はゼロパディングなし（4月19日であって04月19日でない）
- 説教者氏名の姓名間スペースは除去する（「前田 重雄」→「前田重雄」）
- 100 文字超過時は末尾から切り詰める

### 5. 説明文生成

```python
def build_description(
    date: datetime.date,
    title: str,
    scripture: str,
    preacher: str,
    template: str,
) -> str:
```

- `template`: config.yaml の youtube.description_template の値
- テンプレート内のプレースホルダー（{year}/{month}/{day}/{title}/{scripture}/{preacher}）を礼拝情報で置換する
- 戻り値: プレースホルダーを置換した説明文文字列

### 6. 独自例外クラス

| クラス名 | 説明 |
|---------|------|
| `YouTubeUploaderError` | このモジュール固有の基底例外クラス |
| `AuthenticationError(YouTubeUploaderError)` | OAuth2認証の失敗（ブラウザキャンセル・credentials.json 不正等） |
| `QuotaExceededError(YouTubeUploaderError)` | YouTube API の日次クォータ超過（HTTP 403 quotaExceeded） |
| `UploadError(YouTubeUploaderError)` | アップロード中のネットワーク断・API エラー |
| `ThumbnailError(YouTubeUploaderError)` | サムネイルセット失敗（画像形式不正・ファイルサイズ超過等） |

---

## OAuth2認証フロー詳細

### 初回認証（token.json が存在しない場合）

```
1. credentials.json を credentials_path から読み込む
2. google_auth_oauthlib.flow.InstalledAppFlow を生成する
   - スコープ: ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
3. flow.run_local_server(port=0) を呼び出す
   → デフォルトブラウザが起動し、Google アカウント選択・同意画面が表示される
   → ユーザーが同意すると認証コードが取得される
4. 取得したトークン（アクセストークン＋リフレッシュトークン）を token_path（token.json）に保存する
5. 認証済みサービスオブジェクトを返す
```

### 2回目以降（token.json が存在する場合）

```
1. token.json を読み込む
2. アクセストークンが有効期限内であればそのまま使用する
3. アクセストークンが期限切れの場合、リフレッシュトークンで自動更新する
   （google.auth.transport.requests.Request を使用）
4. 更新後のトークンを token.json に上書き保存する
5. リフレッシュトークンも無効な場合は初回認証フローに移行する
```

### credentials.json の取得手順（概要）

1. Google Cloud Console（https://console.cloud.google.com/）にアクセスする
2. プロジェクトを作成または選択する
3. 「APIとサービス」→「ライブラリ」で「YouTube Data API v3」を有効化する
4. **OAuth同意画面の設定**（必須）
   1. 「APIとサービス」→「OAuth同意画面」を開く
   2. ユーザータイプは「外部」を選択して「作成」をクリックする
   3. アプリ名（例: zoom-youtube-automator）とサポートメールアドレスを入力する
   4. 「スコープを追加または削除」で `youtube.upload` と `youtube.force-ssl` を追加する
   5. 「テストユーザー」にアップロード先の Google アカウント（メールアドレス）を追加する
   6. **注意: アプリが「テスト」状態のままだとリフレッシュトークンが7日で失効する。**  
      継続運用する場合は「本番環境に公開」申請（OAuth検証）を行うか、7日ごとに `token.json` を再取得すること
5. 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuth 2.0 クライアント ID」を選択する
6. アプリケーションの種類は「デスクトップアプリ」を選択する
7. 作成後、`credentials.json` をダウンロードして `config.yaml` の `youtube.credentials_path` で指定したパスに配置する
8. 初回起動時にブラウザ認証を行い、`token.json` が自動生成される
   - **スコープを変更した場合（`youtube.force-ssl` 追加時等）は既存の `token.json` を削除し、再取得すること**

---

## 動画アップロード仕様詳細

### Resumable Upload

- `googleapiclient.http.MediaFileUpload` の `resumable=True` を使用する
- チャンクサイズ: `10 * 1024 * 1024`（10MB）以上を推奨する。`google-api-python-client` のデフォルト値（約100MB）を使用してよい。256KB等の小サイズは数GBファイルで数千回のHTTPリクエストが発生するため非推奨
- アップロード中に HTTP 5xx または接続エラーが発生した場合、最大 3 回まで自動リトライする
  - リトライ間隔: 指数バックオフ（1秒、2秒、4秒）
- 3 回リトライしても失敗した場合は `UploadError` を送出する

### 説明文テンプレートのプレースホルダー

| プレースホルダー | 置換内容 |
|----------------|---------|
| `{year}` | 年（例: 2026） |
| `{month}` | 月（ゼロパディングなし、例: 4） |
| `{day}` | 日（ゼロパディングなし、例: 19） |
| `{title}` | 説教タイトル |
| `{scripture}` | 聖書箇所 |
| `{preacher}` | 説教者氏名（「師」なし） |

デフォルトテンプレート例（config.yaml.example に記載）：

```
{year}年{month}月{day}日 礼拝メッセージ

【説教題】「{title}」
【聖書箇所】{scripture}
【説教者】{preacher}師

調布南キリスト教会
〒182-0004 東京都調布市入間町1丁目
https://www.chofuminami.com/
```

### 動画メタデータ（固定値）

| 項目 | 値 |
|------|----|
| カテゴリID | `22`（People & Blogs）※ TBD |
| タグ | `["礼拝", "キリスト教", "調布南キリスト教会", "説教", "礼拝メッセージ"]` |
| 言語 | `ja`（日本語） |
| 公開設定 | `"public"` または `"unlisted"`（config.yaml の設定または UI 選択値） |

### サムネイル仕様

- アップロード後に `thumbnails.set` API で別途セットする（`upload_video()` 内で `_set_thumbnail()` を自動呼び出し）
- ファイル形式: PNG（SPEC_THUMBNAIL.md が生成する thumbnail.png）
- 最大ファイルサイズ: 2MB（YouTube API 制限）
- 推奨解像度: 1280x720px 以上（16:9）

---

## アップロード進捗管理

- `upload_video()` の `progress_callback` 引数に `Callable[[int], None]` を渡す
- コールバックはチャンク送信完了ごとに呼び出される
- 引数は 0〜100 の整数（パーセンテージ）
- コントローラー側でコールバックを定義し、Tkinter の `after()` キューを通じてプログレスバーを更新する
- コールバックが `None` の場合は進捗通知を行わない

---

## エラーハンドリング

| エラー種別 | 発生条件 | 対応 |
|-----------|---------|------|
| `FileNotFoundError` | credentials.json または動画ファイルが存在しない | 呼び出し元に伝播。GUI でファイルパスを確認するメッセージを表示 |
| `AuthenticationError` | ブラウザ認証キャンセル・credentials.json 不正 | 呼び出し元に伝播。GUI で再認証を促すメッセージを表示 |
| `QuotaExceededError` | HTTP 403 quotaExceeded レスポンス | 呼び出し元に伝播。GUI で「本日のクォータ超過。翌日以降に再試行してください」を表示 |
| `UploadError` | HTTP 5xx・接続タイムアウト（3 回リトライ後） | 呼び出し元に伝播。GUI で「アップロード失敗。ネットワークを確認して再試行してください」を表示 |
| `ThumbnailError` | サムネイル 2MB 超過・非対応形式 | サムネイルなしで動画アップロードは成功とし、警告を GUI に表示する |
| リフレッシュトークン失効 | 長期未使用・アカウント設定変更 | 初回認証フローに自動移行し、ブラウザを再起動する |

---

## 設定キー一覧（config.yaml の youtube.* セクション）

| キー | 型 | 必須 | 説明 |
|-----|----|------|------|
| `youtube.account` | string | 任意 | アップロード先 Google アカウントのメールアドレス（表示用。認証には使わない） |
| `youtube.credentials_path` | string | 必須 | credentials.json のファイルパス（絶対パス推奨） |
| `youtube.token_path` | string | 必須 | token.json の保存先ファイルパス（絶対パス推奨） |
| `youtube.default_visibility` | string | 必須 | デフォルト公開設定。"public" または "unlisted" |
| `youtube.description_template` | string | 必須 | 説明文テンプレート。プレースホルダー使用可（上記参照） |
| `youtube.category_id` | string | 任意 | YouTube 動画カテゴリID。省略時は "22"（People & Blogs） |
| `youtube.tags` | list[string] | 任意 | タグ一覧。省略時はデフォルトタグを使用 |

config.yaml での記述例：

```yaml
youtube:
  account: "chofu.minami@gmail.com"
  credentials_path: "credentials/credentials.json"
  token_path: "credentials/token.json"
  default_visibility: "public"
  category_id: "22"
  tags:
    - "礼拝"
    - "キリスト教"
    - "調布南キリスト教会"
    - "説教"
    - "礼拝メッセージ"
  description_template: |
    {year}年{month}月{day}日 礼拝メッセージ

    【説教題】「{title}」
    【聖書箇所】{scripture}
    【説教者】{preacher}師

    調布南キリスト教会
    〒182-0004 東京都調布市入間町1丁目
    https://www.chofuminami.com/
```

> **補足:** SPEC_OVERVIEW.md §8 の config.yaml 定義には `refresh_token` キーが TBD として記載されているが、本仕様では `token.json` ファイル一本化方式に確定した。`refresh_token` の config.yaml 直接記載は行わない。SPEC_OVERVIEW.md §8 に `credentials_path` と `token_path` の追記が必要（既存キーへの破壊的変更なし）。

---

## 依存ライブラリ

| パッケージ名 | バージョン要件 | 用途 |
|------------|-------------|------|
| `google-api-python-client` | `>=2.0.0` | YouTube Data API v3 クライアント |
| `google-auth-oauthlib` | `>=0.4.0` | OAuth2 認証フロー（InstalledAppFlow） |
| `google-auth-httplib2` | `>=0.1.0` | HTTP トランスポート層 |
| `google-auth` | `>=2.0.0` | 認証情報管理・トークン更新 |

requirements.txt への記載例：

```
google-api-python-client>=2.0.0
google-auth-oauthlib>=0.4.0
google-auth-httplib2>=0.1.0
google-auth>=2.0.0
```

Python バージョン要件: 3.9 以上（型ヒント `X | Y` 構文を使用するため）

---

## セキュリティ注意事項

### credentials.json の保護

- Google Cloud Console からダウンロードした `credentials.json` はリポジトリに含めないこと
- `config.yaml` の `youtube.credentials_path` で指定し、`.gitignore` の対象とする
- ファイルのアクセス権限は所有者のみ読み書き可能に設定すること（Windows: フォルダのプロパティ → セキュリティで制限）

### token.json の保護

- OAuth2 トークンが保存される `token.json` はリポジトリに含めないこと
- `token.json` には Google アカウントへのアクセス権限があるリフレッシュトークンが含まれる
- `.gitignore` の対象とし、所有者のみ読み書き可能に設定すること

### gitignore 対象ファイル一覧（YouTube関連）

```
credentials.json
token.json
config.yaml
```

### スコープの最小化

- 要求する OAuth2 スコープは `youtube.upload` と `youtube.force-ssl` の2つに限定する
  - `youtube.upload`: 動画アップロードに必須
  - `youtube.force-ssl`: サムネイル設定（`thumbnails.set`）に必要。`youtube.upload` 単独では失敗するケースがある
- チャンネル管理・削除・他ユーザーデータアクセスなど不要なスコープは要求しない

---

## テスト方針

### 単体テスト

- `unittest.mock.patch` を使用して `googleapiclient.discovery.build` をモックする
- `authenticate()` のテスト: token.json が存在する場合・存在しない場合・リフレッシュトークン期限切れの場合
- `build_title()` のテスト: 日付フォーマット（ゼロパディングなし）・氏名スペース除去・100 文字超過時の切り詰め
- `build_description()` のテスト: 各プレースホルダーの正常置換・テンプレートにないプレースホルダーの扱い
- `upload_video()` のテスト: 正常系（mock で video_id を返す）・QuotaExceeded・UploadError（3 回リトライ）
- `_set_thumbnail()` のテスト: `upload_video()` 経由での正常系・ThumbnailError（ファイルサイズ超過）・`thumbnail_path=None` 時のスキップ確認

### テストファイル構成

```
tests/
  test_youtube_uploader.py
  fixtures/
    dummy_credentials.json   # テスト用ダミー credentials（実認証情報ではない）
    dummy_token.json         # テスト用ダミー token
    test_video.mp4           # 最小サイズのダミー動画（数KB）
    test_thumbnail.png       # ダミーサムネイル画像
```

### 統合テスト（手動）

- 本番 Google アカウントを使用した実機テストは YouTube にアップロードが発生するため、限定公開でテストアップロードし、確認後に手動削除する
- クォータ上限（1日10,000ユニット、動画アップロード 100ユニット/本）に注意すること（2026年改定値、1日最大66本まで対応可能）

---

## TBD・未決事項

| 項目 | 内容 | 優先度 |
|------|------|--------|
| YouTube カテゴリ | "22"（People & Blogs）vs "29"（Nonprofits & Activism）等、適切なカテゴリを教会側に確認する | Medium |
| 説明文テンプレート | 調布南キリスト教会の正式な説明文定型文フォーマットを確定する（チャンネルURL含む） | Medium |
| token.json の保存先 | config.yaml 内に token_path として管理する方針だが、Windows 資格情報マネージャー（keyring ライブラリ）への移行を将来的に検討する | Low |
| アップロード後のリトライUI | UploadError 発生時に GUI 上で手動リトライボタンを提供するか・自動リトライのみとするかを確定する | Medium |
| チャンネルID | ✅ 確定済み：デフォルトチャンネルを使用。config.yaml の `youtube.channel_id` で上書き可能 | 解決済み |
| Google Cloud プロジェクト | ✅ 確定済み：YouTubeアカウントの持ち主（教会スタッフ）が初回セットアップを実施 | 解決済み |

---

## 制約・前提条件

- 対応 OS: Windows 10 / 11 64bit のみ（SPEC_OVERVIEW.md に準拠）
- Python 3.9 以上が必要
- `credentials.json` は事前に Google Cloud Console で取得・配置されていること
- 初回認証はブラウザが起動できる環境でのみ実行可能（ヘッドレス環境は非対応）
- YouTube Data API v3 の日次クォータ（10,000ユニット）に注意すること。1 動画アップロードで 100 ユニット消費する（2026年改定値）
- 動画アップロードのスコープ（youtube.upload）は YouTube チャンネルが存在するアカウントにのみ有効
- OBS 録画が正常に完了し、MP4 ファイルが存在することを前提とする（ファイル存在確認はコントローラー側で行う）
- 本モジュールは Tkinter ループを直接操作しない。進捗通知はコールバック経由のみとする

---

## 受け入れ条件

- [ ] `build_title()` が指定フォーマット（{年}年{月}月{日}日 「{title}」 {scripture} {preacher}師）の文字列を返す
- [ ] `build_title()` が月・日のゼロパディングなしで出力する（4月19日であって04月19日でない）
- [ ] `build_title()` が説教者氏名のスペースを除去する（「前田 重雄」→「前田重雄」）
- [ ] `authenticate()` が token.json 存在時にブラウザを起動せず認証済みサービスオブジェクトを返す
- [ ] `authenticate()` が token.json 不存在時にブラウザを起動し、token.json を生成する
- [ ] `authenticate()` がリフレッシュトークン期限切れ時に初回認証フローに移行する
- [ ] `upload_video()` がモック API に対して `video_id`（str）と `video_url`（`https://youtu.be/{video_id}` 形式、str）を含む辞書を返す
- [ ] `upload_video()` が `progress_callback` を渡した場合に 0〜100 の整数で呼び出す
- [ ] `upload_video()` が QuotaExceeded（HTTP 403）で `QuotaExceededError` を送出する
- [ ] `upload_video()` が HTTP 5xx で最大 3 回リトライし、失敗後に `UploadError` を送出する
- [ ] `upload_video()` が `thumbnail_path` 指定時に内部で `_set_thumbnail()` を呼び出しモック API に対して正常終了する
- [ ] `upload_video()` が `thumbnail_path=None` 時に `_set_thumbnail()` を呼び出さない
- [ ] `_set_thumbnail()` が `ThumbnailError` 発生時に動画アップロードを失敗扱いにしない
- [ ] `credentials.json` および `token.json` がリポジトリに含まれていない（.gitignore 確認）
- [ ] 単体テストが `unittest.mock` のみでネットワーク接続なしで実行できる

---

## 実装メモ（PRGちゃんへの引き継ぎ）

### ファイル配置

- モジュール本体: `youtube_uploader.py`（プロジェクトルートまたは `src/` 以下、SPEC_GUI.md と整合する配置に従う）
- テスト: `tests/test_youtube_uploader.py`

### config.yaml との連携

- `config.yaml` の読み込みはコントローラー（`app.py`）が担当する。`youtube_uploader.py` は読み込み済みの値を引数で受け取る設計とする
- `credentials_path` と `token_path` の両方が `config.yaml` に記載されていることを前提とする

### 注意: Windows 日本語パス

- `video_path` や `thumbnail_path` に日本語が含まれる可能性がある
- `MediaFileUpload` はファイルパスを文字列で受け取るが、内部で `open()` するため日本語パスの動作を実機確認すること（必要であれば一時ファイルにコピーしてから渡す。SPEC_OVERVIEW.md §10.4 参照）

### トークン保存の実装

- `google.oauth2.credentials.Credentials` の `to_json()` で token.json に保存する
- 読み込みは `Credentials.from_authorized_user_file(token_path, SCOPES)` を使用する

### progress_callback のスレッド安全性

- `upload_video()` は Tkinter のメインスレッドとは別スレッドで実行される想定
- `progress_callback` 内で直接 Tkinter ウィジェットを更新しないこと
- コントローラー側で `root.after(0, lambda: progressbar.set(value))` の形でメインスレッドキューに積むこと

### Resumable Upload の実装ポイント

- `googleapiclient.http.MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)` を使用する
- `next_chunk()` のループで進捗を取得する（`status.progress()` が 0.0〜1.0 を返す）
- `status` が `None` になった時点でアップロード完了
- `progress_callback` には `int(status.progress() * 100)` を渡す

### SPEC_OVERVIEW.md との整合確認

- config.yaml の youtube.* セクションに `credentials_path`・`token_path` キーを追加する（SPEC_OVERVIEW.md §8 への追記が必要。既存キーへの破壊的変更なし）
- SPEC_OVERVIEW.md §8 に記載されている `refresh_token` の config.yaml 直接保存は本仕様で token.json 方式に変更した。SPEC_OVERVIEW.md §8 と §10.3 の該当記述を本仕様書と整合させる更新が必要
