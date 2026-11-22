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
QApplication.processEvents()  # static; no local named app, which is the package
w.grab().save("window.png")
```

Keep it as a scratch script writing outside the repository, not as a test.

The offscreen platform draws the Fusion style -- Windows' and Linux's sizes, a
push button never under 80 px -- on an 800x600 screen, where a dialog opens at
its least. For the macOS look, render with the platform macOS runs, off the
screen:

```python
os.environ["QT_QPA_PLATFORM"] = "cocoa"  # before QtWidgets is imported
w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
```

Look at the window at its smallest (`w.resize(100, 100)`): a field cut shows
there first.

## A wrapped label cut

A label with word wrap gets no more height than its minimum asks for wherever
its height for its width is left out: in a `QSplitter`'s part, and in a window
or dialog's least size, a layout's minimum leaving it out. Its text grown -- a
phone's lines, a lens's advice --, it is cut, or what is below it is pressed
under its own minimum: a QR code that does not scan, buttons a few pixels high.
Use `app/widgets/whole_label.WholeLabel`, which keeps its height for its width as
its minimum, and keep such a label out of a splitter's part. Test it at the
smallest size:

```python
w.resize(100, 100)
w.show()
QApplication.processEvents()
assert label.height() >= label.heightForWidth(label.width())
for button in w.findChildren(QPushButton):
    if button.isVisible():
        assert button.height() >= button.minimumSizeHint().height(), button.text()
```

A text that grows without bound on one row -- a path written out on a button --
pushes the window past the screen and leaves the fields beside it no room: name
the file, the path in the tip.

## Painting

Draw inside `with QPainter(self) as painter:`. A `paintEvent` that raises with
its painter open leaves the window's backing store painted on: Qt warns
`QBackingStore::endPaint() called with active painter`, and a later paint of the
window crashes it (SIGSEGV in `QBackingStore::flush`) -- 0.14.0 crashed so, twice
in an afternoon.

Qt takes integer coordinates in 32 bits: an x worked out from a moment far from
the view -- a stretch of a camera just removed, days of recording zoomed in on --
overflows them, and `fillRect(int, ...)` raises `OverflowError`. Cut a span to
the widget before drawing it, as the timeline's `_shown` does.

A `grab()` in a test paints within the call, and a paint that raises fails the
test with its error. `paintingActive()` says nothing of a painter left open on a
grab: keep the painter -- patch a method it is handed to -- and ask its
`isActive()`.

## When the window crashed

- `data/window.log` next to the program: each start, the Python errors no handler
  took, the stacks of a crash.
- On macOS, `~/Library/Logs/DiagnosticReports/PhotoFinish-*.ips` holds the native
  stack, and the system log the minutes before it, Qt's warnings among them:
  `/usr/bin/log show --style compact --start "<time>" --end "<time>" --predicate
  'processID == <pid>'` -- in zsh a bare `log` is a builtin that shows nothing.
