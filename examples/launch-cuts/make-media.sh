#!/usr/bin/env bash
# Generates placeholder renders for this example room (test patterns and tones) into ./renders. Needs ffmpeg.
set -euo pipefail
cd "$(dirname "$0")"
out=renders
mkdir -p "$out/carousel"
ff() { ffmpeg -v error -y "$@"; }

# clip <file> <seconds> <WxH> <label> [silent]
clip() {
  local file=$1 secs=$2 size=$3 label=$4 audio=(-f lavfi -i "sine=frequency=440:duration=$2") amap=(-map 1:a -c:a aac -b:a 96k)
  if [[ ${5:-} == silent ]]; then audio=(); amap=(-an); fi
  ff -f lavfi -i "testsrc2=size=$size:rate=30:duration=$secs" ${audio[@]+"${audio[@]}"} \
    -vf "drawtext=text='$label':fontsize=h/14:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=20:x=(w-tw)/2:y=h*0.1,drawtext=text='%{pts\:hms}':fontsize=h/20:fontcolor=white:box=1:boxcolor=black@0.6:x=(w-tw)/2:y=h*0.85" \
    -map 0:v ${amap[@]+"${amap[@]}"} -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$out/$file"
}
still() { ff -f lavfi -i "color=c=$2:size=1080x1350" -vf "drawtext=text='$3':fontsize=120:fontcolor=white:x=(w-tw)/2:y=(h-th)/2" -frames:v 1 "$out/$1"; }

clip teaser.mp4 8 720x1280 "Teaser"
clip explainer.mp4 12 1280x720 "Explainer"
clip explainer.silent.mp4 12 1280x720 "Explainer (silent)" silent
for c in teaser explainer; do ff -ss 1 -i "$out/$c.mp4" -frames:v 1 "$out/$c.poster.png"; done
still carousel/01-question.png 0x2b4c7e "1 · Question"
still carousel/02-product.png 0x7e2b5a "2 · Product"
still carousel/03-date.png 0x2b7e4c "3 · Date"
ff -f lavfi -i "testsrc2=size=1080x1350:rate=30:duration=4" -c:v libx264 -pix_fmt yuv420p "$out/carousel/04-clip.mp4"
echo "Renders in $(pwd)/$out"
