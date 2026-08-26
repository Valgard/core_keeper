"""Derive a Steam-Workshop-legal preview image from a mod's logo.

Steam rejects a preview above 1 MB with k_EResultLimitExceeded and fails the
whole upload. Every logo in this family exceeds it: 1024² PNGs whose golden glow
is exactly the gradient PNG cannot compress.

The ladder comes down in resolution first and only then in colour depth. The
Workshop displays previews at roughly 268² in listings, so resolution above that
buys nothing a viewer sees, while quantisation shows as banding in the gradients
that made the file large in the first place — visible at full size, and the
reason the obvious "quantise at 1024²" is the last step rather than the first.

Transparency is preserved throughout; the item page composites onto its own
background.
"""

from pathlib import Path

from PIL import Image

LIMIT = 1_048_576
LADDER = (1024, 896, 768, 640, 512, 384, 256)


def _targets(side: int) -> tuple[int, ...]:
    """Ladder rungs at or below the source's own resolution.

    A rung above `side` would upscale a raster that never had that much detail,
    so it is dropped rather than tried. When the source is smaller than every
    rung — a placeholder icon, a small logo — none qualify and the ladder would
    otherwise have nothing left to offer; the source's own size stands in as
    the sole rung, so a small image still gets a preview at the resolution it
    actually has instead of an unconditional refusal.
    """
    rungs = tuple(t for t in LADDER if t <= side)
    return rungs if rungs else (side,)


def _save(img: Image.Image, dest: Path) -> int:
    img.save(dest, optimize=True, compress_level=9)
    return dest.stat().st_size


def derive_preview(source: Path, dest: Path, limit: int = LIMIT) -> tuple[int, str]:
    """Write the largest preview that fits under `limit`. Returns (bytes, how)."""
    original = Image.open(source).convert("RGBA")
    side = min(original.size)
    targets = _targets(side)

    for target in targets:
        candidate = (
            original
            if target == side
            else original.resize((target, target), Image.LANCZOS)
        )
        size = _save(candidate, dest)
        if size <= limit:
            return size, f"{target}² lossless"

    # Nothing lossless fits. Quantising keeps the alpha channel and drops to an
    # indexed palette, which is roughly a third of the size at the cost of
    # banding — acceptable only because the alternative is no preview at all.
    for target in targets:
        candidate = (
            original
            if target == side
            else original.resize((target, target), Image.LANCZOS)
        )
        size = _save(candidate.quantize(colors=255, method=Image.FASTOCTREE), dest)
        if size <= limit:
            return size, f"{target}² quantised"

    dest.unlink(missing_ok=True)
    raise ValueError(f"no variant of {source.name} fits the {limit} byte limit")
