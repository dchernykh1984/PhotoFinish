"""Choosing the cameras to export and the job that writes them (specs/011)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.widgets import export_dialog
from tests.conftest import wait_until
from tests.test_export import START, record

Heard = list[tuple[list[Path], str, int]]


def finished(job: export_dialog.ExportJob) -> Heard:
    heard: Heard = []
    job.done.connect(
        lambda written, error, skipped: heard.append((written, error, skipped))
    )
    return heard


def wait(heard: Heard) -> None:
    """The signals come through Qt's events, the job's thread being another."""
    wait_until(lambda: bool(heard))


def test_every_camera_is_ticked_at_first_and_those_left_ticked_are_chosen() -> None:
    dialog = export_dialog.ExportChoice(None, {"cam1": "Main", "cam2": "Tele"})
    assert dialog.chosen() == ["cam1", "cam2"]
    dialog.ticks["cam1"].setChecked(False)
    assert dialog.chosen() == ["cam2"]


def test_the_job_writes_each_camera_and_says_how_far_it_is(tmp_path: Path) -> None:
    record(tmp_path / "cam1", START, 40)
    record(tmp_path / "cam2", START, 40)
    jobs = [(tmp_path / c, tmp_path / f"{c}.mp4") for c in ("cam1", "cam2")]
    job = export_dialog.ExportJob(jobs)
    steps: list[int] = []
    job.progress.connect(steps.append)
    heard = finished(job)
    job.start()
    wait(heard)
    assert heard == [([tmp_path / "cam1.mp4", tmp_path / "cam2.mp4"], "", 0)]
    assert steps[-1] == export_dialog.STEPS
    assert steps == sorted(steps)


def test_a_job_cancelled_says_so_and_one_that_fails_says_why(tmp_path: Path) -> None:
    record(tmp_path / "cam1", START, 40)
    job = export_dialog.ExportJob([(tmp_path / "cam1", tmp_path / "a.mp4")])
    heard = finished(job)
    job.cancel()
    job.start()
    wait(heard)
    assert heard == [([], export_dialog.CANCELLED, 0)]
    gone = export_dialog.ExportJob([(tmp_path / "cam1", tmp_path / "no" / "a.mp4")])
    failed = finished(gone)
    gone.start()
    wait(failed)
    assert failed[0][0] == [] and failed[0][1]


def test_a_job_tells_whatever_fails_never_leaving_the_window_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> list[Path]:
        raise IndexError("list index out of range")

    monkeypatch.setattr(export_dialog.export, "export", broken)
    job = export_dialog.ExportJob([(tmp_path, tmp_path / "a.mp4")])
    heard = finished(job)
    job.start()
    wait(heard)
    assert heard == [([], "a: list index out of range", 0)]


def test_a_camera_that_fails_is_told_and_the_next_still_exported(
    tmp_path: Path,
) -> None:
    record(tmp_path / "cam2", START, 40)
    jobs = [
        (tmp_path / "cam2", tmp_path / "missing" / "Main.mp4"),  # no such folder
        (tmp_path / "cam2", tmp_path / "Tele.mp4"),
    ]
    job = export_dialog.ExportJob(jobs)
    heard = finished(job)
    job.start()
    wait(heard)
    ((written, error, _),) = heard
    assert written == [tmp_path / "Tele.mp4"]
    assert error.startswith("Main: ")


def test_a_job_stopped_as_the_program_closes_leaves_no_file_half_written(
    tmp_path: Path,
) -> None:
    record(tmp_path / "cam1", START, 70)
    job = export_dialog.ExportJob([(tmp_path / "cam1", tmp_path / "Side.mp4")])
    job.stop(5)  # before it starts: nothing written
    job.start()
    job.stop(5)
    assert not list(tmp_path.glob("Side*.part"))
