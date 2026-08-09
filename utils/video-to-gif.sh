#!/usr/bin/env bash
# utils/video-to-gif.sh — Turn a screen recording into a GIF, cropped to 16:9.
#
# The video counterpart to `crop-center-169.sh`: that script cuts the centre 16:9
# region out of an ultra-wide still, this one does the same for a video and then
# encodes it as a GIF. Written for Core Keeper clips recorded on a 32:9 display,
# where the interesting half of the frame is the middle.
#
#   video-to-gif.sh clip.mov                      # whole clip, centre 16:9, 15 fps
#   video-to-gif.sh -s 4 -e 30.5 clip.mov         # trim intro and outro
#   video-to-gif.sh -f 12 -w 1280 a.mov b.mov     # slower, downscaled, two files
#
# Output goes next to the input as <name>.gif unless -o says otherwise.
#
# Requires ffmpeg + ffprobe; uses gifski for encoding when it is installed
# (`brew install gifski`) and falls back to ffmpeg's palette filters otherwise.
# Note this build of ffmpeg has no `drawtext` (no libfreetype), so nothing here
# depends on it.

set -euo pipefail

fps=15
colors=200
quality=90
width=""
start=""
end=""
out=""
do_crop=1

# gifski produces visibly better GIFs than ffmpeg's palette filters, so prefer it
# when installed (`brew install gifski`) and fall back silently when it is not.
if command -v gifski >/dev/null; then use_gifski=1; else use_gifski=0; fi

die() { printf '%s\n' "$*" >&2; exit 1; }

usage() {
  cat >&2 <<'EOF'
Usage: video-to-gif.sh [options] <video> [video …]

  -s, --start SEC    start offset in seconds (default: 0)
  -e, --end SEC      end offset in seconds (default: end of clip)
  -f, --fps N        output frame rate (default: 15)
  -w, --width PX     scale to this width, keeping aspect (default: no scaling)
  -c, --colors N     palette size for the ffmpeg encoder, 2..256 (default: 200)
  -q, --quality N    gifski quality, 1..100 (default: 90)
      --gifski       force the gifski encoder
      --no-gifski    force ffmpeg's palettegen/paletteuse encoder
      --no-crop      keep the full frame instead of the centre 16:9 region
  -o, --out FILE     output path (only valid with a single input)
  -h, --help         this text

Encoder: gifski when installed (better quality, needs scratch space for one PNG
per frame), otherwise ffmpeg's two-pass palette.

Size levers, in the order worth trying: shorter --start/--end, then lower --fps,
and only then --width. GIF stores whole frames, so length and frame rate dominate.
Measured on Core Keeper captures at 2048x1152:

  26 s, 15 fps, ffmpeg  274 MB      6 s, 10 fps, gifski   37 MB
  26 s, 15 fps, gifski  ~230 MB    10 s, 15 fps, gifski   86 MB

Full resolution stays practical as long as the clip is short: 6 s at 10 fps lands
at the same file size as a 1280x720 GIF of comparable length, with 2.6x the pixels.
Reach for --width only once trimming and frame rate are exhausted.
EOF
  exit 2
}

while (( $# )); do
  case "$1" in
    -s|--start)  start="${2:-}"; shift 2 ;;
    -e|--end)    end="${2:-}";   shift 2 ;;
    -f|--fps)    fps="${2:-}";   shift 2 ;;
    -w|--width)  width="${2:-}"; shift 2 ;;
    -c|--colors) colors="${2:-}"; shift 2 ;;
    -q|--quality) quality="${2:-}"; shift 2 ;;
    --gifski)    use_gifski=1; shift ;;
    --no-gifski) use_gifski=0; shift ;;
    --no-crop)   do_crop=0; shift ;;
    -o|--out)    out="${2:-}";   shift 2 ;;
    -h|--help)   usage ;;
    -*)          die "unknown option: $1" ;;
    *)           break ;;
  esac
done

