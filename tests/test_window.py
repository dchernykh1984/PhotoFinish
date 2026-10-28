"""The window builds under the offscreen platform."""

from __future__ import annotations


def test_window_title_names_the_app(win) -> None:
    assert win.windowTitle() == "PhotoFinish"
