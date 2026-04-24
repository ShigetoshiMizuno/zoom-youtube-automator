"""
src/youtube_uploader.py
YouTube Data API v3 を使った動画アップロードモジュール
"""

import datetime
import json
import os
import time

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
except ImportError:
    build = None
    HttpError = Exception
    MediaFileUpload = None
    InstalledAppFlow = None
    Credentials = None
    Request = None

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

DEFAULT_CATEGORY_ID = "22"
DEFAULT_TAGS = ["礼拝", "キリスト教", "調布南キリスト教会", "説教", "礼拝メッセージ"]
VALID_PRIVACY = {"public", "unlisted"}
MAX_TITLE_LENGTH = 100
MAX_RETRY = 3


# ---------------------------------------------------------------------------
# 独自例外クラス
# ---------------------------------------------------------------------------

class YouTubeUploaderError(Exception):
    """このモジュール固有の基底例外クラス"""


class AuthenticationError(YouTubeUploaderError):
    """OAuth2認証の失敗"""


class QuotaExceededError(YouTubeUploaderError):
    """YouTube API の日次クォータ超過"""


class UploadError(YouTubeUploaderError):
    """アップロード中のエラー"""


class ThumbnailError(YouTubeUploaderError):
    """サムネイルセット失敗"""


# ---------------------------------------------------------------------------
# 認証
# ---------------------------------------------------------------------------

def authenticate(credentials_path: str, token_path: str):
    """OAuth2認証を行い、YouTube API サービスオブジェクトを返す。

    Args:
        credentials_path: credentials.json のファイルパス
        token_path: token.json の保存・読み込みパス

    Returns:
        認証済みの YouTube API サービスオブジェクト

    Raises:
        FileNotFoundError: credentials_path が存在しない場合
        AuthenticationError: ブラウザ認証キャンセル等の認証失敗
    """
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(f"credentials.json が見つかりません: {credentials_path}")

    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds and creds.valid:
        pass
    elif creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds, token_path)
    else:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        except Exception as exc:
            raise AuthenticationError(f"認証に失敗しました: {exc}") from exc
        _save_token(creds, token_path)

    return build("youtube", "v3", credentials=creds)


def _save_token(creds, token_path: str) -> None:
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


# ---------------------------------------------------------------------------
# 動画アップロード
# ---------------------------------------------------------------------------

def upload_video(
    service,
    video_path: str,
    title: str,
    description: str,
    thumbnail_path,
    privacy: str,
    progress_callback=None,
) -> dict:
    """動画を YouTube にアップロードする。

    Args:
        service: authenticate() で取得した認証済みサービスオブジェクト
        video_path: アップロードするMP4ファイルのパス
        title: YouTube 動画タイトル
        description: YouTube 動画説明文
        thumbnail_path: サムネイル画像ファイルのパス。None の場合はスキップ
        privacy: 公開設定。"public" または "unlisted"
        progress_callback: 進捗を 0〜100 の整数で受け取るコールバック関数

    Returns:
        {"video_id": str, "video_url": str}

    Raises:
        FileNotFoundError: video_path が存在しない場合
        ValueError: privacy が不正値の場合
        QuotaExceededError: HTTP 403 quotaExceeded
        UploadError: 3回リトライ後も失敗した場合
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")

    if privacy not in VALID_PRIVACY:
        raise ValueError(f"privacy は 'public' または 'unlisted' を指定してください: {privacy}")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": DEFAULT_TAGS,
            "categoryId": DEFAULT_CATEGORY_ID,
            "defaultLanguage": "ja",
        },
        "status": {
            "privacyStatus": privacy,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    video_id = _execute_upload(request, progress_callback)

    if thumbnail_path is not None:
        try:
            _set_thumbnail(service, video_id, thumbnail_path)
        except ThumbnailError:
            # サムネイルエラーは動画アップロードの成否に影響しない
            pass

    return {
        "video_id": video_id,
        "video_url": f"https://youtu.be/{video_id}",
    }


def _execute_upload(request, progress_callback) -> str:
    """Resumable Upload を実行し、動画IDを返す。リトライあり。"""
    retry_count = 0
    backoff_seconds = 1

    while True:
        try:
            status, response = request.next_chunk()
            if response is not None:
                if progress_callback is not None:
                    progress_callback(100)
                return response["id"]
            if status is not None and progress_callback is not None:
                progress_callback(int(status.progress() * 100))
        except HttpError as exc:
            if _is_quota_exceeded(exc):
                raise QuotaExceededError("YouTube APIのクォータを超過しました") from exc
            if _is_retryable(exc) and retry_count < MAX_RETRY:
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                retry_count += 1
            else:
                raise UploadError(f"アップロードに失敗しました: {exc}") from exc


def _is_quota_exceeded(exc) -> bool:
    try:
        status = exc.resp.status
        content = exc.content.decode("utf-8", errors="replace")
        return status == 403 and "quotaExceeded" in content
    except Exception:
        return False


def _is_retryable(exc) -> bool:
    try:
        return exc.resp.status >= 500
    except Exception:
        return False


# ---------------------------------------------------------------------------
# サムネイルセット（プライベートメソッド）
# ---------------------------------------------------------------------------

def _set_thumbnail(service, video_id: str, thumbnail_path: str) -> None:
    """サムネイル画像をアップロード済み動画にセットする。

    Raises:
        FileNotFoundError: thumbnail_path が存在しない場合
        ThumbnailError: サムネイルセット失敗
    """
    if not os.path.exists(thumbnail_path):
        raise FileNotFoundError(f"サムネイルファイルが見つかりません: {thumbnail_path}")

    try:
        media = MediaFileUpload(thumbnail_path, mimetype="image/png", resumable=False)
        service.thumbnails().set(
            videoId=video_id,
            media_body=media,
        ).execute()
    except HttpError as exc:
        raise ThumbnailError(f"サムネイルのセットに失敗しました: {exc}") from exc


# ---------------------------------------------------------------------------
# タイトル・説明文生成
# ---------------------------------------------------------------------------

def build_title(
    date: datetime.date,
    title: str,
    scripture: str,
    preacher: str,
) -> str:
    """礼拝情報からYouTube動画タイトルを生成する。

    書式: {年}年{月}月{日}日 「{title}」 {scripture} {preacher}師
    - 月・日はゼロパディングなし
    - 説教者姓名間スペース（半角・全角）を除去
    - 100文字超過時は切り詰め
    """
    clean_preacher = preacher.replace(" ", "").replace("　", "")
    result = (
        f"{date.year}年{date.month}月{date.day}日"
        f" 「{title}」 {scripture} {clean_preacher}師"
    )
    return result[:MAX_TITLE_LENGTH]


def build_description(
    date: datetime.date,
    title: str,
    scripture: str,
    preacher: str,
    template: str,
) -> str:
    """テンプレートのプレースホルダーを礼拝情報で置換した説明文を返す。

    プレースホルダー: {year} {month} {day} {title} {scripture} {preacher}
    """
    return template.format(
        year=date.year,
        month=date.month,
        day=date.day,
        title=title,
        scripture=scripture,
        preacher=preacher,
    )
