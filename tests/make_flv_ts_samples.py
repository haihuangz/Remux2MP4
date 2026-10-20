import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "media", "flv_ts")
EXPORT = os.path.join(HERE, "media", "export")
DUR = 20
LANGS = ["chi", "eng", "jpn"]
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-g", "60", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "160k", "-ac", "2"]


def run(args):
    print(">", " ".join(args[:6]), "...", args[-1])
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error"] + args,
                       capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print(p.stderr)
        raise SystemExit(f"ffmpeg failed for {args[-1]}")


def video_in(size="1280x720", rate=30, dur=DUR):
    return ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={dur}"]


def audio_in(freq, dur=DUR, offset=None):
    pre = ["-itsoffset", str(offset)] if offset else []
    return pre + ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={dur}"]


def maps(n_audio):
    args = ["-map", "0:v"]
    for i in range(n_audio):
        args += ["-map", f"{i + 1}:a"]
    return args


def path(name, folder=OUT):
    return os.path.join(folder, name)


def truncate_copy(src, dst, fraction):
    with open(src, "rb") as f:
        data = f.read()
    with open(dst, "wb") as f:
        f.write(data[:int(len(data) * fraction)])
    print("> truncated", os.path.basename(dst), f"{fraction:.0%}")


def make_flv():
    run(video_in() + audio_in(440) + maps(1) + X264 + AAC + [path("flv_h264_aac.flv")])
    truncate_copy(path("flv_h264_aac.flv"), path("flv_truncated_60pct.flv"), 0.6)
    run(video_in("640x360", dur=8) + audio_in(550, 8) + maps(1)
        + ["-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "keyint=60:log-level=error"] + AAC
        + [path("flv_enhanced_hevc_aac.flv")])
    run(video_in("640x360", dur=6) + audio_in(660, 6) + maps(1)
        + ["-c:v", "libsvtav1", "-preset", "12", "-g", "60", "-pix_fmt", "yuv420p", "-svtav1-params", "log-level=0"]
        + AAC + [path("flv_enhanced_av1_aac.flv")])


def make_ts():
    args = video_in() + audio_in(330) + audio_in(550) + audio_in(770) + maps(3) + X264 + AAC
    for i, lang in enumerate(LANGS):
        args += [f"-metadata:s:a:{i}", f"language={lang}"]
    run(args + [path("ts_h264_3aac_lang.ts")])
    truncate_copy(path("ts_h264_3aac_lang.ts"), path("ts_truncated_60pct.ts"), 0.6)
    x265 = "keyint=60:repeat-headers=1:log-level=error"
    run(video_in() + audio_in(330) + audio_in(550) + maps(2)
        + ["-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le", "-x265-params", x265] + AAC
        + ["-metadata:s:a:0", "language=chi", "-metadata:s:a:1", "language=eng", path("ts_hevc10_2aac.ts")])
    run(video_in(dur=12) + audio_in(440, 11, offset=0.3) + maps(1) + X264 + AAC
        + [path("ts_start1.4_audio_late.ts")])
    run(video_in("1280x720", dur=10) + audio_in(440, 10) + maps(1) + X264 + ["-c:a", "ac3", "-b:a", "192k"]
        + ["-f", "mpegts", "-mpegts_m2ts_mode", "1", path("m2ts_h264_ac3.m2ts")])
    seg_a, seg_b = path("_seg_a.ts"), path("_seg_b.ts")
    run(video_in("640x360", dur=10) + audio_in(440, 10) + maps(1) + X264 + AAC + [seg_a])
    run(video_in("640x360", dur=8) + audio_in(660, 8) + maps(1) + X264 + AAC + ["-output_ts_offset", "5000", seg_b])
    with open(path("ts_discontinuity.ts"), "wb") as f:
        for p in (seg_a, seg_b):
            with open(p, "rb") as g:
                f.write(g.read())
            os.remove(p)
    print("> joined ts_discontinuity.ts")


def make_export():
    names = ["游戏声音 Game", "麦克风 Mic", "音乐 Music"]
    args = video_in("640x360", dur=10) + audio_in(330, 10) + audio_in(550, 10) + audio_in(770, 10) + maps(3) + X264 + AAC
    for i, n in enumerate(names):
        args += [f"-metadata:s:a:{i}", f"handler_name={n}", f"-metadata:s:a:{i}", f"language={LANGS[i]}",
                 f"-disposition:a:{i}", "default" if i == 0 else "0"]
    run(args + ["-movflags", "+faststart", path("plain_3aac.mp4", EXPORT)])
    run(video_in("640x360", dur=10) + audio_in(440, 9, offset=0.5) + maps(1) + X264 + AAC
        + ["-metadata:s:a:0", "title=麦克风 晚开始", path("audio_late.mkv", EXPORT)])
    run(video_in("640x360", dur=6) + audio_in(440, 6) + audio_in(660, 6) + maps(2) + X264
        + ["-c:a:0", "aac", "-b:a:0", "128k", "-c:a:1", "libmp3lame", "-b:a:1", "128k",
           "-metadata:s:a:0", 'title=Mic: "主播"/<1>?*|\\ ', "-metadata:s:a:1", "title=con.",
           path("bad_title.mkv", EXPORT)])


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(EXPORT, exist_ok=True)
    make_flv()
    make_ts()
    make_export()
    print("done:", OUT, EXPORT)


if __name__ == "__main__":
    main()
