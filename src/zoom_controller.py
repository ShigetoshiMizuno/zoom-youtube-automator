# zoom_controller.py — stub for Red phase (TDD)
from dataclasses import dataclass
from typing import Optional


@dataclass
class WindowPosition:
    x: int
    y: int
    width: int
    height: int


@dataclass
class ZoomConfig:
    meeting_id: str
    password: str = ""
    display_name: str = "配信"
    join_timeout: int = 30
    window_position: Optional[WindowPosition] = None


class ZoomError(Exception):
    pass


class ZoomNotInstalledError(ZoomError):
    pass


class ZoomSchemeNotRegisteredError(ZoomError):
    pass


class ZoomJoinTimeoutError(ZoomError):
    pass


class ZoomWindowNotFoundError(ZoomError):
    pass


class ZoomController:
    def __init__(self, config: ZoomConfig) -> None:
        raise NotImplementedError

    def build_zoom_url(self) -> str:
        raise NotImplementedError

    def join_meeting(self) -> None:
        raise NotImplementedError

    def leave_meeting(self) -> None:
        raise NotImplementedError

    def set_window_position(self, position: WindowPosition) -> None:
        raise NotImplementedError

    def is_meeting_active(self) -> bool:
        raise NotImplementedError

    def _check_zoom_installed(self) -> None:
        raise NotImplementedError
