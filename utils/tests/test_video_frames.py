"""Unit tests for the screen-recording contact-sheet tool.

The arithmetic is the part a wrong answer hides in: a label that is off by a
second still looks like a label, and the whole point of the tool is matching a
tile to a log line. So the time maths, the file-name parser and the ffmpeg
argument building are pinned on their own, and one end-to-end test runs the
real ffmpeg over a synthetic clip to prove the pieces are wired together.
"""

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
import video_frames
from PIL import Image

START = datetime(2026, 10, 23, 17, 7, 10)


@pytest.mark.parametrize(
    "name",
    [
        "Bildschirmaufnahme 2026-10-23 um 17.07.10.mov",
        "Screen Recording 2026-10-23 at 17.07.10.mov",
        "/Users/someone/Pictures/Bildschirmaufnahme 2026-10-23 um 17.07.10.mov",
    ],
)
def test_parse_start_reads_both_languages(name):
    """Both macOS locales yield the same start, with or without a directory."""
    assert video_frames.parse_start(name) == START


@pytest.mark.parametrize(
    "name",
    [
        "walkthrough.mov",
        "Bildschirmaufnahme 2026-10-23 17.07.10.mov",
        "Screen Recording 2026-13-45 at 17.07.10.mov",
        "Screenshot 2026-10-23 at 17.07.10.png",
    ],
)
def test_parse_start_refuses_anything_else(name):
    """No guessing: other names, malformed ones and impossible dates give None."""
    assert video_frames.parse_start(name) is None


def test_parse_start_keeps_seconds_precision():
    """The seconds field survives, and no sub-second part is invented."""
    got = video_frames.parse_start("Screen Recording 2026-01-02 at 03.04.59.mov")
    assert got is not None
    assert (got.year, got.month, got.day) == (2026, 1, 2)
    assert (got.hour, got.minute, got.second, got.microsecond) == (3, 4, 59, 0)
    assert got.tzinfo is None


def test_tile_times_follow_window_and_fps():
    """Tiles start at `from`, step by 1/fps, and stop before `to`."""
    assert video_frames.tile_times(0, 3, 1) == [0, 1, 2]
    assert video_frames.tile_times(10, 11, 4) == [10, 10.25, 10.5, 10.75]
    assert video_frames.tile_times(0, 1.5, 2) == [0, 0.5, 1.0]
    assert video_frames.tile_times(5, 5, 1) == []


def test_tile_times_are_not_fooled_by_float_error():
    """0.1 * 3 is 0.30000000000000004 s: at 10 fps that is three tiles, not four."""
    end = 0.1 * 3
    assert end * 10 > 3  # the premise: a bare ceil() would count a fourth tile
    assert len(video_frames.tile_times(0, end, 10)) == 3


def test_wall_clock_adds_offset_to_start():
    """17:07:10 + 12.5 s is 17:07:22.5, and the minute carries."""
    assert video_frames.wall_clock(START, 12.5) == "17:07:22.5"
    assert video_frames.wall_clock(START, 55) == "17:08:05.0"


def test_wall_clock_carries_when_rounding_reaches_a_whole_second():
    """0.96 s rounds to a full second instead of printing `.10`."""
    assert video_frames.wall_clock(START, 0.96) == "17:07:11.0"


def test_label_for_with_and_without_start():
    """The wall clock appears only when the start time is known."""
    assert video_frames.label_for(12.5, None) == "t=12.5s"
    assert video_frames.label_for(12.5, START) == "t=12.5s  17:07:22.5"
    assert video_frames.label_for(0.25, START, 2) == "t=0.25s  17:07:10.25"


def test_decimals_grow_with_the_frame_rate():
    """Above 10 fps one decimal cannot tell neighbouring tiles apart, nor two above 100."""
    assert video_frames.decimals_for(0.5) == 1
    assert video_frames.decimals_for(10) == 1
    assert video_frames.decimals_for(30) == 2
    assert video_frames.decimals_for(120) == 3


