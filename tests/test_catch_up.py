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


def test_no_estimate_while_the_phone_falls_behind_again_within_the_minute() -> None:
    catch_up = Heard()
    for s in range(41):  # 50 s held, falling to 20 s over 40 s
        catch_up.line(said(50_000 - 750 * s, 1_000 * s))
    line = ""
    for s in range(1, 20):  # then rising 0.9 s a second: a minute's fall hides it
        line = catch_up.line(said(20_000 + 900 * s, 40_000 + 1_000 * s))
    assert line.endswith("%")


def test_the_peak_is_forgotten_once_the_phone_is_live_again() -> None:
    catch_up = Heard()
    catch_up.line(said(600_000, 0))
    assert catch_up.line(said(1_000, 9_000)) == ""
    assert catch_up.line(said(60_000, 10_000)).startswith(
        f"1:00 of video on the phone {EMPTY * 10} 0%"
    )


def test_a_short_break_while_catching_up_keeps_the_bar_of_the_long_one() -> None:
    catch_up = Heard()
    catch_up.line(said(120_000, 0))
    catch_up.line(said(40_000, 160_000))  # two thirds come
    line = catch_up.line(said(43_000, 164_000))  # a Wi-Fi hiccup of 3 s
    assert line.startswith(f"0:43 of video on the phone {FULL * 6}{EMPTY * 4} 64%")


def test_a_clock_set_back_begins_the_minute_looked_back_on_again() -> None:
    catch_up = Heard()
    catch_up.line(said(600_000, 3_700_000))
    catch_up.line(said(540_000, 3_730_000))
    back = 130_000  # this computer's clock set back an hour
    catch_up.line(said(530_000, back))
    assert catch_up.line(said(500_000, back + 15_000)).endswith(", in about 5 min")


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


def test_a_new_break_after_catching_up_a_while_measures_the_bar_anew() -> None:
    catch_up = Heard()
    catch_up.line(said(600_000, 0))
    catch_up.line(said(5_000, 300_000))  # nearly caught up
    line = catch_up.line(said(240_000, 360_000))  # a new break, four minutes held
    assert line.startswith(f"4:00 of video on the phone {EMPTY * 10} 0%")
