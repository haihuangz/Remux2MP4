import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "media", "obs")
DUR = 20
TRACK_NAMES = ["游戏声音 Game", "麦克风 Mic", "音乐 Music", "Discord 语音", "系统提示音", "Track 6 备用"]


def run(args):
    print(">", " ".join(args[:6]), "...", args[-1])
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error"] + args,
                       capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print(p.stderr)
        raise SystemExit(f"ffmpeg failed for {args[-1]}")


def video_in(size="1280x720", rate=30):
    return ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={DUR}"]


def audio_in(freq):
    return ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={DUR}"]


def audio_tracks(n, first_input, names, codec_args):
    args = []
    for i in range(n):
        args += ["-map", f"{first_input + i}:a"]
    args += codec_args
    for i in range(n):
        args += [f"-metadata:s:a:{i}", f"title={names[i]}",
                 f"-disposition:a:{i}", "default" if i == 0 else "0"]
    return args


def path(name):
    return os.path.join(OUT, name)


def make_h264_6aac():
    ins = video_in()
    for i in range(6):
        ins += audio_in(220 * (i + 1))
    args = ins + ["-map", "0:v"] + audio_tracks(6, 1, TRACK_NAMES, ["-c:a", "aac", "-b:a", "160k", "-ac", "2"])
    args += ["-c:v", "libx264", "-preset", "veryfast", "-g", "60", "-pix_fmt", "yuv420p",
             "-metadata", "encoder=OBS Studio 31.0 (test)", path("obs_h264_6aac.mkv")]
    run(args)


def make_hevc10_hdr():
    x265 = ("hdr10=1:hdr10-opt=1:repeat-headers=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:"
            "master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):max-cll=1000,400:"
            "keyint=60:log-level=error")
    args = video_in() + audio_in(330) + audio_in(550)
    args += ["-map", "0:v"] + audio_tracks(2, 1, TRACK_NAMES, ["-c:a", "aac", "-b:a", "160k", "-ac", "2"])
    args += ["-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le", "-x265-params", x265,
             "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc",
             path("obs_hevc10_hdr_pq.mkv")]
    run(args)


def make_av1_opus():
    args = video_in("640x360") + audio_in(440) + audio_in(660)
    args += ["-map", "0:v"] + audio_tracks(2, 1, TRACK_NAMES, ["-c:a", "libopus", "-b:a", "128k"])
    args += ["-c:v", "libsvtav1", "-preset", "12", "-g", "60", "-pix_fmt", "yuv420p", path("obs_av1_opus.mkv")]
    run(args)


def make_flac_pcm():
    args = video_in("640x360") + audio_in(440) + audio_in(660) + audio_in(880)
    args += ["-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a",
             "-c:v", "libx264", "-preset", "veryfast", "-g", "60", "-pix_fmt", "yuv420p",
             "-c:a:0", "aac", "-b:a:0", "160k", "-c:a:1", "flac", "-c:a:2", "pcm_s16le"]
    for i, name in enumerate(["游戏声音 AAC", "麦克风 FLAC", "音乐 PCM"]):
        args += [f"-metadata:s:a:{i}", f"title={name}", f"-disposition:a:{i}", "default" if i == 0 else "0"]
    args.append(path("obs_flac_pcm.mkv"))
    run(args)


def truncate_copy(src, dst, fraction):
    with open(src, "rb") as f:
        data = f.read()
    with open(dst, "wb") as f:
        f.write(data[:int(len(data) * fraction)])
    print("> truncated", os.path.basename(dst), f"{fraction:.0%}")


def make_frag(name, fmt_flags, extra=()):
    args = video_in() + audio_in(330) + audio_in(550) + audio_in(770)
    args += ["-map", "0:v"] + audio_tracks(3, 1, TRACK_NAMES, ["-c:a", "aac", "-b:a", "160k", "-ac", "2"])
    args += ["-c:v", "libx264", "-preset", "veryfast", "-g", "60", "-pix_fmt", "yuv420p"]
    for i, name_ in enumerate(TRACK_NAMES[:3]):
        args += [f"-metadata:s:a:{i}", f"handler_name={name_}"]
    args += ["-movflags", fmt_flags] + list(extra) + [path(name)]
    run(args)


def main():
    os.makedirs(OUT, exist_ok=True)
    make_h264_6aac()
    make_hevc10_hdr()
    make_av1_opus()
    make_flac_pcm()
    truncate_copy(path("obs_h264_6aac.mkv"), path("obs_truncated_60pct.mkv"), 0.6)
    make_frag("obs_fragmented.mp4", "frag_keyframe+empty_moov+default_base_moof")
    make_frag("obs_fragmented.mov", "frag_keyframe+empty_moov+default_base_moof")
    make_frag("obs_hybrid_full.mp4", "frag_keyframe+default_base_moof")
    truncate_copy(path("obs_hybrid_full.mp4"), path("obs_hybrid_unfinalised.mp4"), 0.55)
    os.remove(path("obs_hybrid_full.mp4"))
    print("done:", OUT)


if __name__ == "__main__":
    main()