@pytest.mark.parametrize("t", [0.05, 0.15, 0.25, 1.05, 12.35, 0.03, 59.995])
@pytest.mark.parametrize("decimals", [1, 2])
def test_both_halves_of_a_label_agree_on_the_fraction(t, decimals):
    """`t=` and the wall clock round once, so they never name different fractions."""
    label = video_frames.label_for(t, START, decimals)
    shown_t = label.split("s")[0].split("=")[1]
    shown_clock = label.rsplit(".", 1)[1]
    assert shown_t.rsplit(".", 1)[1] == shown_clock


def test_parse_crop_accepts_four_integers():
    """`W:H:X:Y` becomes a Crop."""
    assert video_frames.parse_crop("200:100:30:40") == video_frames.Crop(200, 100, 30, 40)


@pytest.mark.parametrize("text", ["200:100:30", "a:b:c:d", "0:100:0:0", "10:10:-1:0", "1:2:3:4:5"])
def test_parse_crop_rejects_malformed(text):
    """Wrong arity, non-numbers, an empty size and a negative origin all fail."""
    with pytest.raises(argparse.ArgumentTypeError, match="W:H:X:Y"):
        video_frames.parse_crop(text)


def test_crop_fits_is_inclusive_of_the_far_edge():
    """A rectangle ending exactly on the frame edge fits; one pixel more does not."""
    crop = video_frames.Crop(10, 10, 54, 38)
    assert crop.fits(64, 48)
    assert not crop.fits(63, 48)
    assert not crop.fits(64, 47)


def test_video_filter_retimes_samples_crops_scales():
    """Order matters: re-time, sample on the grid, crop in source pixels, then scale."""
    crop = video_frames.Crop(200, 100, 30, 40)
    assert video_frames.video_filter(2, crop, 600, 1.5) == (
        "setpts=PTS-1.500000/TB,fps=2:start_time=0:round=up,crop=200:100:30:40:exact=1,scale=600:-2"
    )
    assert video_frames.video_filter(0.5, None, None, 0) == (
        "setpts=PTS-0.000000/TB,fps=0.5:start_time=0:round=up"
    )


def test_sheet_layout_pages_by_height():
    """Tiles that overflow the height cap continue on a further sheet."""
    assert video_frames.sheet_layout(tile_h=400, cols=5, count=20) == (10, 1)
    assert video_frames.sheet_layout(tile_h=2000, cols=2, count=5) == (2, 2)
    assert video_frames.sheet_layout(tile_h=9000, cols=1, count=3) == (1, 3)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
