"""Cut a screen recording into labelled contact sheets and single frames.

In-game walks of the mods here are checked from macOS screen recordings, and
the questions asked of them are about *when*: did the marker fade between two
frames, which tile is the moment a screenshot was taken. A plain `ffmpeg` tile
filter answers the first half and leaves the second to counting, so every tile
this tool writes carries its time into the video and, when the file name says
when the recording began, the wall-clock time of that frame -- the form a
screenshot's file name, another recording or a hand-kept note uses. (The game's
own `Player.log` has no per-line timestamps, so it is not something a tile can
be matched against by clock.)

Three subcommands: `probe` (what the file is), `sheet` (an overview grid over a
window, optionally of one cropped region at a high rate) and `frame` (one frame,
full resolution unless told otherwise).

Decisions:

- **A tile shows what was on screen at the time its label names.** macOS writes
  a frame only when the picture changes, so a recording is variable-frame-rate
  with gaps of a second and more, and "the frame nearest the time" or "the first
  frame after a seek" are both wrong in a gap: they show the *next* picture
  under the label of the previous one. The sampler therefore takes, for every
  slot, the last frame at or before it (`fps=...:round=up`), starts decoding at
  the keyframe before the window (`-noaccurate_seek -copyts`) so that frame
  exists when the window opens in a static stretch, and shifts time so slot 0 is
  exactly `--from` (`setpts`). Each tile is then labelled from the number of the
  file ffmpeg wrote for it, never from its position in a list, and a count that
  differs from the expected one is an error instead of being trimmed to fit.
- **Labels are drawn with Pillow.** The Homebrew `ffmpeg` here is built without
  freetype, so its `drawtext` filter does not exist. ffmpeg only extracts and
  crops; composing and lettering happen here.
- **The band goes below the picture, not over it.** A label laid on the tile
  hides the pixels of a region someone is about to inspect. A tile is therefore
  `--width` wide and its picture's height plus a band tall.
- **A sheet is capped near 4000 px of height** and the tiles continue on the next
  sheet (`...-01.png`, `-02`, ...). Past about that, a viewer downscales the
  image to fit its window and the tiles stop being readable while the file stays
  huge. A single tile taller than the cap gets a sheet of its own row. Width is
  `cols` x `--width` and is the caller's choice.
- **Sheet names say what made them**: `<stem>-sheet-<from>-<to>s-<fps>fps[-crop-
  WxH+X+Y]-NN.png`, so an overview and a zoom on the same recording sit side by
  side. Repeating the identical run replaces its own sheets (and removes
  leftovers of a longer earlier run with that exact name); nothing else is
  touched. `--width` and `--cols` are not part of the name.
- **The start time comes from the file name only.** macOS names a recording
  `Bildschirmaufnahme YYYY-MM-DD um HH.MM.SS.mov` or `Screen Recording
  YYYY-MM-DD at HH.MM.SS.mov`, local time, when it began. Anything else yields
  no wall clock. The modification time is not a substitute: it is when the file
  was last written, which for a copied or trimmed recording is neither the start
  nor the end, and a plausible wrong time is worse than none.
- **The wall clock is only as exact as that name.** The name carries whole
  seconds and the stamp is taken around the start of capture, so the base is good
  to about a second; the decimals after the point are the tile's own offset into
  the video and make tiles distinguishable, they do not make the clock finer.
- **`scale=W:-2`** keeps the aspect ratio and rounds the height to an even
  number, so tile sizes are tidy; PNG itself does not require it. A crop is
  `exact=1` so odd values mean what they say rather than being rounded down to
  even, and it is checked against the probed frame size -- ffmpeg would
  otherwise clamp an out-of-frame rectangle into the picture without a word.
- **The video stream's own duration bounds the window** when it has one, not
  the container's: an audio track that outlasts the picture would otherwise
  yield tiles of a frozen last frame. A stream without a duration (Matroska,
  for one) falls back to the container's, less the stream's start offset, with
  a note on stderr.
- **Slots before the first frame repeat it.** If the first frame lies later
  than the stream's start time, `fps` has nothing earlier to show and fills
  those slots with that first frame. ffprobe's first packets are enough to see
  it, so the tool says so on stderr, naming the lead; it does not change the
  sampling. A stream that starts at its first frame, which is every recording
  looked at here, never triggers it.
- **Output never goes next to the input by default.** The default is
  `$TMPDIR/video-frames/<input stem>/`; `--out` overrides it and is the one way
  output lands anywhere else. Every file written is printed as an absolute path.

Usage:
    uv run utils/video_frames.py probe VIDEO
    uv run utils/video_frames.py sheet VIDEO [--from S] [--to S] [--fps N]
        [--cols C] [--width W] [--crop W:H:X:Y] [--out DIR]
    uv run utils/video_frames.py frame VIDEO --at S [--crop W:H:X:Y] [--width W]
        [--out DIR]
"""

