"""Ties the three shipped font artifacts to the Pixaki master they came from.

Two of them (`thinTiny_full.png`, `thinTiny_kerning.bytes`) are written by
`pixaki_to_glyphs.py`; the third (the 384-character `Widths` constant) is
copy-pasted into C# by hand. Nothing else in the build compares them: a
forgotten paste passes `--check-only` (which validates the master, not the
C#), CSharpier, the Unity build and the Roslyn sandbox, and the mod even logs
its success line. The glyph then renders with a stale advance while its
kerning row was generated for the new shape -- and a cell that gains ink but
keeps a stale `'0'` gets a zero-size rect, which `InitCodePoints` skips, so
the character silently does not render at all.

These tests are the comparison nobody was making. They live in the parent repo
because that is where the generator and its suite live, and they read the mod
repo beside it; a parent checkout without the mod skips them loudly rather
than passing vacuously.
"""

import hashlib
import io
import re
import tomllib
from contextlib import redirect_stdout
from pathlib import Path

import PIL
import pixaki_to_glyphs as g
import pytest

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "pyproject.toml"
MOD = REPO / "complete-tiny-font"
MASTER = MOD / "sources" / "thinTiny.pixaki"
ART = MOD / "unity" / "CompleteTinyFont" / "Art"
ATLAS = ART / "thinTiny_full.png"
KERNING = ART / "thinTiny_kerning.bytes"
PATCH = MOD / "unity" / "CompleteTinyFont" / "ThinTinyFontPatch.cs"

pytestmark = pytest.mark.skipif(
    not MASTER.exists(),
    reason=(
        f"complete-tiny-font is not checked out beside this repo "
        f"({MASTER} missing), so the shipped artifacts cannot be compared "
        f"against their master -- these guards did NOT run"
    ),
)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digit_rows(text):
    """Every quoted run of digits, concatenated -- the Widths string's shape.

    Matches both the generator's pasteable stdout block and the C# constant's
    concatenated string literals, so the same parse reads either side.
    """
    return "".join(re.findall(r'"([0-9]+)"', text))


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    """Run the real CLI once, writing both artifacts, and keep its stdout.

    Deliberately goes through `main()` rather than calling the helpers
    directly: the PNG's bytes come from `Image.save()` inside that path, and
    the `Widths` block is something only the CLI prints.
    """
    out = tmp_path_factory.mktemp("regen")
    sheet, kerning = out / "atlas.png", out / "kerning.bytes"
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = g.main(
            [
                "--pixaki",
                str(MASTER),
                "--sheet",
                str(sheet),
                "--kerning",
                str(kerning),
            ]
        )
    assert rc == 0
    return sheet, kerning, buf.getvalue()


def test_pillow_matches_the_pin_in_pyproject():
    # Byte-identity is the acceptance check every test below relies on, and
    # PNG bytes are encoder-dependent -- so an unpinned Pillow would turn a
    # real change and an environment difference into the same failure. This
    # also catches the likelier accident: running the suite outside the
    # project environment, where the pin does not apply at all.
    deps = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    pinned = next(
        (d.split("==", 1)[1] for d in deps if d.lower().startswith("pillow==")), None
    )
    assert pinned, f"{PYPROJECT.name} no longer pins pillow to an exact version"
    assert PIL.__version__ == pinned, (
        f"running Pillow {PIL.__version__}, pyproject.toml pins {pinned} -- "
        "run the suite with `uv run pytest`, which resolves the pin"
    )


def test_regenerated_atlas_is_byte_identical_to_the_shipped_png(regenerated):
    sheet, _, _ = regenerated
    assert _sha256(sheet) == _sha256(ATLAS)


def test_regenerated_kerning_is_byte_identical_to_the_shipped_matrix(regenerated):
    _, kerning, _ = regenerated
    assert _sha256(kerning) == _sha256(KERNING)
    # 384 x 384 -- the size the runtime rejects the file for not being.
    assert KERNING.stat().st_size == g.CELLS * g.CELLS


def test_widths_constant_matches_what_the_generator_prints(regenerated):
    _, _, stdout = regenerated
    generated = _digit_rows(stdout)
    constant = re.search(r"Widths\s*=\s*(.*?);", PATCH.read_text(), re.S)
    assert constant, "the Widths constant is no longer where this test looks"
    assert _digit_rows(constant.group(1)) == generated


def test_the_printed_widths_block_is_pasteable_verbatim(regenerated):
    # The digit comparison above tolerates any layout; this pins the layout
    # itself. The generator emits what CSharpier would produce (leading `+` on
    # each continuation line at printWidth 160), so pasting is the last step of
    # a regeneration. With a trailing `+` the block had to be reformatted
    # afterwards -- a hand-touch on a string where one lost digit shifts every
    # later cell's advance and kerning row with nothing to catch it.
    _, _, stdout = regenerated
    start = stdout.index("        private const string Widths =")
    block = stdout[start : stdout.index(";", start) + 1]
    assert block in PATCH.read_text(), (
        "the generator's output is no longer a verbatim paste into "
        f"{PATCH.name} -- one of the two changed shape"
    )


def test_widths_constant_is_exactly_one_digit_per_cell(regenerated):
    # A short or long paste shifts every glyph after the error, and the
    # runtime never checks the length. Asserted as the literal 384 rather
    # than g.CELLS: a test that reads the constant it verifies cannot catch
    # that constant being wrong.
    constant = re.search(r"Widths\s*=\s*(.*?);", PATCH.read_text(), re.S)
    assert len(_digit_rows(constant.group(1))) == 384
