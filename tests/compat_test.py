import glob
import json
import os
import shutil
import struct
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "media")
OUT = os.path.join(HERE, "compat_out")
RESULTS = os.path.join(HERE, "compat_results.json")
MODES = [("plain", []), ("unofficial", ["-strict", "unofficial"]), ("experimental", ["-strict", "experimental"])]
COPY_SOURCES = ["multi.mkv", "hevc10_rare_audio.mkv", "av1_opus.mkv", "vp9_vorbis.mkv", "vp8_vorbis.mkv",
                "mpeg2_mp2.mkv", "theora_vorbis.mkv", "dvdsub.mkv", "pgs.mkv"]

results = {}


def ff(args, cwd=None):
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error"] + args
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", cwd=cwd)
    return r.returncode, r.stderr.strip()


def probe(path, extra=None):
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-show_chapters", "-of", "json"] + (extra or []) + [path]
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        data = {}
    data["_rc"] = r.returncode
    data["_err"] = r.stderr.strip()[-400:]
    return data


def media(name):
    return os.path.join(MEDIA, name)


def outp(name):
    return os.path.join(OUT, name)


def short(err):
    lines = [l for l in err.splitlines() if l.strip()]
    return " | ".join(lines[:3])[:400]


def stream_summary(s):
    tags = s.get("tags", {})
    disp = s.get("disposition", {})
    return {
        "codec": s.get("codec_name"),
        "tag": s.get("codec_tag_string"),
        "language": tags.get("language"),
        "title": tags.get("title"),
        "handler_name": tags.get("handler_name"),
        "default": disp.get("default"),
        "forced": disp.get("forced"),
        "attached_pic": disp.get("attached_pic"),
    }


def decode_check(path, stype):
    if stype == "subtitle":
        r = subprocess.run(["ffprobe", "-v", "error", "-show_frames", "-of", "json", path],
                           capture_output=True, encoding="utf-8", errors="replace")
        frames = json.loads(r.stdout or "{}").get("frames", [])
        n = sum(1 for f in frames if f.get("media_type") == "subtitle")
        return r.returncode == 0 and n > 0 and not r.stderr.strip(), f"{n} subtitle events" + (f"; {short(r.stderr)}" if r.stderr.strip() else "")
    rc, err = ff(["-i", path, "-map", "0", "-f", "null", "-"])
    return rc == 0 and not err, short(err) or "clean"


def per_stream_copy():
    rows = []
    for name in COPY_SOURCES:
        src = media(name)
        if not os.path.isfile(src):
            continue
        info = probe(src)
        stem = os.path.splitext(name)[0]
        for s in info.get("streams", []):
            if s["codec_type"] == "attachment" or s.get("disposition", {}).get("attached_pic"):
                continue
            idx, codec = s["index"], s["codec_name"]
            variants = [("", [])]
            if codec == "hevc":
                variants = [("", []), ("_hvc1", ["-tag:v", "hvc1"])]
            for suffix, vargs in variants:
                row = {"file": name, "index": idx, "type": s["codec_type"], "codec": codec + suffix,
                       "src": stream_summary(s), "works_with": None, "errors": {}}
                for mode, margs in MODES:
                    dst = outp(f"{stem}_s{idx}_{codec}{suffix}_{mode}.mp4")
                    rc, err = ff(["-i", src, "-map", f"0:{idx}", "-c", "copy"] + vargs + margs + [dst])
                    if rc == 0:
                        row["works_with"] = mode
                        row["cmd"] = f'ffmpeg -i "{name}" -map 0:{idx} -c copy {" ".join(vargs + margs)} out.mp4'.replace("  ", " ")
                        ok, msg = decode_check(dst, s["codec_type"])
                        row["decode_ok"], row["decode_msg"] = ok, msg
                        p = probe(dst)
                        row["out"] = stream_summary(p["streams"][0]) if p.get("streams") else None
                        break
                    row["errors"][mode] = short(err)
                rows.append(row)
                print(f"{name:24} #{idx:<2} {row['codec']:20} -> {row['works_with']}  decode={row.get('decode_ok')}")
    results["per_stream_copy"] = rows