(( $# )) || usage
[[ -n "$out" && $# -gt 1 ]] && die "-o/--out takes a single input file"

command -v ffmpeg  >/dev/null || die "ffmpeg not found"
command -v ffprobe >/dev/null || die "ffprobe not found"

for src in "$@"; do
  [[ -f "$src" ]] || { printf 'skipped (not found): %s\n' "$src" >&2; continue; }

  # `-of csv=p=0` only — ffprobe 8.x rejects the older `csv=p=0:s=' '` spelling
  # ("Failed to parse option string … provided to textformat context").
  IFS=, read -r w h < <(ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height -of csv=p=0 "$src")
  [[ -n "${w:-}" && -n "${h:-}" ]] || { printf 'skipped (no dimensions): %s\n' "$src" >&2; continue; }

  chain=""
  out_w=$w out_h=$h
  if (( do_crop )); then
    # Same rule as crop-center-169.sh: keep full height, width becomes H*16/9,
    # centred. Skipped when the source is already 16:9 or narrower.
    target=$(( h * 16 / 9 ))
    if (( target < w )); then
      chain="crop=${target}:${h}:$(( (w - target) / 2 )):0,"
      out_w=$target
    else
      printf 'note: %s is %dx%d — already 16:9 or narrower, not cropping\n' "${src##*/}" "$w" "$h" >&2
    fi
  fi
  chain+="fps=${fps}"
  if [[ -n "$width" ]]; then
    chain+=",scale=${width}:-1:flags=lanczos"
    out_h=$(( out_h * width / out_w ))
    out_w=$width
  fi

  cut=()
  [[ -n "$start" ]] && cut+=(-ss "$start")
  [[ -n "$end"   ]] && cut+=(-to "$end")

  dest="$out"
  [[ -n "$dest" ]] || dest="${src%.*}.gif"

  if (( use_gifski )); then
    # gifski quantises across the whole clip rather than per frame, which is why
    # it beats ffmpeg's palette on gradient-heavy material — at the cost of
    # staging every frame as a PNG first (budget roughly 4 MB per frame at
    # 2048x1152, so a 400-frame clip wants ~1.5 GB of scratch space).
    # Explicit XXXXXX: GNU mktemp (Homebrew coreutils, ahead of the BSD tools in
    # PATH here) rejects a template without it, while BSD mktemp appends its own.
    # Spelling it out satisfies both.
    tmpdir="$(mktemp -d -t v2g-frames.XXXXXX)"
    trap 'rm -rf "$tmpdir"' EXIT
    ffmpeg -y -v error "${cut[@]}" -i "$src" -vf "$chain" "$tmpdir/f%05d.png"
    # Always pass the frame size explicitly. gifski's --width/--height are
    # MAXIMUMS with a default cap that silently downscales anything wider than
    # 1024 px — a 2048x1152 clip comes out 1024x576 with no warning at all. Since
    # any requested scaling already happened in the ffmpeg chain above, out_w/out_h
    # are the true frame dimensions and passing them means "leave it alone".
    gifski -o "$dest" --fps "$fps" --quality "$quality" \
      --width "$out_w" --height "$out_h" "$tmpdir"/f*.png
    rm -rf "$tmpdir"
    trap - EXIT
  else
    pal="$(mktemp -t v2g-palette.XXXXXX).png"
    trap 'rm -f "$pal"' EXIT

    # Two passes. GIF holds at most 256 colours per frame, so a palette derived
    # from this clip beats any generic one; stats_mode=diff weights the moving
    # part of the frame, which is what the eye follows.
    #
    # Expect this path to produce a MUCH larger file than gifski — measured on a
    # 26 s 2048x1152 clip: 274 MB here versus 50 MB from gifski, same input and
    # frame rate. The culprit is the dithering: bayer lays a fixed pattern over
    # flat areas, so a uniform wall stops being a run of identical pixels and LZW
    # loses its grip. Dropping to dither=none shrinks the file at the cost of
    # banding in the gradients. Prefer gifski whenever it is available.
    ffmpeg -y -v error "${cut[@]}" -i "$src" \
      -vf "${chain},palettegen=max_colors=${colors}:stats_mode=diff" "$pal"

    # ${chain}[x] — braces are load-bearing: in zsh, "$chain[x]" parses as an
    # array subscript and silently expands to nothing, leaving ffmpeg with an
    # empty filter name. Harmless in bash, wrong in zsh; keep the braces.
    ffmpeg -y -v error "${cut[@]}" -i "$src" -i "$pal" \
      -lavfi "${chain}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle" \
      -loop 0 "$dest"

    rm -f "$pal"
    trap - EXIT
  fi

  # `wc -c` instead of stat: GNU coreutils are ahead of the BSD tools in PATH on
  # this machine, so `stat -f%z` (BSD) fails while `stat -c%s` (GNU) works — and
  # the reverse holds on a stock macOS. wc sidesteps the difference entirely.
  bytes=$(wc -c < "$dest")
  awk -v b="$bytes" -v s="${src##*/}" -v d="${dest##*/}" \
    'BEGIN { printf "✓ %s → %s (%.1f MB)\n", s, d, b/1048576 }'
done
