"""OBS実機統合テスト - 実際にOBSが起動している状態で実行する"""
import sys
import time
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from obs_client import OBSClient
from exceptions import OBSError

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print('='*50)


def ok(msg):
    print(f"  [OK] {msg}")


def fail(msg):
    print(f"  [NG] {msg}")


def main():
    config = load_config()
    obs_cfg = config.get("obs", {})

    scene = obs_cfg.get("scene", "聖日礼拝")

    client = OBSClient(
        host=obs_cfg.get("host", "localhost"),
        port=obs_cfg.get("port", 4455),
        password=obs_cfg.get("password", ""),
        output_dir=obs_cfg.get("output_dir", ""),
    )

    # 1. 接続テスト
    section("1. OBS接続テスト")
    try:
        client.connect()
        ok("接続成功")
    except OBSError as e:
        fail(f"接続失敗: {e}")
        return

    # 2. 録画状態確認
    section("2. 録画状態確認")
    try:
        is_recording = client.get_recording_status()
        ok(f"録画状態取得成功: recording={is_recording}")
    except OBSError as e:
        fail(f"状態取得失敗: {e}")

    # 3. 仮想カメラ起動
    section("3. 仮想カメラ起動テスト")
    try:
        client.start_virtual_cam()
        ok("仮想カメラ起動成功")
        time.sleep(1)
        client.stop_virtual_cam()
        ok("仮想カメラ停止成功")
    except OBSError as e:
        fail(f"仮想カメラ操作失敗: {e}")

    # 4. 録画開始・停止テスト（約5秒）
    section("4. 録画テスト（5秒間録画）")
    print("  ※ OBSが録画を開始します。5秒後に停止します。")
    try:
        client.start_recording(scene_name=scene)
        ok("録画開始成功")
        print("  録画中... 5秒待機")
        time.sleep(5)
        output_path = client.stop_recording()
        ok(f"録画停止成功")
        ok(f"保存先: {output_path}")
        if output_path and Path(output_path).exists():
            size = Path(output_path).stat().st_size
            ok(f"ファイル確認OK（{size:,} bytes）")
        else:
            fail(f"ファイルが見つかりません: {output_path}")
    except OBSError as e:
        fail(f"録画テスト失敗: {e}")

    # 5. 切断
    section("5. 切断テスト")
    try:
        client.disconnect()
        ok("切断成功")
    except OBSError as e:
        fail(f"切断失敗: {e}")

    section("完了")
    print("  OBS実機統合テスト終了")


if __name__ == "__main__":
    main()