def subtitle_tests():
    rows = []
    multi = media("multi.mkv")
    for idx, label in [(4, "srt"), (5, "ass"), (6, "webvtt")]:
        dst = outp(f"sub_{label}_movtext.mp4")
        rc, err = ff(["-i", multi, "-map", f"0:{idx}", "-c:s", "mov_text", dst])
        row = {"case": f"{label} -> mov_text", "rc": rc, "err": short(err)}
        if rc == 0:
            row["decode_ok"], row["decode_msg"] = decode_check(dst, "subtitle")
            row["out"] = stream_summary(probe(dst)["streams"][0])
            back = outp(f"sub_{label}_movtext_back.srt")
            ff(["-i", dst, "-map", "0:s", back])
            with open(back, encoding="utf-8", errors="replace") as fh:
                row["roundtrip_srt"] = fh.read()[:400]
        rows.append(row)
    for idx, label, ext in [(4, "srt", "srt"), (5, "ass", "ass"), (6, "webvtt", "vtt")]:
        dst = outp(f"sidecar_s{idx}.{ext}")
        rc, err = ff(["-i", multi, "-map", f"0:{idx}", "-c:s", "copy", dst])
        row = {"case": f"{label} sidecar .{ext} (copy)", "rc": rc, "err": short(err)}
        if rc == 0:
            with open(dst, encoding="utf-8", errors="replace") as fh:
                row["content_head"] = fh.read()[:600]
        rows.append(row)
    for name, idx, ext, fmt in [("pgs.mkv", 2, "sup", None), ("dvdsub.mkv", 2, "mks", None)]:
        src = media(name)
        if not os.path.isfile(src):
            continue
        dst = outp(f"sidecar_{os.path.splitext(name)[0]}.{ext}")
        rc, err = ff(["-i", src, "-map", f"0:{idx}", "-c:s", "copy", dst])
        row = {"case": f"{name} -> .{ext} sidecar (copy)", "rc": rc, "err": short(err)}
        if rc == 0:
            row["size"] = os.path.getsize(dst)
            row["decode_ok"], row["decode_msg"] = decode_check(dst, "subtitle")
        rows.append(row)
    for name in ["pgs.mkv", "dvdsub.mkv"]:
        src = media(name)
        if not os.path.isfile(src):
            continue
        for target in ["mov_text", "dvdsub"]:
            dst = outp(f"{os.path.splitext(name)[0]}_to_{target}.mp4")
            rc, err = ff(["-i", src, "-map", "0:s", "-c:s", target, dst])
            rows.append({"case": f"{name} bitmap -> {target} re-encode into mp4", "rc": rc, "err": short(err)})
    for name, idx in [("dvdsub.mkv", 2), ("multi.mkv", 4)]:
        dst = outp(f"vobsub_try_{os.path.splitext(name)[0]}.sub")
        rc, err = ff(["-i", media(name), "-map", f"0:{idx}", "-c:s", "copy", "-f", "vobsub", dst])
        rows.append({"case": f"{name}#{idx} -> -f vobsub", "rc": rc, "err": short(err)})
    for name, dst_name, args in [
        ("dvdsub.mkv", "dvdsub_in_mp4_with_video.mp4", ["-map", "0", "-c", "copy"]),
        ("pgs.mkv", "pgs_in_mp4_with_video.mp4", ["-map", "0", "-c", "copy"]),
    ]:
        src = media(name)
        if not os.path.isfile(src):
            continue
        rc, err = ff(["-i", src] + args + [outp(dst_name)])
        row = {"case": f"{name} full -map 0 -c copy -> mp4", "rc": rc, "err": short(err)}
        if rc == 0:
            p = probe(outp(dst_name))
            row["streams"] = [stream_summary(s) for s in p.get("streams", [])]
            ok, msg = decode_check(outp(dst_name), "subtitle")
            row["sub_decode_ok"], row["sub_decode_msg"] = ok, msg
            rcv, errv = ff(["-i", outp(dst_name), "-filter_complex", "[0:v][0:s]overlay", "-f", "null", "-"])
            row["overlay_render_rc"], row["overlay_render_err"] = rcv, short(errv)
        rows.append(row)
    results["subtitles"] = rows


