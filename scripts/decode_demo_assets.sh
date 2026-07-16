#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
shopt -s nullglob
for man in demo-assets/*.b64.parts; do
  base="${man%.parts}"
  : > "$base"
  while IFS= read -r part; do
    [ -z "$part" ] && continue
    cat "demo-assets/$part" >> "$base"
  done < "$man"
done
for b64 in demo-assets/*.b64; do
  out="${b64%.b64}"
  base64 -d "$b64" > "$out"
  echo "Decoded $out"
done
ls -lh demo-assets/*.{jpg,mp4} 2>/dev/null || true
