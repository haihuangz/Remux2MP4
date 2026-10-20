import json
import os
import re
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MEDIA = os.path.join(HERE, "media")
BASE = os.path.join(HERE, "out", "_export")
ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
EXT = {"aac": ".m4a", "alac": ".m4a", "mp3": ".mp3", "flac": ".flac", "opus": ".opus", "vorbis": ".ogg", "ac3": ".ac3",
       "eac3": ".eac3", "pcm_s16le": ".wav", "pcm_s24le": ".wav", "pcm_f32le": ".wav"}
results = {}


def run(args):
    r = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout, r.stderr


def probe(path):
    rc, out, _ = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    return json.loads(out) if rc == 0 else None


def streamhash(path, idx, bsf=None):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-map", f"0:{idx}", "-c", "copy"]
    if bsf:
        cmd += ["-bsf:0", bsf]
    return run(cmd + ["-f", "streamhash", "-hash", "md5", "-"])[1].strip().split(",")[-1]


def check(name, ok, detail=""):
    results[name] = bool(ok)
    print(("PASS " if ok else "FAIL ") + name + (" :: " + detail if detail else ""))


def convert(src, export=True, sub=None):
    d = os.path.join(BASE, sub or os.path.splitext(os.path.basename(src))[0])
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    args = [sys.executable, os.path.join(ROOT, "mkv2mp4.py"), src, "-o", d] + (["--export-audio"] if export else [])
    rc, out, err = run(args)
    return d, rc, out + err


def tags(info, s):
    t = {k.lower(): v for k, v in (info["format"].get("tags") or {}).items()}
    t.update({k.lower(): v for k, v in (s.get("tags") or {}).items()})
    return t


def decoded_len(path, idx):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", f"0:{idx}", "-f", "s16le", "-"], capture_output=True)
    return len(r.stdout) if r.returncode == 0 else -1


def check_export(label, src, expect_names, ts=False, expect_status="成功", expect_text=(), out_mp4=True, lang=None,
                 suffix=""):
    d, rc, out = convert(src)
    stem = os.path.splitext(os.path.basename(src))[0] + suffix
    folder = os.path.join(d, stem + "_音轨")
    names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    check(f"{label}: folder and names", names == sorted(expect_names), f"{names}")
    check(f"{label}: names are Windows-safe", all(not ILLEGAL.search(n) and not n.endswith((" ", ".")) for n in names))
    check(f"{label}: CLI status {expect_status}", f"[{expect_status}]" in out and (rc == 0), f"rc={rc}")
    check(f"{label}: MP4 output {'present' if out_mp4 else 'absent'}",
          os.path.exists(os.path.join(d, stem + ".mp4")) == out_mp4)
    si = probe(src)
    audio = [s for s in si["streams"] if s["codec_type"] == "audio"]
    ok_hash, ok_start, ok_tags, details = True, True, True, []
    for n, s in enumerate(audio, 1):
        cands = [x for x in names if x.startswith(f"{n}-")]
        if not cands:
            ok_hash = False
            details.append(f"track {n} missing")
            continue
        p = os.path.join(folder, cands[0])
        if not cands[0].endswith(EXT.get(s["codec_name"], ".mka")):
            ok_hash = False
            details.append(f"{cands[0]} wrong extension for {s['codec_name']}")
        bsf = "aac_adtstoasc" if ts and s["codec_name"] == "aac" else None
        a, b = streamhash(src, s["index"], bsf), streamhash(p, 0)
        if a != b:
            ok_hash = False
            details.append(f"{cands[0]} hash {a} != {b}")
        ei = probe(p)
        es = ei["streams"][0]
        if ts:
            la, lb = decoded_len(src, s["index"]), decoded_len(p, 0)
            if la != lb or la <= 0:
                ok_start = False
                details.append(f"{cands[0]} decodes to {lb} bytes, source track {la}")
        if abs(float(es.get("start_time") or 0)) > 0.05:
            ok_start = False
            details.append(f"{cands[0]} starts at {es.get('start_time')}")
        t = tags(ei, es)
        title = (s.get("tags") or {}).get("title") or (s.get("tags") or {}).get("handler_name")
        if s["codec_name"] not in ("ac3", "eac3"):
            if title and title.strip() not in {v.strip() for v in t.values()}:
                ok_tags = False
                details.append(f"{cands[0]} title {title!r} not in tags {t}")
            want_lang = (s.get("tags") or {}).get("language")
            if want_lang and want_lang != "und" and t.get("language") != want_lang:
                ok_tags = False
                details.append(f"{cands[0]} language {t.get('language')} != {want_lang}")
    check(f"{label}: every exported file matches its source track (stream hash)", ok_hash, "; ".join(details))
    check(f"{label}: exported files start at their first sample, nothing cut", ok_start, "; ".join(details))
    check(f"{label}: title/language tags kept", ok_tags)
    rep = os.path.join(d, stem + ".转换报告.txt")
    text = open(rep, encoding="utf-8-sig").read() if os.path.exists(rep) else ""
    check(f"{label}: report lists every exported file", text and all(n in text for n in names))
    check(f"{label}: report has no absolute paths", text and d not in text and not re.search(r"[A-Za-z]:\\", text))
    for t in expect_text:
        check(f"{label}: report says {t!r}", t in text)
    check(f"{label}: no partial files", not any(".partial" in f for _, _, fs in os.walk(d) for f in fs))
    return d, out