def full_multi():
    rows = []
    multi = media("multi.mkv")
    base = ["-i", multi, "-map", "0:v:0", "-map", "0:a", "-map", "0:s", "-map", "0:8",
            "-c", "copy", "-c:s", "mov_text", "-disposition:v:1", "attached_pic",
            "-map_metadata", "0", "-map_chapters", "0"]
    variants = {
        "no_use_metadata_tags": ["-movflags", "+faststart"],
        "use_metadata_tags": ["-movflags", "+faststart+use_metadata_tags"],
        "use_metadata_tags_handler": ["-movflags", "+faststart+use_metadata_tags",
                                      "-metadata:s:a:0", "handler_name=日语", "-metadata:s:a:1", "handler_name=English 5.1",
                                      "-metadata:s:a:2", "handler_name=国语", "-metadata:s:s:0", "handler_name=简体中文",
                                      "-metadata:s:s:1", "handler_name=English Signs (ASS)",
                                      "-metadata:s:s:2", "handler_name=WebVTT 日本語"],
    }
    for label, extra in variants.items():
        dst = outp(f"multi_full_{label}.mp4")
        args = base + extra + [dst]
        rc, err = ff(args)
        row = {"variant": label, "rc": rc, "err": short(err), "cmd": "ffmpeg " + " ".join(a if " " not in a else f'"{a}"' for a in args)}
        if rc == 0:
            p = probe(dst)
            row["format_tags"] = p.get("format", {}).get("tags", {})
            row["chapters"] = [(c.get("start_time"), c.get("end_time"), c.get("tags", {}).get("title")) for c in p.get("chapters", [])]
            row["streams"] = [stream_summary(s) for s in p.get("streams", [])]
            row["atoms"] = top_atoms(dst)
            dec_rc, dec_err = ff(["-i", dst, "-map", "0:v:0", "-map", "0:a", "-f", "null", "-"])
            row["decode_av_ok"] = dec_rc == 0 and not dec_err
        rows.append(row)
        print("full", label, rc, short(err))
    dst = outp("multi_naive_map0.mp4")
    rc, err = ff(["-i", multi, "-map", "0", "-c", "copy", dst])
    rows.append({"variant": "naive -map 0 -c copy", "rc": rc, "err": short(err)})
    dst = outp("multi_naive_map0_movtext.mp4")
    rc, err = ff(["-i", multi, "-map", "0", "-c", "copy", "-c:s", "mov_text", dst])
    rows.append({"variant": "naive -map 0 -c copy -c:s mov_text", "rc": rc, "err": short(err)})
    dst = outp("multi_map0_minus_t.mp4")
    rc, err = ff(["-i", multi, "-map", "0", "-map", "-0:t", "-c", "copy", "-c:s", "mov_text", dst])
    row = {"variant": "-map 0 -map -0:t -c copy -c:s mov_text", "rc": rc, "err": short(err)}
    if rc == 0:
        row["streams"] = [stream_summary(s) for s in probe(dst).get("streams", [])]
    rows.append(row)
    results["multi_full"] = rows


def top_atoms(path):
    atoms = []
    with open(path, "rb") as fh:
        while True:
            hdr = fh.read(8)
            if len(hdr) < 8:
                break
            size, typ = struct.unpack(">I4s", hdr)
            if size == 1:
                size = struct.unpack(">Q", fh.read(8))[0]
                fh.seek(size - 16, 1)
            elif size == 0:
                atoms.append(typ.decode("latin-1"))
                break
            else:
                fh.seek(size - 8, 1)
            atoms.append(typ.decode("latin-1"))
    return atoms


