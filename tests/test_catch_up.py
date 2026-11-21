"""What a phone still holds for a camera, as its line says it (specs/009)."""

from __future__ import annotations

from app.catch_up import EMPTY, FULL, CatchUp, span


def said(held: int, heard: int) -> dict[str, str]:
    return {"unsent_ms": str(held), "heard_ms": str(heard)}


class Heard(CatchUp):
    """Heard as each status comes, never stale: the line's own tests."""

    def line(self, status: object, now_ms: int | None = None) -> str:
        heard = status.get("heard_ms", "0") if isinstance(status, dict) else "0"
        return super().line(status, int(float(heard)) if now_ms is None else now_ms)


def test_little_or_nothing_held_says_nothing() -> None:
    catch_up = Heard()
    assert catch_up.line(None) == ""
    assert catch_up.line({}) == ""
    assert catch_up.line(said(1_999, 0)) == ""
    assert catch_up.line({"unsent_ms": "nan", "heard_ms": "1"}) == ""
    assert catch_up.line({"unsent_ms": "lots", "heard_ms": "1"}) == ""


def test_the_bar_fills_with_what_came_since_the_phone_began_falling_behind() -> None:
    catch_up = Heard()
    assert (
        catch_up.line(said(400_000, 0)) == f"6:40 of video on the phone {EMPTY * 10} 0%"
    )
    assert catch_up.line(said(600_000, 1_000)).startswith(
        f"10:00 of video on the phone {EMPTY * 10} 0%"
    )
    line = catch_up.line(said(150_000, 61_000))
    assert line.startswith(f"2:30 of video on the phone {FULL * 8}{EMPTY * 2} 75%")


def test_while_it_catches_up_the_line_says_about_when_the_rest_is_in() -> None:
    catch_up = Heard()
    catch_up.line(said(600_000, 0))
    # 60 s of video sent in 30 s more than taken: the 540 s left in about 270 s
    assert catch_up.line(said(540_000, 30_000)).endswith(", in about 5 min")
    catch_up.line(said(90_000, 280_000))
    assert catch_up.line(said(30_000, 315_000)).endswith(", in under a minute")
    catch_up.line(said(30_000, 400_000))
    assert catch_up.line(said(40_000, 430_000)).endswith("%")  # falling behind again


def test_the_peak_is_forgotten_once_the_phone_is_live_again() -> None:
    catch_up = Heard()
    catch_up.line(said(600_000, 0))
    assert catch_up.line(said(1_000, 9_000)) == ""
    assert catch_up.line(said(60_000, 10_000)).startswith(
        f"1:00 of video on the phone {EMPTY * 10} 0%"
    )


def test_a_span_reads_as_a_clock() -> None:
    assert span(0) == "0:00"
    assert span(59_999) == "0:59"
    assert span(3_723_000) == "1:02:03"
    assert span(-1) == "0:00"


def test_a_phone_gone_quiet_is_told_as_last_heard_with_no_estimate() -> None:
    catch_up = CatchUp()
    catch_up.line(said(600_000, 0), 0)
    catch_up.line(said(540_000, 30_000), 30_000)
    assert catch_up.line(said(540_000, 30_000), 30_000).endswith("in about 5 min")
    assert catch_up.line(said(540_000, 30_000), 36_000).endswith("10%, as last heard")