def main():
    import tool_ffmpeg
    print(tool_ffmpeg.describe())
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE)
    obs = os.path.join(MEDIA, "obs")
    exp = os.path.join(MEDIA, "export")
    names6 = ["游戏声音 Game", "麦克风 Mic", "音乐 Music", "Discord 语音", "系统提示音", "Track 6 备用"]
    check_export("6-track OBS MKV", os.path.join(obs, "obs_h264_6aac.mkv"),
                 [f"{i}-{n}.m4a" for i, n in enumerate(names6, 1)], expect_text=("另存的音轨",))
    check_export("Opus", os.path.join(obs, "obs_av1_opus.mkv"), ["1-游戏声音 Game.opus", "2-麦克风 Mic.opus"])
    check_export("FLAC + PCM", os.path.join(obs, "obs_flac_pcm.mkv"),
                 ["1-游戏声音 AAC.m4a", "2-麦克风 FLAC.flac", "3-音乐 PCM.wav"])
    _, out = check_export("plain MP4, export only", os.path.join(exp, "plain_3aac.mp4"),
                          ["1-游戏声音 Game.m4a", "2-麦克风 Mic.m4a", "3-音乐 Music.m4a"], out_mp4=False,
                          expect_text=("已经是普通 MP4", "只另存音轨"))
    check("plain MP4, export only: summary names the folder", "plain_3aac_音轨" in out)
    d, rc, out = convert(os.path.join(exp, "plain_3aac.mp4"), export=False, sub="plain_no_export")
    check("plain MP4 without the option: still skipped, nothing written", "[跳过]" in out and not os.listdir(d), str(os.listdir(d)))
    check_export("audio later than video", os.path.join(exp, "audio_late.mkv"), ["1-麦克风 晚开始.m4a"],
                 expect_status="完成（有提示）", expect_text=("这条音轨比画面晚 0.500 秒开始，剪辑时请对齐",))
    d, _ = check_export("illegal characters in titles", os.path.join(exp, "bad_title.mkv"),
                        ["1-Mic_ _主播___1_____.m4a", "2-con.mp3"])
    check_export("fragmented MP4, audio 0.067 s before video (below 0.1 s: note only, status ok)",
                 os.path.join(MEDIA, "fmp4", "frag_hevc_hvc1.mp4"), ["1-音轨1.m4a"], suffix="_标准MP4",
                 expect_text=("1-音轨1.m4a：这条音轨比画面早 0.067 秒开始",))
    check_export("TS with languages", os.path.join(MEDIA, "flv_ts", "ts_h264_3aac_lang.ts"),
                 ["1-chi.m4a", "2-eng.m4a", "3-jpn.m4a"], ts=True)
    check_export("TS audio starting 0.279 s after video", os.path.join(MEDIA, "flv_ts", "ts_start1.4_audio_late.ts"),
                 ["1-音轨1.m4a"], ts=True, expect_status="完成（有提示）", expect_text=("这条音轨比画面晚 0.279 秒开始",))
    gen = os.path.join(BASE, "_src")
    os.makedirs(gen)
    late = os.path.join(MEDIA, "flv_ts", "ts_start1.4_audio_late.ts")
    two = os.path.join(gen, "ts_two_late.ts")
    run(["ffmpeg", "-v", "error", "-i", late, "-itsoffset", "0.3", "-i", late, "-itsoffset", "0.7", "-i", late,
         "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c", "copy", "-f", "mpegts", two])
    check_export("TS, two tracks starting 0.3 s and 0.7 s after video", two, ["1-音轨1.m4a", "2-音轨2.m4a"], ts=True,
                 expect_status="完成（有提示）", expect_text=("1-音轨1.m4a：这条音轨比画面晚 0.300 秒开始",
                                                       "2-音轨2.m4a：这条音轨比画面晚 0.700 秒开始"))
    blank = os.path.join(gen, "blank_titles.mkv")
    run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=2", "-f", "lavfi", "-i", "sine=d=2:f=660", "-f", "lavfi",
         "-i", "sine=d=2:f=880", "-map", "0", "-map", "1", "-map", "2", "-c:a", "aac",
         "-metadata:s:a:0", "title=   ", "-metadata:s:a:1", "title=..", "-metadata:s:a:1", "language=eng",
         "-metadata:s:a:2", "title= . ", blank])
    check_export("titles of only spaces/dots fall back", blank, ["1-音轨1.m4a", "2-eng.m4a", "3-音轨3.m4a"], out_mp4=True)
    print("ALL PASS" if all(results.values()) else "SOME FAILED", f"({sum(results.values())}/{len(results)})")


if __name__ == "__main__":
    main()
