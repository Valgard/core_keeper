#!/usr/bin/env zsh
# crop-center-169 — schneidet den mittigen 16:9-Ausschnitt (volle Höhe) aus einem Bild.
#
# Gedacht für 32:9-Panorama-Screenshots, funktioniert aber für jedes Bild, das
# breiter als 16:9 ist: die Höhe bleibt, die Breite wird auf H*16/9 gesetzt und
# sips croppt automatisch mittig. Standardmäßig IN-PLACE (Original wird ersetzt);
# mit -k/--keep bleibt das Original und das Ergebnis landet als <name>-16x9.<ext>.

set -u

keep=0
if [[ "${1:-}" == "-k" || "${1:-}" == "--keep" ]]; then
  keep=1
  shift
fi

if (( $# == 0 )); then
  print -u2 "Usage: ${0:t} [-k|--keep] <bild> [bild …]"
  print -u2 "  Schneidet den mittigen 16:9-Ausschnitt (volle Höhe) aus jedem Bild."
  print -u2 "  -k  Original behalten, Ergebnis als <name>-16x9.<ext> schreiben."
  exit 2
fi

rc=0
for img in "$@"; do
  if [[ ! -f "$img" ]]; then
    print -u2 "übersprungen (nicht gefunden): $img"
    rc=1
    continue
  fi

  h=$(sips -g pixelHeight "$img" 2>/dev/null | awk '/pixelHeight/{print $2}')
  w=$(sips -g pixelWidth  "$img" 2>/dev/null | awk '/pixelWidth/{print $2}')

  if [[ -z "$h" || -z "$w" ]]; then
    print -u2 "übersprungen (keine Bildmaße): $img"
    rc=1
    continue
  fi

  target=$(( h * 16 / 9 ))

  if (( target >= w )); then
    print -u2 "übersprungen (bereits 16:9 oder schmaler): $img (${w}x${h})"
    rc=1
    continue
  fi

  if (( keep )); then
    out="${img:r}-16x9.${img:e}"
    sips -c "$h" "$target" "$img" --out "$out" >/dev/null
    print "✓ ${img} (${w}x${h}) → ${out} (${target}x${h})"
  else
    sips -c "$h" "$target" "$img" >/dev/null
    print "✓ ${img} (${w}x${h}) → ${target}x${h}"
  fi
done

exit $rc
