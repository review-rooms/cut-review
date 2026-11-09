#!/usr/bin/env bash
# Generates placeholder renders for this example room (test patterns, tones and sketched storyboard frames) into ./renders. Needs ffmpeg.
set -euo pipefail
cd "$(dirname "$0")"
out=renders
mkdir -p "$out/carousel" "$out/board" "$out/tiktok"
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
tall() { ff -f lavfi -i "color=c=$2:size=1080x1920" -vf "drawtext=text='$3':fontsize=110:fontcolor=white:x=(w-tw)/2:y=(h-th)/2" -frames:v 1 "$out/$1"; }
# sketch <file> <label> <drawbox filters>: a storyboard frame, pencil-grey boxes on paper, as a board artist draws it
sketch() { ff -f lavfi -i "color=c=0xfbfaf6:size=1080x1920" -vf "$3,drawtext=text='$2':fontsize=54:fontcolor=0x9a9a9a:x=60:y=h-110" -frames:v 1 "$out/$1"; }
pen=color=0x3c3c3c:t=9; shade=color=0x3c3c3c@0.12:t=fill
notebook="drawbox=x=150:y=560:w=780:h=980:$shade,drawbox=x=150:y=560:w=780:h=980:$pen,drawbox=x=530:y=560:w=6:h=980:$pen"
notebook+=",drawbox=x=200:y=700:w=280:h=5:$pen,drawbox=x=200:y=800:w=280:h=5:$pen,drawbox=x=200:y=900:w=220:h=5:$pen"
hand="drawbox=x=600:y=980:w=330:h=420:$pen,drawbox=x=560:y=860:w=40:h=300:$pen"
logo="drawbox=x=390:y=820:w=300:h=300:color=0x3c3c3c@0.55:t=fill,drawbox=x=300:y=1180:w=480:h=40:$pen"
phone="drawbox=x=300:y=380:w=480:h=1000:$pen,drawbox=x=480:y=420:w=120:h=20:$pen,drawbox=x=340:y=560:w=300:h=110:$shade,drawbox=x=440:y=720:w=300:h=110:$pen"
phone+=",drawbox=x=340:y=880:w=360:h=240:$shade,drawbox=x=340:y=1250:w=400:h=80:$pen,drawbox=x=220:y=1300:w=260:h=380:$pen"
endcard="drawbox=x=200:y=760:w=680:h=90:color=0x3c3c3c@0.55:t=fill,drawbox=x=280:y=900:w=520:h=60:$shade,drawbox=x=330:y=1060:w=420:h=110:$pen"
sketch board/launch-1.png "1 · CU hand" "$notebook,$hand"
sketch board/launch-2.png "2 · MS page, logo" "$notebook,$logo"
sketch board/launch-3.png "3 · MCU phone" "$phone"
sketch board/launch-4.png "4 · End card" "$endcard"
sketch board/teaser-1.png "1 · CU notebook" "$notebook,$hand"
sketch board/teaser-2.png "2 · Logo" "$logo"
sketch board/teaser-3.png "3 · End card" "$endcard"
for i in 1 2 3; do tall "tiktok/0$i.png" 0x225566 "Slide $i"; done
echo "Renders in $(pwd)/$out"