@pytest.mark.parametrize("flag", ["--at", "--fps", "--from"])
def test_non_finite_numbers_are_refused_by_the_parser(flag, value, capsys):
    """A nan or an infinity would reach ffmpeg or the tile arithmetic; argparse stops it."""
    command = "frame" if flag == "--at" else "sheet"
    with pytest.raises(SystemExit) as exc:
        video_frames.build_parser().parse_args([command, "x", f"{flag}={value}"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "finite" in err or "negative" in err


def _fake_probe(monkeypatch, payload):
    """Make `probe` see `payload` as ffprobe's JSON."""
    done = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
    monkeypatch.setattr(video_frames, "_run", lambda cmd: done)


def test_probe_refuses_a_file_without_a_video_stream(monkeypatch):
    """An audio-only file has no `streams[0]`; that is an error, not an IndexError."""
    _fake_probe(monkeypatch, {"streams": [], "format": {"duration": "1.0"}})
    with pytest.raises(SystemExit, match="no video stream"):
        video_frames.probe(Path("a.wav"))


def test_probe_refuses_a_file_without_a_duration(monkeypatch):
    """Neither the stream nor the container names a duration."""
    stream = {"width": 4, "height": 4, "avg_frame_rate": "10/1", "duration": "N/A"}
    _fake_probe(monkeypatch, {"streams": [stream], "format": {}})
    with pytest.raises(SystemExit, match="no usable duration"):
        video_frames.probe(Path("a.mov"))


def test_probe_prefers_the_stream_duration_and_survives_a_zero_frame_rate(monkeypatch):
    """The video stream's duration wins over the container's; 0/0 means unknown rate."""
    stream = {
        "width": 4,
        "height": 4,
        "avg_frame_rate": "0/0",
        "duration": "2.0",
        "start_time": "0.5",
    }
    _fake_probe(monkeypatch, {"streams": [stream], "format": {"duration": "9.0"}})
    info = video_frames.probe(Path("a.mov"))
    assert (info.duration, info.fps, info.first_pts) == (2.0, None, 0.5)


def test_warnings_keep_decode_errors_and_drop_the_scaler_notice():
    """A damaged input's messages survive; the per-frame scaler chatter does not."""
    stderr = (
        "[swscaler @ 0x1] No accelerated colorspace conversion found from yuv420p to rgb24.\n"
        "[h264 @ 0x2] error while decoding MB 3 4\n\n"
    )
    assert video_frames._warnings(stderr) == "[h264 @ 0x2] error while decoding MB 3 4"
    assert video_frames._warnings("") == ""


def test_probe_reports_a_missing_tool_cleanly(monkeypatch):
    """A binary that is not installed is a one-line error naming it."""

    def boom(*_args, **_kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(video_frames.subprocess, "run", boom)
    with pytest.raises(SystemExit, match="ffprobe not found on PATH"):
        video_frames.probe(Path("a.mov"))


def test_main_refuses_a_missing_input():
    """A path that is not a file stops before any tool runs."""
    with pytest.raises(SystemExit, match="no such file"):
        video_frames.main(["probe", "/nonexistent/clip.mov"])


needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)

# Frame N of the clip below sits at N/10 s and carries luma 16 + 3N, so a tile's
# pixels name the source frame they show. Frames 9..29 do not exist: a 2.1 s gap,
# which is how a macOS recording looks while the screen holds still.
KEPT = [*range(0, 9), *range(30, 60)]


def _band(width):
    return 2 * video_frames.label_size(width)


def _shown_frame(img, x, y):
    """The source frame number whose luma the pixel at (x, y) carries.

    ffmpeg converts yuv420p to RGB with limited-range scaling, so a grey of g
    came from a luma of 16 + g * 219 / 255.
    """
    grey = img.convert("L").getpixel((x, y))
    return round(grey * 219 / 255 / 3)


def _on_screen_at(t):
    """The last kept frame at or before `t`: what the screen showed then."""
    return max(n for n in KEPT if n / 10 <= t + 1e-9)


@pytest.fixture
def clip(tmp_path):
    """A 6 s, 64x48, variable-frame-rate lossless clip named like a macOS recording."""
    path = tmp_path / "Screen Recording 2026-10-23 at 17.07.10.mkv"
    graph = (
        "color=c=black:s=64x48:r=10:d=6,format=yuv420p,geq=lum='16+N*3':cb=128:cr=128,"
        "select='not(between(t\\,0.9\\,2.95))'"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            graph,
            "-fps_mode",
            "vfr",
            "-c:v",
            "ffv1",
            str(path),
        ],
        check=True,
    )
    return path


def _cli(*args):
    assert video_frames.main([str(a) for a in args]) == 0


@needs_ffmpeg
@pytest.mark.parametrize(("start", "fps"), [(0, 2), (1, 2), (1.25, 2), (2, 1), (2.5, 4), (0.3, 4)])
def test_every_tile_shows_the_frame_its_label_names(clip, tmp_path, start, fps):
    """Across a gap, at any window start, a tile holds the frame on screen at its time."""
    out = tmp_path / "out"
    _cli(
        "sheet",
        clip,
        "--from",
        start,
        "--to",
        5,
        "--fps",
        fps,
        "--cols",
        4,
        "--width",
        64,
        "--out",
        out,
    )
    expected = video_frames.tile_times(start, 5, fps)
    assert len(expected) >= 3
    tile_h = 48 + _band(64)
    shown = []
    for sheet in sorted(out.glob("*.png")):
        with Image.open(sheet) as img:
            for i in range(img.width // 64 * (img.height // tile_h)):
                x, y = (i % 4) * 64, (i // 4) * tile_h
                shown.append(_shown_frame(img, x + 5, y + 5))
    # the last sheet's unused cells are background; only the tiles count
    assert shown[: len(expected)] == [_on_screen_at(t) for t in expected]


@needs_ffmpeg
@pytest.mark.parametrize(("at", "frame"), [(0.95, 8), (2.0, 8), (3.0, 30), (3.05, 30), (5.9, 59)])
def test_frame_shows_what_was_on_screen_at_the_time(clip, tmp_path, at, frame):
    """`frame --at` inside a gap returns the frame before it, not the one after."""
    out = tmp_path / "out"
    _cli("frame", clip, "--at", at, "--out", out)
    (png,) = out.glob("*.png")
    with Image.open(png) as img:
        assert img.size == (64, 48 + _band(64))
        assert _shown_frame(img, 5, 5) == frame


@needs_ffmpeg
def test_sheet_labels_carry_time_and_wall_clock(clip, tmp_path, monkeypatch):
    """The text drawn on each tile is the offset into the video and the wall clock."""
    seen = []
    real = video_frames.labelled
    monkeypatch.setattr(
        video_frames, "labelled", lambda img, text: (seen.append(text), real(img, text))[1]
    )
    _cli("sheet", clip, "--from", 1, "--to", 3, "--fps", 2, "--out", tmp_path / "out")
    assert seen == [
        "t=1.0s  17:07:11.0",
        "t=1.5s  17:07:11.5",
        "t=2.0s  17:07:12.0",
        "t=2.5s  17:07:12.5",
    ]


@needs_ffmpeg
def test_sheet_continues_on_further_sheets_and_replaces_its_own_leftovers(
    clip, tmp_path, monkeypatch, capsys
):
    """Past the height cap tiles flow onto -02, -03; a rerun with fewer sheets removes the spare."""
    monkeypatch.setattr(video_frames, "MAX_SHEET_HEIGHT", 100)
    out = tmp_path / "out"
    common = ["sheet", clip, "--from", 0, "--to", 3, "--fps", 2, "--width", 64, "--out", out]
    _cli(*common, "--cols", 2)
    names = capsys.readouterr().out.splitlines()
    assert [Path(n).name[-7:] for n in names] == ["-01.png", "-02.png", "-03.png"]
    for n in names:
        with Image.open(n) as img:
            assert img.size == (2 * 64, 48 + _band(64))
    _cli(*common, "--cols", 3)
    assert [p.name[-7:] for p in sorted(out.glob("*.png"))] == ["-01.png", "-02.png"]


@needs_ffmpeg
def test_different_runs_do_not_overwrite_each_other(clip, tmp_path):
    """An overview and a zoom of the same recording sit side by side."""
    out = tmp_path / "out"
    _cli("sheet", clip, "--fps", 1, "--out", out)
    _cli("sheet", clip, "--from", 1, "--to", 3, "--fps", 4, "--crop", "20:20:4:4", "--out", out)
    assert len(list(out.glob("*.png"))) == 2


@needs_ffmpeg
def test_stale_cleanup_ignores_glob_characters_in_the_name(tmp_path):
    """A stem with `[` must neither survive its own cleanup nor reach another file."""
    path = tmp_path / "rec [1].mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=32x32:r=5:d=2", str(path)],
        check=True,
    )
    other = tmp_path / "out" / "rec 1-sheet-0-2.000s-1fps-01.png"
    other.parent.mkdir()
    other.write_bytes(b"keep")
    _cli("sheet", path, "--fps", 1, "--out", other.parent)
    _cli("sheet", path, "--fps", 1, "--out", other.parent)
    assert other.read_bytes() == b"keep"
    assert sorted(p.name for p in other.parent.iterdir()) == [
        "rec 1-sheet-0-2.000s-1fps-01.png",
        "rec [1]-sheet-0-2.000s-1fps-01.png",
    ]


@needs_ffmpeg
def test_crop_keeps_odd_values_exact(clip, tmp_path):
    """11x11 at an odd offset comes out 11 wide, not rounded to even."""
    out = tmp_path / "out"
    _cli("frame", clip, "--at", 1, "--crop", "11:11:3:5", "--out", out)
    (png,) = out.glob("*.png")
    with Image.open(png) as img:
        assert img.size == (11, 11 + _band(11))


@needs_ffmpeg
@pytest.mark.parametrize("crop", ["70:10:0:0", "10:10:60:0", "10:10:0:40"])
def test_crop_outside_the_frame_is_an_error(clip, tmp_path, crop):
    """A rectangle past the 64x48 frame is refused, not clamped by ffmpeg."""
    with pytest.raises(SystemExit, match="outside"):
        _cli("frame", clip, "--at", 1, "--crop", crop, "--out", tmp_path / "out")


@needs_ffmpeg
def test_windows_past_the_end_are_errors_or_noted(clip, tmp_path, capsys):
    """`--from` and `--at` beyond the video fail; `--to` beyond it is clamped with a note."""
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="empty window"):
        _cli("sheet", clip, "--from", 9, "--out", out)
    with pytest.raises(SystemExit, match="no frame at 9"):
        _cli("frame", clip, "--at", 9, "--out", out)
    capsys.readouterr()
    _cli("sheet", clip, "--from", 5, "--to", 99, "--out", out)
    assert "past the video's end" in capsys.readouterr().err


