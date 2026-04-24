"""
tests/test_youtube_uploader.py
YouTube アップローダーモジュールの単体テスト（全てモックで動作）
"""

import datetime
import json
import os
import unittest
from unittest.mock import MagicMock, patch, call

# テスト実行前に sys.path を通す
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from youtube_uploader import (
    authenticate,
    upload_video,
    build_title,
    build_description,
    YouTubeUploaderError,
    AuthenticationError,
    QuotaExceededError,
    UploadError,
    ThumbnailError,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
DUMMY_CREDENTIALS = os.path.join(FIXTURES_DIR, 'dummy_credentials.json')
DUMMY_TOKEN = os.path.join(FIXTURES_DIR, 'dummy_token.json')
TEST_VIDEO = os.path.join(FIXTURES_DIR, 'test_video.mp4')
TEST_THUMBNAIL = os.path.join(FIXTURES_DIR, 'test_thumbnail.png')


# ---------------------------------------------------------------------------
# build_title テスト
# ---------------------------------------------------------------------------

class TestBuildTitle(unittest.TestCase):

    def test_normal(self):
        """指定フォーマットの文字列を返す"""
        date = datetime.date(2026, 4, 19)
        result = build_title(date, '忘れ得じ、彼のパリサイびと', 'ヨハネの福音書3章1〜15節', '前田重雄')
        expected = '2026年4月19日 「忘れ得じ、彼のパリサイびと」 ヨハネの福音書3章1〜15節 前田重雄師'
        self.assertEqual(result, expected)

    def test_no_zero_padding(self):
        """月・日はゼロパディングなし（4月19日であって04月19日でない）"""
        date = datetime.date(2026, 4, 5)
        result = build_title(date, 'テストタイトル', '創世記1章', '田中一郎')
        self.assertIn('4月5日', result)
        self.assertNotIn('04月', result)
        self.assertNotIn('05日', result)

    def test_preacher_space_removal(self):
        """説教者の姓名間スペースを除去する（半角・全角両方）"""
        date = datetime.date(2026, 4, 19)
        result = build_title(date, 'タイトル', '聖書箇所', '前田 重雄')
        self.assertIn('前田重雄師', result)
        self.assertNotIn('前田 重雄', result)

    def test_preacher_fullwidth_space_removal(self):
        """全角スペースも除去する"""
        date = datetime.date(2026, 4, 19)
        result = build_title(date, 'タイトル', '聖書箇所', '前田　重雄')
        self.assertIn('前田重雄師', result)
        self.assertNotIn('前田　重雄', result)

    def test_truncate_over_100_chars(self):
        """100文字超過時は100文字以内に切り詰める"""
        date = datetime.date(2026, 4, 19)
        long_title = 'あ' * 100
        result = build_title(date, long_title, 'ヨハネの福音書3章', '前田重雄')
        self.assertLessEqual(len(result), 100)


# ---------------------------------------------------------------------------
# build_description テスト
# ---------------------------------------------------------------------------

class TestBuildDescription(unittest.TestCase):

    TEMPLATE = (
        "{year}年{month}月{day}日 礼拝メッセージ\n\n"
        "【説教題】「{title}」\n"
        "【聖書箇所】{scripture}\n"
        "【説教者】{preacher}師\n"
    )

    def test_normal(self):
        """各プレースホルダーが正しく置換される"""
        date = datetime.date(2026, 4, 19)
        result = build_description(date, 'テスト説教', 'ヨハネ3:16', '前田重雄', self.TEMPLATE)
        self.assertIn('2026年4月19日', result)
        self.assertIn('「テスト説教」', result)
        self.assertIn('ヨハネ3:16', result)
        self.assertIn('前田重雄師', result)

    def test_month_day_no_zero_padding(self):
        """月・日のゼロパディングなし"""
        date = datetime.date(2026, 4, 5)
        result = build_description(date, 'タイトル', '箇所', '説教者', self.TEMPLATE)
        self.assertIn('4月5日', result)
        self.assertNotIn('04月', result)
        self.assertNotIn('05日', result)


# ---------------------------------------------------------------------------
# authenticate テスト
# ---------------------------------------------------------------------------

class TestAuthenticate(unittest.TestCase):

    @patch('youtube_uploader.build')
    @patch('youtube_uploader.Credentials')
    def test_token_exists(self, mock_credentials_cls, mock_build):
        """token.json が存在する場合、ブラウザを起動せずに認証済みオブジェクトを返す"""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_credentials_cls.from_authorized_user_file.return_value = mock_creds
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        result = authenticate(DUMMY_CREDENTIALS, DUMMY_TOKEN)

        mock_credentials_cls.from_authorized_user_file.assert_called_once()
        mock_build.assert_called_once()
        self.assertEqual(result, mock_service)

    @patch('youtube_uploader.build')
    @patch('youtube_uploader.InstalledAppFlow')
    def test_token_not_exists(self, mock_flow_cls, mock_build):
        """token.json が存在しない場合、InstalledAppFlow（ブラウザフロー）が呼ばれる"""
        mock_flow = MagicMock()
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_flow.run_local_server.return_value = mock_creds
        mock_creds.to_json.return_value = json.dumps({'token': 'new_token'})
        mock_build.return_value = MagicMock()

        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
            tmp_path = tmp.name
        os.unlink(tmp_path)  # ファイルを削除してtoken不存在状態にする

        try:
            result = authenticate(DUMMY_CREDENTIALS, tmp_path)
            mock_flow_cls.from_client_secrets_file.assert_called_once()
            mock_flow.run_local_server.assert_called_once_with(port=0)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_credentials_not_found(self):
        """credentials.json が存在しない場合、FileNotFoundError が送出される"""
        with self.assertRaises(FileNotFoundError):
            authenticate('/nonexistent/path/credentials.json', DUMMY_TOKEN)

    @patch('youtube_uploader.build')
    @patch('youtube_uploader.InstalledAppFlow')
    @patch('youtube_uploader.Credentials')
    def test_token_expired_triggers_reauth(self, mock_credentials_cls, mock_flow_cls, mock_build):
        """リフレッシュトークンが無効な場合にInstalledAppFlowが起動すること"""
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = None
        mock_credentials_cls.from_authorized_user_file.return_value = mock_creds

        mock_flow = MagicMock()
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow
        new_creds = MagicMock()
        new_creds.to_json.return_value = json.dumps({'token': 'new_token'})
        mock_flow.run_local_server.return_value = new_creds
        mock_build.return_value = MagicMock()

        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            authenticate(DUMMY_CREDENTIALS, tmp_path)
            mock_flow_cls.from_client_secrets_file.assert_called_once()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# upload_video テスト
# ---------------------------------------------------------------------------

class TestUploadVideo(unittest.TestCase):

    def _make_service(self):
        return MagicMock()

    @patch('youtube_uploader.MediaFileUpload')
    def test_normal(self, mock_media_upload):
        """正常系: video_id と video_url を含む辞書を返す"""
        service = self._make_service()
        mock_request = MagicMock()
        service.videos.return_value.insert.return_value = mock_request

        # next_chunk: 1回目にstatus付きで返し、2回目にNoneでアップロード完了
        mock_status = MagicMock()
        mock_status.progress.return_value = 1.0
        mock_response = {'id': 'abc123'}
        mock_request.next_chunk.side_effect = [
            (mock_status, None),
            (None, mock_response),
        ]

        result = upload_video(service, TEST_VIDEO, 'テスト動画', '説明文', None, 'public')

        self.assertEqual(result['video_id'], 'abc123')
        self.assertEqual(result['video_url'], 'https://youtu.be/abc123')

    @patch('youtube_uploader.MediaFileUpload')
    def test_progress_callback(self, mock_media_upload):
        """progress_callback が 0〜100 の整数で呼ばれる"""
        service = self._make_service()
        mock_request = MagicMock()
        service.videos.return_value.insert.return_value = mock_request

        mock_status1 = MagicMock()
        mock_status1.progress.return_value = 0.5
        mock_status2 = MagicMock()
        mock_status2.progress.return_value = 1.0
        mock_response = {'id': 'xyz789'}

        mock_request.next_chunk.side_effect = [
            (mock_status1, None),
            (None, mock_response),
        ]

        callback_values = []
        upload_video(service, TEST_VIDEO, 'タイトル', '説明', None, 'public',
                     progress_callback=lambda p: callback_values.append(p))

        self.assertTrue(all(isinstance(v, int) for v in callback_values))
        self.assertTrue(all(0 <= v <= 100 for v in callback_values))

    @patch('youtube_uploader.MediaFileUpload')
    def test_quota_exceeded(self, mock_media_upload):
        """HTTP 403 quotaExceeded で QuotaExceededError が送出される"""
        from googleapiclient.errors import HttpError
        service = self._make_service()
        mock_request = MagicMock()
        service.videos.return_value.insert.return_value = mock_request

        resp = MagicMock()
        resp.status = 403
        error_content = json.dumps({
            'error': {'errors': [{'reason': 'quotaExceeded'}]}
        }).encode()
        mock_request.next_chunk.side_effect = HttpError(resp=resp, content=error_content)

        with self.assertRaises(QuotaExceededError):
            upload_video(service, TEST_VIDEO, 'タイトル', '説明', None, 'public')

    @patch('youtube_uploader.time')
    @patch('youtube_uploader.MediaFileUpload')
    def test_retry_then_upload_error(self, mock_media_upload, mock_time):
        """HTTP 5xx で3回リトライ後 UploadError が送出される"""
        from googleapiclient.errors import HttpError
        service = self._make_service()
        mock_request = MagicMock()
        service.videos.return_value.insert.return_value = mock_request

        resp = MagicMock()
        resp.status = 503
        error_content = b'Service Unavailable'
        mock_request.next_chunk.side_effect = HttpError(resp=resp, content=error_content)

        with self.assertRaises(UploadError):
            upload_video(service, TEST_VIDEO, 'タイトル', '説明', None, 'public')

        # time.sleep が3回呼ばれていること（指数バックオフ）
        self.assertEqual(mock_time.sleep.call_count, 3)

    @patch('youtube_uploader._set_thumbnail')
    @patch('youtube_uploader.MediaFileUpload')
    def test_thumbnail_called_when_path_given(self, mock_media_upload, mock_set_thumbnail):
        """thumbnail_path 指定時に _set_thumbnail が呼ばれる"""
        service = self._make_service()
        mock_request = MagicMock()
        service.videos.return_value.insert.return_value = mock_request

        mock_status = MagicMock()
        mock_status.progress.return_value = 1.0
        mock_response = {'id': 'thumb_test_id'}
        mock_request.next_chunk.side_effect = [
            (mock_status, None),
            (None, mock_response),
        ]

        upload_video(service, TEST_VIDEO, 'タイトル', '説明', TEST_THUMBNAIL, 'public')

        mock_set_thumbnail.assert_called_once_with(service, 'thumb_test_id', TEST_THUMBNAIL)

    @patch('youtube_uploader.MediaFileUpload')
    def test_progress_callback_receives_100_on_completion(self, mock_media_upload):
        """アップロード完了時にprogress_callbackが100で呼ばれること"""
        service = self._make_service()
        mock_request = MagicMock()
        service.videos.return_value.insert.return_value = mock_request

        mock_response = {'id': 'complete_id'}
        # 1回のnext_chunk呼び出しでstatus=None（即完了）を返す
        mock_request.next_chunk.side_effect = [(None, mock_response)]

        callback_values = []
        upload_video(service, TEST_VIDEO, 'タイトル', '説明', None, 'public',
                     progress_callback=lambda p: callback_values.append(p))

        self.assertIn(100, callback_values)

    @patch('youtube_uploader._set_thumbnail')
    @patch('youtube_uploader.MediaFileUpload')
    def test_thumbnail_not_called_when_none(self, mock_media_upload, mock_set_thumbnail):
        """thumbnail_path=None のとき _set_thumbnail は呼ばれない"""
        service = self._make_service()
        mock_request = MagicMock()
        service.videos.return_value.insert.return_value = mock_request

        mock_status = MagicMock()
        mock_status.progress.return_value = 1.0
        mock_response = {'id': 'no_thumb_id'}
        mock_request.next_chunk.side_effect = [
            (mock_status, None),
            (None, mock_response),
        ]

        upload_video(service, TEST_VIDEO, 'タイトル', '説明', None, 'public')

        mock_set_thumbnail.assert_not_called()


# ---------------------------------------------------------------------------
# _set_thumbnail テスト
# ---------------------------------------------------------------------------

class TestSetThumbnail(unittest.TestCase):

    @patch('youtube_uploader.MediaFileUpload')
    def test_thumbnail_error_does_not_fail_upload(self, mock_media_upload):
        """_set_thumbnail が ThumbnailError を送出しても upload_video は成功扱い"""
        from googleapiclient.errors import HttpError
        service = MagicMock()

        # 動画アップロードは成功
        mock_request = MagicMock()
        service.videos.return_value.insert.return_value = mock_request
        mock_status = MagicMock()
        mock_status.progress.return_value = 1.0
        mock_response = {'id': 'thumbnail_error_id'}
        mock_request.next_chunk.side_effect = [
            (mock_status, None),
            (None, mock_response),
        ]

        # サムネイルAPIはエラーを返す
        resp = MagicMock()
        resp.status = 400
        service.thumbnails.return_value.set.return_value.execute.side_effect = HttpError(
            resp=resp, content=b'Bad Request'
        )

        # ThumbnailError が送出されても upload_video は結果を返す
        result = upload_video(service, TEST_VIDEO, 'タイトル', '説明', TEST_THUMBNAIL, 'public')

        self.assertIn('video_id', result)
        self.assertEqual(result['video_id'], 'thumbnail_error_id')


if __name__ == '__main__':
    unittest.main()
