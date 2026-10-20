import hashlib
import os
import shutil
import subprocess
import sys
import threading

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mkv2mp4_core as core

MEDIA = os.path.join(HERE, "media")
BASE = os.path.join(HERE, "out", "_fixchk")
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE)
OBS = os.path.join(MEDIA, "obs", "obs_h264_6aac.mkv")
results = {}


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fresh(name):
    d = os.path.join(BASE, name)
    os.makedirs(d)
    return d


def check(name, ok, detail=""):
    results[name] = bool(ok)
    print(("PASS " if ok else "FAIL ") + name + (" :: " + detail if detail else ""))


import tool_ffmpeg
print(tool_ffmpeg.describe())
src_md5 = md5(OBS)

d = fresh("read_error_full")
orig_run = core.FFmpegRunner.run


def run_with_fake_io_error(self, args, *a, **kw):
    rc, err = orig_run(self, args, *a, **kw)
    return rc, err + ["[matroska,webm @ 0000] I/O error"]


core.FFmpegRunner.run = run_with_fake_io_error
r = core.Converter(core.Options(out_dir=d)).convert(OBS)
check("read error, full length -> corrupt-packet warning, not OBS crash",
      r.status == "warn" and "OBS" not in r.message and any("损坏的数据包" in w for w in r.warnings), r.message)

d = fresh("read_error_short")
orig_build = core.build_command


def build_short(src, plan, partial_main, *a, **kw):
    args = orig_build(src, plan, partial_main, *a, **kw)
    i = args.index(partial_main)
    return args[:i] + ["-t", "8"] + args[i:]


core.build_command = build_short
r = core.Converter(core.Options(out_dir=d)).convert(OBS)
check("read error, output short -> error, keep source",
      r.status == "failed" and "请勿删除源文件" in r.message and "OBS" not in r.message, r.message)
core.build_command = orig_build
core.FFmpegRunner.run = orig_run

d = fresh("cancel_verify")
ev = threading.Event()


def log(m):
    if "逐包比对" in m:
        ev.set()


r = core.Converter(core.Options(out_dir=d), log=log, cancel_event=ev).convert(OBS)
left = os.listdir(d)
check("cancel during verify -> cancelled, nothing left", r.status == "cancelled" and not left, f"{r.status} {left}")

d = fresh("json_collision")
src = os.path.join(MEDIA, "multi.mkv")
jp = os.path.join(d, "multi.源文件信息.json")
with open(jp, "w", encoding="utf-8") as f:
    f.write("USER FILE")
r = core.Converter(core.Options(out_dir=d, verify=False)).convert(src)
with open(jp, encoding="utf-8") as f:
    kept = f.read() == "USER FILE"
check("existing .源文件信息.json not overwritten", kept and os.path.basename(r.output) == "multi (1).mp4",
      os.path.basename(r.output))

d = fresh("sidecar_glob")
open(os.path.join(d, "multi.2024.10.20.mkv"), "wb").close()
open(os.path.join(d, "other.4.chi.srt"), "wb").close()
folder, stem, ext = core.choose_output(src, "mkv", core.Options(out_dir=d), "mp4")
open(os.path.join(d, "x.4.chi.srt"), "wb").close()
_, stem2, _ = core.choose_output(os.path.join(d, "x.mkv"), "mkv", core.Options(out_dir=d), "mp4")
check("unrelated 'multi.2024.10.20.mkv' no longer forces (1); own sidecar still does", stem == "multi" and stem2 == "x (1)",
      f"{stem} / {stem2}")

info = core.probe(os.path.join(MEDIA, "vp8_vorbis.mkv"))
plan = core.build_plan(info, "mkv", core.Options(), ".mkv")
size = os.path.getsize(os.path.join(MEDIA, "vp8_vorbis.mkv"))
extra = core.estimate_extra_bytes(info, plan, size, core._fdur(info["format"]["duration"]))
check("space estimate includes re-encode + sidecar", extra >= size, f"extra={extra} src={size}")

hdr_src = os.path.join(BASE, "prores_hdr.mkv")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25", "-t", "2",
                "-vf", "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc",
                "-c:v", "prores_ks", "-pix_fmt", "yuv422p10le", "-color_primaries", "bt2020", "-color_trc", "smpte2084",
                "-colorspace", "bt2020nc", hdr_src], check=True)
d = fresh("hdr_reencode")
r = core.Converter(core.Options(out_dir=d)).convert(hdr_src)
out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                      "stream=codec_name,codec_tag_string,pix_fmt,color_transfer,color_primaries,color_space",
                      "-of", "compact=p=0", r.output], capture_output=True, encoding="utf-8", errors="replace").stdout.strip()
check("HDR 10-bit re-encode -> hevc hvc1 10-bit with PQ/bt2020 tags",
      "hevc" in out and "hvc1" in out and "yuv420p10le" in out and "smpte2084" in out and "bt2020" in out, out)

d = fresh("readonly")
os.chmod(d, 0o444)
ro = subprocess.run(["icacls", d, "/deny", "Everyone:(W,AD,WD)"], capture_output=True)
r = core.Converter(core.Options(out_dir=d)).convert(src)
subprocess.run(["icacls", d, "/remove:d", "Everyone"], capture_output=True)
os.chmod(d, 0o777)
check("unwritable output folder -> Chinese message, no retry ladder",
      r.status == "failed" and "不能写入" in r.message and not os.listdir(d), r.message)

check("source unchanged", md5(OBS) == src_md5)
print("ALL PASS" if all(results.values()) else "SOME FAILED")
