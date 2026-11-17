# Implementation Plan: What the phone hits, on the laptop

**Spec**: [spec.md](spec.md) | **Contract**: [../003-phone-camera-app/contracts/phone-stream.md](../003-phone-camera-app/contracts/phone-stream.md)

## Shape

```
android/.../diagnostics/PhoneLog.kt     the lines: numbered, cut, 20 a second, the last 1,000 kept
android/.../diagnostics/LogMessages.kt  a message of lines, the recorder's answer (contract)
android/.../diagnostics/LogSender.kt    each recorder sent what it has not answered, on one socket
android/.../diagnostics/ProcessLog.kt   the app's own part of the system log, warnings and errors (glue)
android/.../diagnostics/Crashes.kt      an error that ends the app kept for the next start
android/.../diagnostics/StatusLog.kt    what the screen shows, once a change
android/.../MainActivity.kt             the log made, its start line, the sender to the code's lenses (glue)
android/.../capture/CameraStreamer.kt   what is opened, the camera's error codes, exceptions (glue)
android/.../capture/LensStream.kt       an encoder that fails while streaming (glue)
app/recorder/phone_log.py               the lines kept in phone.log, the answer, the last word
app/recorder/clock_sync.py              a message that is not a clock exchange handed on
app/recorder/__init__.py                the phone's log beside the clock; its last word in the heartbeat
app/main_window.py                      the phone's last word in a camera's line that does not record
```

- **The clock exchange's port.** The recorder of a phone's lens already answers UDP on the lens's
  port while it runs, streaming or not; a log message is told from a clock exchange by its first
  four bytes. No port more, no server more, and no video connection needed: the log gets through
  while the camera fails.
- **Text, a line a line.** A message is `PFLG 1 <run>` and its lines, `<seq> <ms> <level> <lens>
  <text>`; the answer `PFLG 1 <run> <seq>`, the newest line kept. Readable on the wire and in
  the file, and the same few lines of code on both sides.
- **Sent again until answered.** The phone keeps, for each recorder, the newest line it answered;
  every second, and at once when there are new lines, it sends from the next one, as many as a
  message of 1,200 bytes holds. The recorder keeps a line only after the one before it, and passes
  over one it has: a lost message is sent again, none is written twice. A run it has not heard --
  the app started, or the recorder itself -- begins at the first line it gets, which is the oldest
  the phone has not had answered; lines of the run that never came are said not heard, lines the
  phone could no longer keep said lost. A recorder started again finds where it was from the file's
  last lines.
- **A recorder that answers nothing** -- an older PhotoFinish -- is sent to every 5 s after 10 s
  without an answer.
- **The app's own system log**: `logcat --pid` of the app's process at warning and above, the
  app's own tag left out: the camera's and the encoder's words to the app, without a call site for
  each.
- **The heartbeat** holds `phone_said`: the last warning or error of the camera's lens or of the
  phone as a whole, with when the recorder heard it.

## Tests

- JVM: the log (numbers, cut, the limit and its note, the last 1,000), the messages (a line a line,
  1,200 bytes at most, the answer), the sender (sent from the next unanswered, again until
  answered, slower when nothing answers), a system log line read, an error described, the status
  changes logged once.
- pytest: a message read and written, a line once, a run new or started again, lines not heard or
  lost, a message that is no message, the answer, the file kept at 10 MB, the heartbeat's last word;
  the responder handing a log message on.
- Qt: a camera that does not record shows its phone's last word; one that records does not.
- By hand: the emulator in tandem (SC-001, SC-002).
