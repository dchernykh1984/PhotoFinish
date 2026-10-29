"""The build workflow and the app must agree on what the app is called.

Nothing else ties the two together: the workflow stamps the name into the
macOS bundle and the app sets the same name on the Qt application. Sibling
apps once showed the packaged file name in the dock because the two drifted
apart unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.main import _APP_NAME

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"


def _workflow_env(name: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(rf"^  {re.escape(name)}: *(\S.*?) *$", text, re.MULTILINE)
    assert match is not None, f"{name} is not set in {WORKFLOW.name}"
    return match.group(1)


def _project_name() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^name *= *"(.+?)"', text, re.MULTILINE)
    assert match is not None, "pyproject.toml has no project name"
    return match.group(1)


def test_the_build_collects_pyav_and_onnxruntime_with_their_libraries() -> None:
    # PyAV bundles FFmpeg's shared libraries, onnxruntime its runtime: a frozen app
    # without them cannot record, or find riders with a model.
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--collect-all av" in text
    assert "--collect-all onnxruntime" in text


def test_the_build_records_the_test_camera_with_the_frozen_app() -> None:
    # The recorder is the frozen app itself: every platform's build must record.
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"$app" --recorder smoke &' in text
    assert '"connection": "test"' in text
    assert "stop.request" in text


def test_workflow_bundle_name_matches_the_app() -> None:
    # macOS shows the .app folder name in the dock and ignores the plist's
    # CFBundleName/CFBundleDisplayName, so the bundle name *is* the dock name.
    # It has to stay space-free, hence the app's name with spaces removed.
    assert _workflow_env("APP_BUNDLE_NAME") == _APP_NAME.replace(" ", "")


def test_workflow_bundle_name_has_no_spaces() -> None:
    # The bundle is a file people copy between competition folders; spaces in
    # it make every shell command that touches it need quoting.
    assert " " not in _workflow_env("APP_BUNDLE_NAME")


def test_workflow_bundle_id_is_reverse_dns_for_this_project() -> None:
    # Copied between six sibling repos, so pin it to this project's own name -
    # a bundle id left pointing at a sibling would silently make macOS treat
    # the two apps as one.
    bundle_id = _workflow_env("APP_BUNDLE_ID")
    assert re.fullmatch(r"[a-z0-9]+(\.[a-z0-9-]+)+", bundle_id), bundle_id
    assert bundle_id.rsplit(".", 1)[-1] == _project_name()