import argparse
import glob
import json
import math
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from fractions import Fraction
from pathlib import Path

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

MAX_SHEET_HEIGHT = 4000
DEFAULT_FPS = 1.0
DEFAULT_COLS = 5
DEFAULT_WIDTH = 600
BAND_BG = (24, 24, 28)
BAND_FG = (235, 235, 235)

_NAME = re.compile(
    r"(?:Bildschirmaufnahme|Screen Recording) "
    r"(\d{4})-(\d{2})-(\d{2}) (?:um|at) (\d{2})\.(\d{2})\.(\d{2})"
)


@dataclass(frozen=True)
class Crop:
    """A source-pixel rectangle, as ffmpeg's `crop=w:h:x:y` takes it."""

    w: int
    h: int
    x: int
    y: int

    def __post_init__(self) -> None:
        """Refuse what `parse_crop` refuses, so no other caller can build one."""
        if self.w <= 0 or self.h <= 0 or self.x < 0 or self.y < 0:
            raise ValueError(f"crop needs W,H > 0 and X,Y >= 0: {self}")

    def fits(self, width: int, height: int) -> bool:
        """Whether the rectangle lies entirely inside a `width` x `height` frame."""
        return self.x + self.w <= width and self.y + self.h <= height


@dataclass(frozen=True)
class Probe:
    """What ffprobe says about a recording's video stream, plus the name's start."""

    duration: float
    width: int
    height: int
    fps: float | None
    first_pts: float
    lead: float  # seconds between the stream's start and its first frame
    started: datetime | None


def parse_start(name: str) -> datetime | None:
    """The recording's start time from its file name, or None for any other name."""
    m = _NAME.fullmatch(Path(name).stem)
    if m is None:
        return None
    try:
        year, month, day, hour, minute, second = (int(g) for g in m.groups())
        return datetime(year, month, day, hour=hour, minute=minute, second=second)
    except ValueError:
        return None


