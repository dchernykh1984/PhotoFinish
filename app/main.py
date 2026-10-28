"""Entry point for PhotoFinish."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import app
from app.main_window import MainWindow

_APP_NAME = "PhotoFinish"
# Resolved from the package, not this script: a frozen build runs the entry
# script from the bundle root, while the icon ships inside app/.
_ICON = str(Path(app.__file__).parent / "app.ico")


def main() -> None:
    # Must run before QApplication -- Qt reads the process name on init.
    _macos_set_process_name(_APP_NAME)
    _windows_set_app_id(_APP_NAME)

    app = QApplication(sys.argv)
    app.setApplicationName(_APP_NAME)
    app.setApplicationDisplayName(_APP_NAME)
    app.setWindowIcon(QIcon(_ICON))
    if sys.platform.startswith("linux"):
        app.setDesktopFileName(_APP_NAME.lower().replace(" ", "-"))

    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    sys.exit(app.exec())


def _macos_set_process_name(name: str) -> None:
    """Set NSProcessInfo processName before QApplication registers with the dock."""
    if sys.platform != "darwin":
        return
    import ctypes
    import ctypes.util

    try:
        _lib = ctypes.util.find_library("objc")
        if _lib is None:
            return
        objc = ctypes.cdll.LoadLibrary(_lib)
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p

        def _nsstr(s: str) -> int:
            objc.objc_msgSend.restype = ctypes.c_void_p
            objc.objc_msgSend.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_char_p,
            ]
            return objc.objc_msgSend(  # type: ignore[return-value]
                objc.objc_getClass(b"NSString"),
                objc.sel_registerName(b"stringWithUTF8String:"),
                s.encode("utf-8"),
            )

        objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        proc_info = objc.objc_msgSend(
            objc.objc_getClass(b"NSProcessInfo"),
            objc.sel_registerName(b"processInfo"),
        )

        objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        objc.objc_msgSend(
            proc_info,
            objc.sel_registerName(b"setProcessName:"),
            _nsstr(name),
        )
    except Exception:  # noqa: S110
        pass


def _windows_set_app_id(name: str) -> None:
    """Set AppUserModelID so Windows taskbar groups by app, not python.exe."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        app_id = f"offline-referee.{name.replace(' ', '')}"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)  # type: ignore[attr-defined]
    except Exception:  # noqa: S110
        pass


if __name__ == "__main__":
    main()