@needs_ffmpeg
def test_probe_of_audio_only_and_garbage_files_is_a_clean_error(tmp_path):
    """No traceback for a file ffprobe cannot read a video stream from."""
    wav = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1", str(wav)], check=True)
    with pytest.raises(SystemExit, match="no video stream"):
        video_frames.main(["probe", str(wav)])
    junk = tmp_path / "junk.mov"
    junk.write_text("not a video")
    with pytest.raises(SystemExit, match="ffprobe failed"):
        video_frames.main(["probe", str(junk)])


@needs_ffmpeg
def test_probe_prints_the_start_time_from_the_name(clip, capsys):
    """`probe` reports size, duration and the start parsed from the file name."""
    _cli("probe", clip)
    out = capsys.readouterr().out
    assert "64 x 48" in out
    assert "2026-10-23 17:07:10" in out


@needs_ffmpeg
def test_default_output_never_lands_next_to_the_input(clip, tmp_path, monkeypatch, capsys):
    """Without --out the files go under $TMPDIR/video-frames/<stem>/."""
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(video_frames.tempfile, "tempdir", str(scratch))
    before = sorted(p.name for p in clip.parent.iterdir())
    _cli("frame", clip, "--at", 0.5)
    path = capsys.readouterr().out.strip()
    assert path.startswith(str((scratch / "video-frames" / clip.stem).resolve()))
    assert sorted(p.name for p in clip.parent.iterdir()) == before


