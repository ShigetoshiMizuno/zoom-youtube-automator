"""OBS連携モジュール 例外クラス定義"""


class OBSError(Exception):
    """OBS連携モジュールの基底例外クラス"""


class OBSConnectionError(OBSError):
    """接続・認証失敗（OBSが未起動・パスワード誤り・ポート不一致 等）"""


class OBSSceneNotFoundError(OBSError):
    """指定シーンが OBS に存在しない"""


class OBSRecordingError(OBSError):
    """録画開始・停止・ファイルパス取得の失敗"""


class OBSVirtualCamError(OBSError):
    """仮想カメラ起動・停止の失敗"""