def parse_crop(text: str) -> Crop:
    """Parse `W:H:X:Y`; a malformed or non-positive size is an argparse error."""
    parts = text.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"expected W:H:X:Y, got {text!r}")
    try:
        w, h, x, y = (int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected W:H:X:Y integers, got {text!r}") from None
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        raise argparse.ArgumentTypeError(f"expected W:H:X:Y with W,H > 0 and X,Y >= 0: {text!r}")
    return Crop(w, h, x, y)


def video_filter(fps: float, crop: Crop | None, width: int | None, origin: float) -> str:
    """The ffmpeg `-vf` chain: re-time, sample, then crop (source pixels), then scale.

    `setpts` shifts the timeline so slot 0 is `origin` (absolute stream time),
    and `fps ... round=up` fills every slot with the last frame at or before it.
    Crop comes before scale so its numbers are the source's own, which is what
    someone reading them off a full-resolution frame has in hand.
    """
    steps = [f"setpts=PTS-{origin:.6f}/TB", f"fps={fps}:start_time=0:round=up"]
    if crop is not None:
        steps.append(f"crop={crop.w}:{crop.h}:{crop.x}:{crop.y}:exact=1")
    if width is not None:
        steps.append(f"scale={width}:-2")
    return ",".join(steps)


def tile_times(start: float, end: float, fps: float) -> list[float]:
    """Times (s into the video) of the tiles over [start, end) at `fps`."""
    count = math.ceil((end - start) * fps - 1e-9)
    return [start + i / fps for i in range(count)]


def decimals_for(fps: float) -> int:
    """Digits after the point a label needs so neighbouring tiles differ."""
    return max(1, math.ceil(math.log10(fps)))


def wall_clock(start: datetime, t: float, decimals: int = 1) -> str:
    """`HH:MM:SS.s` of the frame `t` seconds into a recording that began at `start`."""
    quantum = 10**decimals
    ticks = round(t * quantum)
    moment = start + timedelta(seconds=ticks // quantum)
    return f"{moment:%H:%M:%S}.{ticks % quantum:0{decimals}d}"


def label_for(t: float, start: datetime | None, decimals: int = 1) -> str:
    """Tile label: `t=12.5s`, plus ` 17:07:22.5` when the start time is known.

    Both halves come from one rounding of `t`, so they cannot disagree about
    which tenth of a second the tile is.
    """
    t = round(t * 10**decimals) / 10**decimals
    text = f"t={t:.{decimals}f}s"
    if start is not None:
        text += f"  {wall_clock(start, t, decimals)}"
    return text


def label_size(width: int) -> int:
    """Font size, in px, for a tile `width` px wide; the band is twice this."""
    return max(14, round(width / 30))


def labelled(tile: Image.Image, text: str) -> Image.Image:
    """`tile` with a dark band carrying `text` appended below it."""
    size = label_size(tile.width)
    out = Image.new("RGB", (tile.width, tile.height + size * 2), BAND_BG)
    out.paste(tile.convert("RGB"), (0, 0))
    font = ImageFont.load_default(size=size)
    ImageDraw.Draw(out).text((size // 2, tile.height + size // 2), text, fill=BAND_FG, font=font)
    return out


def sheet_layout(tile_h: int, cols: int, count: int) -> tuple[int, int]:
    """(rows per sheet, number of sheets) under MAX_SHEET_HEIGHT."""
    rows = max(1, MAX_SHEET_HEIGHT // tile_h)
    return rows, max(1, math.ceil(count / (rows * cols)))


def compose(tiles: list[Image.Image], cols: int, rows: int) -> Image.Image:
    """Lay `tiles` out row by row on a dark canvas `cols` wide, `rows` tall at most."""
    w, h = tiles[0].size
    used_rows = math.ceil(len(tiles) / cols)
    canvas = Image.new("RGB", (cols * w, min(used_rows, rows) * h), BAND_BG)
    for i, tile in enumerate(tiles):
        canvas.paste(tile, ((i % cols) * w, (i // cols) * h))
    return canvas


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a tool; a missing binary or a non-zero exit becomes a one-line error."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise SystemExit(f"{cmd[0]} not found on PATH") from None
    if done.returncode != 0:
        raise SystemExit(f"{cmd[0]} failed (exit {done.returncode}):\n{done.stderr.strip()}")
    return done


def probe(video: Path) -> Probe:
    """Duration, size, frame rate and start of `video`'s first video stream."""
    out = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,duration,start_time:format=duration:packet=pts_time",
            "-read_intervals",
            "%+#5",
            "-of",
            "json",
            str(video),
        ]
    ).stdout
    try:
        data = json.loads(out)
    except ValueError:
        raise SystemExit(f"ffprobe printed something that is not JSON for {video.name}") from None
    streams = data.get("streams") or []
    if not streams:
        raise SystemExit(f"{video.name} has no video stream")
    stream = streams[0]
    first_pts = _number(stream.get("start_time")) or 0.0
    duration = _number(stream.get("duration"))
    if duration is None:
        container = _number(data.get("format", {}).get("duration"))
        if container is not None:
            # The container's span includes the stream's start offset; the stream
            # timeline, which every slot is measured on, does not.
            duration = container - first_pts
            print(
                "note: the video stream has no duration of its own; using the container's",
                file=sys.stderr,
            )
    if duration is None or duration <= 0:
        raise SystemExit(f"{video.name} reports no usable duration")
    try:
        rate = Fraction(stream["avg_frame_rate"])
        fps = float(rate) if rate > 0 else None
    except (KeyError, ValueError, ZeroDivisionError):
        fps = None
    return Probe(
        duration=duration,
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=fps,
        first_pts=first_pts,
        lead=max(0.0, _first_frame(data) - first_pts),
        started=parse_start(video.name),
    )


def _first_frame(data: dict) -> float:
    """Earliest presentation time among the first packets ffprobe listed, or 0."""
    times = [_number(pk.get("pts_time")) for pk in data.get("packets") or []]
    known = [t for t in times if t is not None]
    return min(known) if known else 0.0


def lead_note(info: Probe, start: float) -> str | None:
    """A warning when the window opens before the first frame exists, else None."""
    if start >= info.lead - 1e-6:
        return None
    return (
        f"note: the first frame is {info.lead:.3f} s into the stream, so everything before "
        f"that, from {start:g} s on, repeats that first frame"
    )


def _number(value: str | None) -> float | None:
    """A finite float from ffprobe's string field, or None for `N/A` and the like."""
    try:
        number = float(value)  # type: ignore[arg-type]  # None raises TypeError, handled
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# Printed once per scaler on this machine's ffmpeg for every yuv420p source;
# harmless, and it would bury the warnings that mean a damaged input.
_NOISE = "No accelerated colorspace conversion"


def _warnings(stderr: str) -> str:
    """What ffmpeg printed to stderr, minus the known-harmless scaler notice."""
    return "\n".join(ln for ln in stderr.splitlines() if ln.strip() and _NOISE not in ln)


def _sample(
    video: Path,
    info: Probe,
    start: float,
    fps: float,
    count: int,
    crop: Crop | None,
    width: int | None,
    scratch: Path,
) -> list[tuple[int, Path]]:
    """Extract `count` slots from `start` at `fps`; returns (slot number, PNG) pairs.

    The slot number is the file name ffmpeg gave the frame (`-frame_pts`), which
    is the frame's own place on the sampling grid. The caller derives the label
    from it, and a result that is not exactly slots 0..count-1 is refused here.
    """
    origin = info.first_pts + start
    done = _run(
        [
            "ffmpeg",
            "-v",
            "warning",
            "-nostdin",
            "-y",
            "-noaccurate_seek",
            "-ss",
            f"{origin:.6f}",
            "-copyts",
            "-i",
            str(video),
            "-vf",
            video_filter(fps, crop, width, origin),
            "-frames:v",
            str(count),
            "-frame_pts",
            "1",
            str(scratch / "%06d.png"),
        ]
    )
    if warnings := _warnings(done.stderr):
        print(f"ffmpeg: {warnings}", file=sys.stderr)
    found = sorted((int(p.stem), p) for p in scratch.glob("*.png"))
    if [n for n, _ in found] != list(range(count)):
        got = ", ".join(str(n) for n, _ in found) or "none"
        raise SystemExit(
            f"ffmpeg returned slots [{got}] where 0..{count - 1} were expected; "
            "the labels would not match the frames, so nothing was written"
        )
    return found


def _out_dir(video: Path, out: str | None) -> Path:
    """The output directory's path; it is created only once there is something to write."""
    base = Path(out) if out else Path(tempfile.gettempdir()) / "video-frames" / video.stem
    return base.resolve()


def _crop_tag(crop: Crop | None) -> str:
    return f"-crop-{crop.w}x{crop.h}+{crop.x}+{crop.y}" if crop else ""


def _check_crop(crop: Crop | None, info: Probe) -> None:
    if crop is not None and not crop.fits(info.width, info.height):
        raise SystemExit(
            f"crop {crop.w}:{crop.h}:{crop.x}:{crop.y} reaches outside the "
            f"{info.width}x{info.height} frame"
        )


def cmd_probe(ns: argparse.Namespace) -> list[Path]:
    """Print what `probe` found."""
    info = probe(Path(ns.video))
    started = info.started.isoformat(sep=" ") if info.started else "unknown (not in the file name)"
    rate = f"{info.fps:.2f} fps (average)" if info.fps else "unknown"
    print(f"duration   {info.duration:.3f} s")
    print(f"size       {info.width} x {info.height}")
    print(f"frame rate {rate}")
    print(f"started    {started}")
    return []


def cmd_sheet(ns: argparse.Namespace) -> list[Path]:
    """Write the contact sheets; returns their paths."""
    video = Path(ns.video).resolve()
    info = probe(video)
    _check_crop(ns.crop, info)
    start_s = ns.start
    end_s = info.duration if ns.end is None else min(ns.end, info.duration)
    if ns.end is not None and ns.end > info.duration:
        print(
            f"note: --to {ns.end:g} is past the video's end; using {info.duration:.3f} s",
            file=sys.stderr,
        )
    if end_s <= start_s:
        raise SystemExit(
            f"empty window: from {start_s:g} s, but the video is {info.duration:.3f} s long"
        )
    count = len(tile_times(start_s, end_s, ns.fps))
    decimals = decimals_for(ns.fps)
    if note := lead_note(info, start_s):
        print(note, file=sys.stderr)
    dest = _out_dir(video, ns.out)
    prefix = f"{video.stem}-sheet-{start_s:g}-{end_s:.3f}s-{ns.fps:g}fps{_crop_tag(ns.crop)}"
    with tempfile.TemporaryDirectory(prefix="video-frames-") as scratch:
        slots = _sample(video, info, start_s, ns.fps, count, ns.crop, ns.width, Path(scratch))
        with Image.open(slots[0][1]) as first:
            tile_h = first.height + 2 * label_size(first.width)
        rows, n_sheets = sheet_layout(tile_h, ns.cols, count)
        dest.mkdir(parents=True, exist_ok=True)
        for stale in glob.glob(glob.escape(str(dest / prefix)) + "-[0-9][0-9].png"):
            Path(stale).unlink()
        per_sheet = rows * ns.cols
        written = []
        for n in range(n_sheets):
            tiles = []
            for slot, png in slots[n * per_sheet : (n + 1) * per_sheet]:
                with Image.open(png) as img:
                    label = label_for(start_s + slot / ns.fps, info.started, decimals)
                    tiles.append(labelled(img, label))
            path = dest / f"{prefix}-{n + 1:02d}.png"
            compose(tiles, ns.cols, rows).save(path)
            written.append(path)
    return written


def cmd_frame(ns: argparse.Namespace) -> list[Path]:
    """Write one labelled frame; returns its path."""
    video = Path(ns.video).resolve()
    info = probe(video)
    _check_crop(ns.crop, info)
    if ns.at >= info.duration:
        raise SystemExit(f"no frame at {ns.at:g} s: the video is {info.duration:.3f} s long")
    if note := lead_note(info, ns.at):
        print(note, file=sys.stderr)
    dest = _out_dir(video, ns.out)
    width_tag = f"-w{ns.width}" if ns.width else ""
    path = dest / f"{video.stem}-frame-{ns.at:.3f}s{_crop_tag(ns.crop)}{width_tag}.png"
    with tempfile.TemporaryDirectory(prefix="video-frames-") as scratch:
        ((_, png),) = _sample(video, info, ns.at, 1.0, 1, ns.crop, ns.width, Path(scratch))
        with Image.open(png) as img:
            dest.mkdir(parents=True, exist_ok=True)
            labelled(img, label_for(ns.at, info.started, 2)).save(path)
    return [path]


def _finite(kind):
    """An argparse type: `kind(text)` that is a finite number, else a clean error."""

    def check(text: str):
        value = kind(text)
        if not math.isfinite(value):
            raise argparse.ArgumentTypeError(f"must be a finite number: {text}")
        return value

    return check


def _positive(kind):
    def check(text: str):
        value = _finite(kind)(text)
        if value <= 0:
            raise argparse.ArgumentTypeError(f"must be positive: {text}")
        return value

    return check


def _seconds(text: str) -> float:
    value = _finite(float)(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must not be negative: {text}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """The CLI; `description` takes only the docstring's first line."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").partition("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="duration, size, frame rate, start time")
    p.add_argument("video")
    p.set_defaults(run=cmd_probe)

    p = sub.add_parser("sheet", help="labelled contact sheet(s) over a window")
    p.add_argument("video")
    p.add_argument("--from", dest="start", type=_seconds, default=0.0, metavar="S")
    p.add_argument("--to", dest="end", type=_seconds, default=None, metavar="S")
    p.add_argument("--fps", type=_positive(float), default=DEFAULT_FPS)
    p.add_argument("--cols", type=_positive(int), default=DEFAULT_COLS)
    p.add_argument("--width", type=_positive(int), default=DEFAULT_WIDTH, help="tile width, px")
    p.add_argument("--crop", type=parse_crop, help="W:H:X:Y in source pixels")
    p.add_argument("--out", help="output directory (default $TMPDIR/video-frames/<stem>)")
    p.set_defaults(run=cmd_sheet)

    p = sub.add_parser("frame", help="one labelled frame")
    p.add_argument("video")
    p.add_argument("--at", type=_seconds, required=True, metavar="S")
    p.add_argument("--crop", type=parse_crop, help="W:H:X:Y in source pixels")
    p.add_argument("--width", type=_positive(int), help="scale to this width (default: none)")
    p.add_argument("--out", help="output directory (default $TMPDIR/video-frames/<stem>)")
    p.set_defaults(run=cmd_frame)
    return ap


def main(argv: list[str] | None = None) -> int:
    """Run a subcommand and print every file it wrote as an absolute path."""
    ns = build_parser().parse_args(argv)
    if not Path(ns.video).is_file():
        raise SystemExit(f"no such file: {ns.video}")
    for path in ns.run(ns):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
