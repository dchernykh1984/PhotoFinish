---
name: qt-window-tests
description: How to test the PySide6 main window in this repository -- the offscreen setup, keeping a test off the real disk and out of dialogs, testing timer-driven handlers, simulating typing, and rendering the window to a PNG to check a layout. Use when changing or testing anything in app/main_window.py.
---

# Testing the window

`app/main_window.py` is excluded from coverage, so these tests are the only
thing standing between a handler and a silent regression. Add one for every
handler change.

## Setup

`tests/conftest.py` selects the platform plugin before `QtWidgets` is imported
and keeps one module-level `QApplication`:

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from app import main_window as mw

_app = QApplication.instance() or QApplication([])
```

## The fixture

`win` builds a `MainWindow`. Once the window loads or saves files, extend the
fixture so a test never touches the real `data/` folder - point every path at
`tmp_path` or stub the loader - and silence the dialogs, or a test blocks:

```python
monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: None)
monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: None)
```

A widget can still hold whatever the window loaded at construction, so a test
that inspects a list or a combo box clears it and fills in known values first.

## Timers

Do not wait for a `QTimer` to fire. Call the slot directly and assert on
`timer.isActive()`. For that to mean the same thing as a real firing, the slot
should stop its own timer on entry -- a single-shot timer stops itself when Qt
fires it, but not when a test calls the slot. Debounce is testable this way
too: several edits followed by one timeout must do the work exactly once.

## Simulating the referee

`setText` does not emit `textEdited`, so a handler that tells typed input from
values it wrote itself will not see it. Type instead:

```python
from PySide6.QtTest import QTest

edit.clear()
QTest.keyClicks(edit, "30")
```

## Asserting that no dialog appears

Replace the dialog with a raiser rather than a no-op, and the test fails if
the code ever tries to open one:

```python
monkeypatch.setattr(mw.QMessageBox, "warning", _fail)
```

## Checking a layout

The offscreen platform still renders, so a layout change can be checked as an
image instead of by eye:

```python
w.resize(1400, 900)
w.show()
app.processEvents()
w.grab().save("window.png")
```

Keep it as a scratch script writing outside the repository, not as a test.
