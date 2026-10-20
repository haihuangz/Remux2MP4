import glob
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "media", "fmp4")
DUR = 12
FRAG = "frag_keyframe+empty_moov+default_base_moof"

SRT = """1
00:00:00,500 --> 00:00:03,000
分片字幕 第一句

2
00:00:04,000 --> 00:00:07,000
second line
"""

FFMETA = """;FFMETADATA1
title=分片测试 Fragmented test
artist=测试者
comment=global tag survives?
[CHAPTER]
TIMEBASE=1/1000
START=0
END=4000
title=开场
[CHAPTER]
TIMEBASE=1/1000
START=4000
END=8000
title=中段 Middle
[CHAPTER]
TIMEBASE=1/1000
START=8000
END=12000
title=结尾
"""


def run(args, cwd=None):
    print(">", args[-1])
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error"] + args,
                       capture_output=True, encoding="utf-8", errors="replace", cwd=cwd)
    if p.returncode != 0:
        print(p.stderr)
        raise SystemExit(f"ffmpeg failed for {args[-1]}")


def path(name):
    return os.path.join(OUT, name)


def lavfi_av(n_audio=1, size="1280x720"):
    args = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={DUR}"]
    for i in range(n_audio):
        args += ["-f", "lavfi", "-i", f"sine=frequency={330 + 220 * i}:sample_rate=48000:duration={DUR}"]
    return args


H264 = ["-c:v", "libx264", "-preset", "veryfast", "-g", "60", "-pix_fmt", "yuv420p"]


def make_full_featured(name):
    srt = path("_sub.srt")
    meta = path("_meta.txt")
    with open(srt, "w", encoding="utf-8") as f:
        f.write(SRT)
    with open(meta, "w", encoding="utf-8") as f:
        f.write(FFMETA)
    args = lavfi_av(2) + ["-i", srt, "-i", meta]
    args += ["-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s", "-map_metadata", "4", "-map_chapters", "4"]
    args += H264 + ["-c:a", "aac", "-b:a", "160k", "-c:s", "mov_text"]
    args += ["-metadata:s:a:0", "language=chi", "-metadata:s:a:0", "handler_name=游戏声音",
             "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "handler_name=Mic 麦克风",
             "-metadata:s:s:0", "language=chi", "-metadata:s:s:0", "handler_name=中文字幕",
             "-disposition:a:0", "default", "-disposition:a:1", "0",
             "-movflags", FRAG, path(name)]
    run(args)


def make_hevc(name, tag):
    args = lavfi_av(1) + ["-map", "0:v", "-map", "1:a", "-c:v", "libx265", "-preset", "ultrafast",
                          "-x265-params", "keyint=60:log-level=error", "-tag:v", tag,
                          "-c:a", "aac", "-movflags", FRAG, path(name)]
    run(args)


def make_cmaf(name):
    args = lavfi_av(1) + ["-map", "0:v", "-map", "1:a"] + H264 + ["-c:a", "aac", "-movflags", "cmaf+" + FRAG, path(name)]
    run(args)


def make_dash_concat(name):
    work = path("_dash")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    args = lavfi_av(0) + ["-map", "0:v"] + H264 + ["-f", "dash", "-seg_duration", "2", "-use_template", "1",
                                                   "-use_timeline", "0", "manifest.mpd"]
    run(args, cwd=work)
    parts = sorted(glob.glob(os.path.join(work, "init-stream0.m4s"))) + \
        sorted(glob.glob(os.path.join(work, "chunk-stream0-*.m4s")))
    with open(path(name), "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                out.write(f.read())
    print(f"  concatenated {len(parts)} DASH parts")
    shutil.rmtree(work, ignore_errors=True)


def make_truncated(src, dst, fraction):
    with open(path(src), "rb") as f:
        data = f.read()
    with open(path(dst), "wb") as f:
        f.write(data[:int(len(data) * fraction)])
    print("> truncated", dst)


def make_normal(name):
    args = lavfi_av(1) + ["-map", "0:v", "-map", "1:a"] + H264 + ["-c:a", "aac", "-movflags", "+faststart", path(name)]
    run(args)


def main():
    os.makedirs(OUT, exist_ok=True)
    make_full_featured("frag_h264_2aac_sub_chapters.mp4")
    make_hevc("frag_hevc_hev1.mp4", "hev1")
    make_hevc("frag_hevc_hvc1.mp4", "hvc1")
    make_cmaf("cmaf.mp4")
    make_dash_concat("dash_init_plus_segments.m4s")
    make_truncated("frag_h264_2aac_sub_chapters.mp4", "frag_truncated.mp4", 0.63)
    make_normal("normal_faststart.mp4")
    make_full_featured("中文 空格 录像 (1).mp4")
    for tmp in ("_sub.srt", "_meta.txt"):
        os.remove(path(tmp))
    print("done:", OUT)


if __name__ == "__main__":
    main()