@pytest.fixture
def offset_clip(clip, tmp_path):
    """The same clip with its timeline moved to start at 1.0 s (stream start_time 1.0)."""
    path = tmp_path / "Screen Recording 2026-10-23 at 18.00.00.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(clip),
            "-c",
            "copy",
            "-output_ts_offset",
            "1.0",
            str(path),
        ],
        check=True,
    )
    return path


@needs_ffmpeg
def test_a_stream_that_does_not_start_at_zero_is_sampled_on_its_own_timeline(offset_clip, tmp_path):
    """Times are relative to the stream's start; dropping `first_pts` shifts every tile."""
    assert video_frames.probe(offset_clip).first_pts == pytest.approx(1.0)
    out = tmp_path / "out"
    _cli(
        "sheet",
        offset_clip,
        "--from",
        1.25,
        "--to",
        5,
        "--fps",
        2,
        "--cols",
        4,
        "--width",
        64,
        "--out",
        out,
    )
    expected = video_frames.tile_times(1.25, 5, 2)
    tile_h = 48 + _band(64)
    shown = []
    for sheet in sorted(out.glob("*.png")):
        with Image.open(sheet) as img:
            for i in range(img.width // 64 * (img.height // tile_h)):
                shown.append(_shown_frame(img, (i % 4) * 64 + 5, (i // 4) * tile_h + 5))
    assert shown[: len(expected)] == [_on_screen_at(t) for t in expected]


@needs_ffmpeg
def test_container_duration_fallback_is_on_the_stream_timeline(offset_clip):
    """A container span of 1 + 6 s is a 6 s stream, not a 7 s one with a frozen tail."""
    assert video_frames.probe(offset_clip).duration == pytest.approx(6.0, abs=0.01)


def _stream_with_late_first_frame(monkeypatch, first_packet):
    stream = {
        "width": 4,
        "height": 4,
        "avg_frame_rate": "10/1",
        "duration": "5.0",
        "start_time": "0.0",
    }
    payload = {
        "streams": [stream],
        "packets": [{"pts_time": str(first_packet)}, {"pts_time": "3.5"}],
    }
    _fake_probe(monkeypatch, payload)
    return video_frames.probe(Path("a.mov"))


def test_a_first_frame_later_than_the_stream_start_is_reported(monkeypatch):
    """Slots before the first frame repeat it; the window opening there says so."""
    info = _stream_with_late_first_frame(monkeypatch, 2.5)
    assert info.lead == pytest.approx(2.5)
    note = video_frames.lead_note(info, 1.0)
    assert note is not None
    assert "2.500" in note
    assert video_frames.lead_note(info, 2.5) is None
    assert video_frames.lead_note(info, 4.0) is None


def test_a_stream_that_starts_with_its_first_frame_has_no_lead(monkeypatch):
    """No note for the ordinary case."""
    info = _stream_with_late_first_frame(monkeypatch, 0.0)
    assert info.lead == 0.0
    assert video_frames.lead_note(info, 0.0) is None


def test_the_lead_note_reaches_stderr_from_sheet_and_frame(tmp_path, monkeypatch, capsys):
    """The warning is printed by both subcommands, before any sampling is attempted."""
    _stream_with_late_first_frame(monkeypatch, 2.5)
    video = tmp_path / "rec.mov"
    video.write_bytes(b"")

    def stop(*_args, **_kwargs):
        raise SystemExit("sampling reached")

    monkeypatch.setattr(video_frames, "_sample", stop)
    for argv in (["sheet", str(video)], ["frame", str(video), "--at", "1"]):
        with pytest.raises(SystemExit, match="sampling reached"):
            video_frames.main([*argv, "--out", str(tmp_path / "out")])
        assert "first frame is 2.500 s" in capsys.readouterr().err


def test_a_slot_mismatch_aborts_and_writes_nothing(tmp_path, monkeypatch):
    """Slots 0 and 2 from ffmpeg for a request of 4 are refused, with no output directory."""
    stream = {"width": 8, "height": 8, "avg_frame_rate": "10/1", "duration": "5.0"}
    probe_out = subprocess.CompletedProcess(
        [], 0, stdout=json.dumps({"streams": [stream]}), stderr=""
    )

    def fake(cmd):
        if cmd[0] == "ffprobe":
            return probe_out
        scratch = Path(cmd[-1]).parent
        for slot in (0, 2):
            Image.new("RGB", (8, 8)).save(scratch / f"{slot:06d}.png")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(video_frames, "_run", fake)
    video = tmp_path / "rec.mov"
    video.write_bytes(b"")
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match=r"slots \[0, 2\] where 0\.\.3 were expected"):
        video_frames.main(["sheet", str(video), "--to", "2", "--fps", "2", "--out", str(out)])
    assert not out.exists()


@needs_ffmpeg
def test_frame_names_do_not_collide_within_a_frame_interval(clip, tmp_path):
    """Two times 1 ms apart name two files."""
    out = tmp_path / "out"
    _cli("frame", clip, "--at", 1.001, "--out", out)
    _cli("frame", clip, "--at", 1.004, "--out", out)
    assert len(list(out.glob("*.png"))) == 2


def test_crop_refuses_to_exist_with_an_invalid_rectangle():
    """The invariant lives in the type, not only in the parser."""
    for args in [(0, 5, 0, 0), (5, 0, 0, 0), (5, 5, -1, 0), (5, 5, 0, -1)]:
        with pytest.raises(ValueError, match="crop needs"):
            video_frames.Crop(*args)


def test_probe_refuses_output_that_is_not_json(monkeypatch):
    """A broken ffprobe answer is a message, not a JSONDecodeError traceback."""
    done = subprocess.CompletedProcess([], 0, stdout="garbage", stderr="")
    monkeypatch.setattr(video_frames, "_run", lambda cmd: done)
    with pytest.raises(SystemExit, match="not JSON"):
        video_frames.probe(Path("a.mov"))