def attachments():
    rows = []
    d = outp("dump")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    rc, err = ff(["-dump_attachment:t", "", "-i", media("multi.mkv")], cwd=d)
    rows.append({"case": '-dump_attachment:t "" -i multi.mkv (no output)', "rc": rc, "err": short(err), "files": sorted(os.listdir(d))})
    d2 = outp("dump2")
    shutil.rmtree(d2, ignore_errors=True)
    os.makedirs(d2)
    rc, err = ff(["-dump_attachment:t", "", "-i", media("multi.mkv"), "-f", "null", "-"], cwd=d2)
    rows.append({"case": '-dump_attachment:t "" -i multi.mkv -f null -', "rc": rc, "err": short(err), "files": sorted(os.listdir(d2))})
    d3 = outp("dump3")
    shutil.rmtree(d3, ignore_errors=True)
    os.makedirs(d3)
    rc, err = ff(["-dump_attachment:8", "cover_from_dump.jpg", "-i", media("multi.mkv"), "-f", "null", "-"], cwd=d3)
    rows.append({"case": "-dump_attachment:8 (cover, demuxed as attached_pic video)", "rc": rc, "err": short(err), "files": sorted(os.listdir(d3))})
    jpg = outp("cover_by_copy.jpg")
    rc, err = ff(["-i", media("multi.mkv"), "-map", "0:8", "-c", "copy", "-frames:v", "1", "-update", "1", jpg])
    same = None
    if rc == 0:
        with open(jpg, "rb") as a, open(os.path.join(MEDIA, "_src", "cover.jpg"), "rb") as b:
            same = a.read() == b.read()
    rows.append({"case": "-map 0:8 -c copy -frames:v 1 -update 1 cover.jpg", "rc": rc, "err": short(err), "byte_identical_to_source": same})
    font = os.path.join(d2, "testfont.ttf")
    if os.path.isfile(font):
        with open(font, "rb") as a, open(os.path.join(MEDIA, "_src", "testfont.ttf"), "rb") as b:
            rows.append({"case": "dumped testfont.ttf byte-identical", "result": a.read() == b.read()})
    dst = outp("cover_only_attached_pic.mp4")
    rc, err = ff(["-i", media("already_compatible.mkv"), "-i", os.path.join(MEDIA, "_src", "cover.jpg"),
                  "-map", "0", "-map", "1", "-c", "copy", "-disposition:v:1", "attached_pic", dst])
    row = {"case": "external cover.jpg as attached_pic", "rc": rc, "err": short(err)}
    if rc == 0:
        row["streams"] = [stream_summary(s) for s in probe(dst).get("streams", [])]
    rows.append(row)
    dst = outp("font_attach_into_mp4.mp4")
    rc, err = ff(["-i", media("multi.mkv"), "-map", "0:v:0", "-map", "0:7", "-c", "copy", dst])
    rows.append({"case": "font attachment stream into mp4", "rc": rc, "err": short(err)})
    results["attachments"] = rows


def hdr_tests():
    rows = []
    src = media("hevc10_rare_audio.mkv")
    for label, path in [("source mkv", src)]:
        rows.append({"case": label, **hdr_probe(path)})
    for label, extra in [("copy default tag", []), ("copy -tag:v hvc1", ["-tag:v", "hvc1"])]:
        dst = outp(f"hdr_{label.replace(' ', '_').replace(':', '')}.mp4")
        rc, err = ff(["-i", src, "-map", "0:v", "-c", "copy"] + extra + [dst])
        rows.append({"case": label, "rc": rc, "err": short(err), **(hdr_probe(dst) if rc == 0 else {})})
    container_mkv = outp("hdr_container_level.mkv")
    rc, err = ff(["-i", src, "-map", "0:v", "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le",
                  "-x265-params", "log-level=error", container_mkv])
    rows.append({"case": "re-encode (decoder frame side data -> encoder) mkv", "rc": rc, "err": short(err), **(hdr_probe(container_mkv) if rc == 0 else {})})
    if rc == 0:
        dst = outp("hdr_container_level_copy.mp4")
        rc2, err2 = ff(["-i", container_mkv, "-map", "0:v", "-c", "copy", "-tag:v", "hvc1", dst])
        rows.append({"case": "container-level mkv -> mp4 copy hvc1", "rc": rc2, "err": short(err2), **(hdr_probe(dst) if rc2 == 0 else {})})
    results["hdr"] = rows


