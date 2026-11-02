#!/usr/bin/env bash
# Test recordings for the page's "keep only the sound" step, shaped like what phones hand over. Needs ffmpeg.
#   iphone.mov  HEVC video + AAC audio in QuickTime (the iPhone camera, which is what "record" opens on iOS)
#   voice.m4a   AAC in mp4 (Voice Memos, Android recorders)
#   voice.ogg   Vorbis (no AAC track: the Web Audio fallback)
#   old.3gp     AMR-NB (old Android recorders: refused)
# Usage: tests/harness/make-takes.sh [DIR]   (default: a new temp folder; never inside the repo)
set -euo pipefail
out=${1:-$(mktemp -d)}
mkdir -p "$out"
ff() { ffmpeg -v error -y "$@"; }
tone="sine=frequency=330:duration=5:sample_rate=48000"
ff -f lavfi -i "testsrc2=size=720x1280:rate=30:duration=5" -f lavfi -i "$tone" -c:v libx265 -x265-params log-level=error -tag:v hvc1 -pix_fmt yuv420p \
   -c:a aac -ac 1 -b:a 96k -shortest "$out/iphone.mov"
ff -f lavfi -i "$tone" -c:a aac -ac 1 -b:a 96k "$out/voice.m4a"
ff -f lavfi -i "$tone" -c:a libvorbis -ac 1 "$out/voice.ogg"
ff -f lavfi -i "sine=frequency=330:duration=5:sample_rate=8000" -c:a libopencore_amrnb -ar 8000 -ac 1 -b:a 12.2k "$out/old.3gp"
echo "$out"
