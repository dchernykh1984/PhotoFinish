"""Choosing the cameras to export and the job that writes them (specs/011)."""

from __future__ import annotations

from pathlib import Path

from app.widgets import export_dialog
from tests.conftest import wait_until
from tests.test_export import START, record


def finished(job: export_dialog.ExportJob) -> list[tuple[list[Path], str]]:
    heard: list[tuple[list[Path], str]] = []
    job.done.connect(lambda written, error: heard.append((written, error)))
    return heard


def wait(heard: list[tuple[list[Path], str]]) -> None:
    """The signals come through Qt's events, the job's thread being another."""
    wait_until(lambda: bool(heard))


def test_every_camera_is_ticked_at_first_and_those_left_ticked_are_chosen() -> None:
    dialog = export_dialog.ExportChoice(None, {"cam1": "Main", "cam2": "Tele"})
    assert dialog.chosen() == ["cam1", "cam2"]
    dialog.ticks["cam1"].setChecked(False)
    assert dialog.chosen() == ["cam2"]


def test_a_camera_s_name_becomes_a_file_s() -> None:
    assert export_dialog.file_name('Mi 17: main/"wide"') == "Mi 17_ main_wide_"
    assert export_dialog.file_name("...") == "camera"


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
    assert heard == [([tmp_path / "cam1.mp4", tmp_path / "cam2.mp4"], "")]
    assert steps[-1] == export_dialog.STEPS
    assert steps == sorted(steps)


def test_a_job_cancelled_says_so_and_one_that_fails_says_why(tmp_path: Path) -> None:
    record(tmp_path / "cam1", START, 40)
    job = export_dialog.ExportJob([(tmp_path / "cam1", tmp_path / "a.mp4")])
    heard = finished(job)
    job.cancel()
    job.start()
    wait(heard)
    assert heard == [([], export_dialog.CANCELLED)]
    gone = export_dialog.ExportJob([(tmp_path / "cam1", tmp_path / "no" / "a.mp4")])
    failed = finished(gone)
    gone.start()
    wait(failed)
    assert failed[0][0] == [] and failed[0][1]
