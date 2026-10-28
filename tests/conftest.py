"""Shared Qt fixtures for the window tests.

main_window is excluded from coverage, so these Qt-level tests are what keeps its
handlers from drifting silently.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app import main_window as mw

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    """A MainWindow under the offscreen platform."""
    w = mw.MainWindow()
    yield w
    w.deleteLater()