def hdr_probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", path],
                       capture_output=True, encoding="utf-8", errors="replace")
    s = (json.loads(r.stdout or "{}").get("streams") or [{}])[0]
    r2 = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1", "-show_frames",
                         "-show_entries", "frame=side_data_list,color_primaries,color_transfer,color_space", "-of", "json", path],
                        capture_output=True, encoding="utf-8", errors="replace")
    f = (json.loads(r2.stdout or "{}").get("frames") or [{}])[0]
    return {
        "codec_tag": s.get("codec_tag_string"),
        "pix_fmt": s.get("pix_fmt"),
        "color": [s.get("color_range"), s.get("color_space"), s.get("color_transfer"), s.get("color_primaries")],
        "stream_side_data": [d.get("side_data_type") for d in s.get("side_data_list", [])],
        "stream_side_data_full": s.get("side_data_list", []),
        "frame_side_data": [d.get("side_data_type") for d in f.get("side_data_list", [])],
        "frame_color": [f.get("color_space"), f.get("color_transfer"), f.get("color_primaries")],
    }


def misc_files():
    rows = []
    for name in ["中文 空格 [测试] (1).mkv", "no_audio.mkv", "already_compatible.mkv"]:
        src = media(name)
        dst = outp(os.path.splitext(name)[0] + ".mp4")
        args = ["-i", src, "-map", "0", "-c", "copy", "-c:s", "mov_text", "-map_metadata", "0", "-map_chapters", "0",
                "-movflags", "+faststart+use_metadata_tags", dst]
        rc, err = ff(args)
        row = {"file": name, "rc": rc, "err": short(err)}
        if rc == 0:
            row["streams"] = [stream_summary(s) for s in probe(dst).get("streams", [])]
            row["decode_ok"], row["decode_msg"] = decode_check(dst, "video")
            row["atoms"] = top_atoms(dst)
        rows.append(row)
    src = media("truncated.mkv")
    p = probe(src)
    row = {"file": "truncated.mkv", "probe_rc": p["_rc"], "probe_err": p["_err"][:300],
           "probe_duration": p.get("format", {}).get("duration"), "nb_streams": len(p.get("streams", []))}
    dst = outp("truncated.mp4")
    rc, err = ff(["-i", src, "-map", "0:v", "-map", "0:a", "-c", "copy", dst])
    row["convert_rc"], row["convert_err"] = rc, short(err)
    if os.path.isfile(dst):
        row["out_duration"] = probe(dst).get("format", {}).get("duration")
    vrc, verr = ff(["-v", "error", "-xerror", "-i", src, "-map", "0:v:0", "-f", "null", "-"])
    row["xerror_decode_rc"], row["xerror_decode_err"] = vrc, short(verr)
    rows.append(row)
    results["misc_files"] = rows


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    results["ffmpeg_version"] = subprocess.run(["ffmpeg", "-version"], capture_output=True, encoding="utf-8",
                                               errors="replace").stdout.splitlines()[0]
    per_stream_copy()
    subtitle_tests()
    full_multi()
    attachments()
    hdr_tests()
    misc_files()
    text = json.dumps(results, ensure_ascii=False, indent=1)
    root = os.path.dirname(HERE) + os.sep
    text = text.replace(json.dumps(root)[1:-1], "").replace(json.dumps(root.replace(os.sep, "/"))[1:-1], "")
    with open(RESULTS, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("written", RESULTS)


if __name__ == "__main__":
    main()
