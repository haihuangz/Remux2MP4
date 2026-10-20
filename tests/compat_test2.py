import hashlib
import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "media")
SRC = os.path.join(MEDIA, "_src")
EXTRA = os.path.join(MEDIA, "extra")
OUT = os.path.join(HERE, "compat_out", "t2")
RESULTS = os.path.join(HERE, "compat_results2.json")
MULTI = os.path.join(MEDIA, "multi.mkv")

results = {}


def ff(args, cwd=None):
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error"] + args
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", cwd=cwd)
    return r.returncode, r.stderr.strip()


def short(err):
    lines = [l for l in err.splitlines() if l.strip()]
    return " | ".join(lines[:3])[:400]


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-show_chapters", "-of", "json", path],
                       capture_output=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def streams(path):
    rows = []
    for s in probe(path).get("streams", []):
        d = s.get("disposition", {})
        rows.append({"i": s["index"], "type": s.get("codec_type"), "codec": s.get("codec_name"), "tag": s.get("codec_tag_string"),
                     "tags": s.get("tags", {}), "disp": [k for k, v in d.items() if v]})
    return rows


def o(name):
    return os.path.join(OUT, name)


def md5(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def contains(path, *needles):
    with open(path, "rb") as fh:
        data = fh.read()
    return {n if isinstance(n, str) else n.decode("latin-1"): (n.encode("utf-8") if isinstance(n, str) else n) in data for n in needles}


def find_atom_path(path, target):
    containers = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"ilst", b"edts", b"dinf", b"tref"}
    hits = []
    with open(path, "rb") as fh:
        data = fh.read()

    def walk(start, end, trail):
        pos = start
        while pos + 8 <= end:
            size = int.from_bytes(data[pos:pos + 4], "big")
            typ = data[pos + 4:pos + 8]
            hdr = 8
            if size == 1:
                size = int.from_bytes(data[pos + 8:pos + 16], "big")
                hdr = 16
            elif size == 0:
                size = end - pos
            if size < 8 or pos + size > end:
                return
            name = typ.decode("latin-1")
            if typ == target:
                hits.append("/".join(trail + [name]))
            if typ in containers:
                walk(pos + hdr, pos + size, trail + [name])
            elif typ == b"meta":
                walk(pos + hdr + 4, pos + size, trail + [name])
            elif typ == b"keys":
                pass
            elif trail and trail[-1] == "ilst":
                walk(pos + hdr, pos + size, trail + [name])
            pos += size

    walk(0, len(data), [])
    return hits


def stream_titles():
    rows = []
    base = ["-i", MULTI, "-map", "0:v:0", "-map", "0:a", "-map", "0:s", "-c", "copy", "-c:s", "mov_text",
            "-map_metadata", "0", "-map_chapters", "0"]
    titles = {"a:0": "日语", "a:1": "English 5.1", "a:2": "国语", "s:0": "简体中文", "s:1": "English Signs (ASS)", "s:2": "WebVTT 日本語"}
    explicit = []
    for k, v in titles.items():
        explicit += [f"-metadata:s:{k}", f"title={v}"]
    handler = []
    for k, v in titles.items():
        handler += [f"-metadata:s:{k}", f"handler_name={v}"]
    variants = {
        "default": [],
        "use_metadata_tags": ["-movflags", "+use_metadata_tags"],
        "explicit_title": explicit,
        "explicit_title_use_metadata_tags": explicit + ["-movflags", "+use_metadata_tags"],
        "handler_name": handler,
        "handler_and_title": handler + explicit,
    }
    for label, extra in variants.items():
        dst = o(f"title_{label}.mp4")
        rc, err = ff(base + extra + [dst])
        row = {"variant": label, "rc": rc, "err": short(err), "args_extra": " ".join(extra)}
        if rc == 0:
            row["streams"] = [{"i": s["i"], "codec": s["codec"], "title": s["tags"].get("title"),
                               "handler_name": s["tags"].get("handler_name"), "language": s["tags"].get("language")} for s in streams(dst)]
            row["title_bytes_in_file"] = contains(dst, "English 5.1", "简体中文")
            row["udta_name_atoms"] = find_atom_path(dst, b"name")
        rows.append(row)
        print("title", label, rc)
    results["stream_titles"] = rows


def global_tags():
    rows = []
    base = ["-i", MULTI, "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-map_metadata", "0"]
    variants = {
        "no_flag": [],
        "use_metadata_tags": ["-movflags", "+use_metadata_tags"],
        "no_map_metadata_flag_default": None,
    }
    for label, extra in variants.items():
        dst = o(f"gtags_{label}.mp4")
        args = (["-i", MULTI, "-map", "0:v:0", "-map", "0:a:0", "-c", "copy"] if extra is None else base + extra) + [dst]
        rc, err = ff(args)
        row = {"variant": label, "cmd_tail": " ".join(args[2:-1]), "rc": rc, "err": short(err)}
        if rc == 0:
            row["format_tags"] = probe(dst).get("format", {}).get("tags", {})
            row["itunes_atoms"] = {k: bool(find_atom_path(dst, k.encode("latin-1"))) for k in ["\xa9nam", "\xa9ART", "\xa9day", "\xa9cmt", "\xa9too"]}
            row["mdta_keys_box"] = contains(dst, b"keys", b"mdta", b"MY_CUSTOM_TAG")
        rows.append(row)
        print("gtags", label, rc)
    meta = o("global.ffmetadata.txt")
    rc, err = ff(["-i", MULTI, "-f", "ffmetadata", meta])
    row = {"variant": "-f ffmetadata sidecar", "rc": rc, "err": short(err)}
    if rc == 0:
        with open(meta, encoding="utf-8", errors="replace") as fh:
            row["content"] = fh.read()[:1500]
    rows.append(row)
    rc, err = ff(["-i", MULTI, "-i", meta, "-map", "0:v:0", "-c", "copy", "-map_metadata", "1", "-map_chapters", "1",
                  o("gtags_from_ffmetadata.mp4")])
    row = {"variant": "re-import ffmetadata as input 1 (-map_metadata 1 -map_chapters 1)", "rc": rc, "err": short(err)}
    if rc == 0:
        p = probe(o("gtags_from_ffmetadata.mp4"))
        row["format_tags"] = p.get("format", {}).get("tags", {})
        row["chapters"] = [c.get("tags", {}).get("title") for c in p.get("chapters", [])]
    rows.append(row)
    results["global_tags"] = rows


def chapters():
    rows = []
    for label, extra in [("no -map_chapters (default)", []), ("-map_chapters 0", ["-map_chapters", "0"]),
                         ("-map_chapters -1", ["-map_chapters", "-1"])]:
        dst = o(f"chap_{len(rows)}.mp4")
        rc, err = ff(["-i", MULTI, "-map", "0:v:0", "-c", "copy"] + extra + [dst])
        row = {"variant": label, "rc": rc, "err": short(err)}
        if rc == 0:
            p = probe(dst)
            row["chapters"] = [(c.get("start_time"), c.get("end_time"), c.get("tags", {}).get("title")) for c in p.get("chapters", [])]
            row["streams"] = [(s["i"], s["type"], s["codec"], s["tag"], s["tags"].get("handler_name")) for s in streams(dst)]
            row["chpl_atom"] = find_atom_path(dst, b"chpl")
            row["chap_tref"] = find_atom_path(dst, b"chap")
        rows.append(row)
    results["chapters"] = rows


def cover_art():
    rows = []
    for name in ["multi_full_no_use_metadata_tags.mp4", "multi_full_use_metadata_tags.mp4", "cover_only_attached_pic.mp4"]:
        path = os.path.join(HERE, "compat_out", name)
        if not os.path.isfile(path):
            continue
        row = {"file": name, "covr_atom": find_atom_path(path, b"covr")}
        back = o(f"cover_back_{len(rows)}.jpg")
        vidx = [s["i"] for s in streams(path) if "attached_pic" in s["disp"]]
        if vidx:
            rc, err = ff(["-i", path, "-map", f"0:{vidx[0]}", "-c", "copy", "-frames:v", "1", "-update", "1", back])
            row["extract_rc"] = rc
            if rc == 0:
                row["byte_identical_to_source_cover"] = md5(back) == md5(os.path.join(SRC, "cover.jpg"))
        rows.append(row)
    png = o("cover.png")
    ff(["-i", os.path.join(SRC, "cover.jpg"), png])
    mkv = os.path.join(EXTRA, "png_cover.mkv")
    rc, err = ff(["-i", os.path.join(MEDIA, "already_compatible.mkv"), "-map", "0", "-c", "copy",
                  "-attach", png, "-metadata:s:t:0", "mimetype=image/png", "-metadata:s:t:0", "filename=cover.png", mkv])
    row = {"case": "png cover attachment mkv -> mp4", "make_rc": rc, "make_err": short(err)}
    if rc == 0:
        src_streams = streams(mkv)
        row["src_streams"] = [(s["i"], s["type"], s["codec"], s["disp"], s["tags"].get("filename")) for s in src_streams]
        pic = [s["i"] for s in src_streams if "attached_pic" in s["disp"]]
        dst = o("png_cover.mp4")
        rc2, err2 = ff(["-i", mkv, "-map", "0:v:0", "-map", "0:a", "-map", f"0:{pic[0]}" if pic else "0:t", "-c", "copy",
                        "-disposition:v:1", "attached_pic", dst])
        row["rc"], row["err"] = rc2, short(err2)
        if rc2 == 0:
            row["out_streams"] = [(s["i"], s["codec"], s["disp"]) for s in streams(dst)]
            row["covr_atom"] = find_atom_path(dst, b"covr")
    rows.append(row)
    dst = o("cover_without_disposition.mp4")
    rc, err = ff(["-i", MULTI, "-map", "0:v:0", "-map", "0:8", "-c", "copy", dst])
    row = {"case": "-map 0:8 without -disposition attached_pic (relies on input disposition)", "rc": rc, "err": short(err)}
    if rc == 0:
        row["out_streams"] = [(s["i"], s["codec"], s["disp"]) for s in streams(dst)]
        row["covr_atom"] = find_atom_path(dst, b"covr")
    rows.append(row)
    results["cover_art"] = rows


def attachments_dump():
    rows = []
    d = o("附件 dump")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    target = os.path.join(d, "字体 testfont.ttf")
    rc, err = ff(["-dump_attachment:t:0", target, "-i", MULTI, "-f", "null", "-"])
    rows.append({"case": "-dump_attachment:t:0 <absolute unicode path> -i in.mkv -f null -", "rc": rc, "err": short(err),
                 "exists": os.path.isfile(target),
                 "identical": os.path.isfile(target) and md5(target) == md5(os.path.join(SRC, "testfont.ttf"))})
    info = [(s["i"], s["type"], s["codec"], s["tags"].get("filename"), s["tags"].get("mimetype"), s["disp"]) for s in streams(MULTI)
            if s["type"] in ("attachment",) or "attached_pic" in s["disp"]]
    rows.append({"case": "how ffprobe lists attachments in multi.mkv", "streams": info})
    results["attachments_dump"] = rows


def bitmap_subs():
    rows = []
    src = os.path.join(MEDIA, "dvdsub.mkv")
    for label, dst, args in [
        ("dvdsub -> .mks (-f matroska)", o("dvdsub_sidecar.mks"), ["-map", "0:s:0", "-c:s", "copy", "-f", "matroska"]),
        ("dvdsub -> .sub.mkv", o("dvdsub_sidecar.sub.mkv"), ["-map", "0:s:0", "-c:s", "copy"]),
    ]:
        rc, err = ff(["-i", src] + args + [dst])
        row = {"case": label, "rc": rc, "err": short(err)}
        if rc == 0:
            row["streams"] = streams(dst)
        rows.append(row)
    renders = {}
    for label, path in [("mkv", src), ("mp4", os.path.join(HERE, "compat_out", "dvdsub_in_mp4_with_video.mp4"))]:
        png = o(f"dvdsub_render_{label}.png")
        rc, err = ff(["-i", path, "-filter_complex", "[0:v][0:s]overlay", "-ss", "1", "-frames:v", "1", "-update", "1", png])
        renders[label] = {"rc": rc, "err": short(err), "md5": md5(png) if rc == 0 and os.path.isfile(png) else None}
    rows.append({"case": "dvdsub rendered frame mkv vs mp4 (palette/position survive?)", "renders": renders,
                 "identical": renders["mkv"]["md5"] is not None and renders["mkv"]["md5"] == renders["mp4"]["md5"]})
    src = os.path.join(MEDIA, "pgs.mkv")
    dst = o("pgs_track.sup")
    rc, err = ff(["-i", src, "-map", "0:s:0", "-c:s", "copy", dst])
    row = {"case": "pgs -> .sup via -map 0:s:0 (no -f)", "rc": rc, "err": short(err)}
    if rc == 0:
        with open(dst, "rb") as fh:
            row["magic"] = fh.read(2).decode("latin-1")
        row["probe"] = [(s["codec"], s["tags"]) for s in streams(dst)]
    rows.append(row)
    results["bitmap_subs"] = rows


def language_disposition():
    rows = []
    mkv = os.path.join(EXTRA, "lang_disp.mkv")
    v = os.path.join(MEDIA, "already_compatible.mkv")
    srt = o("tiny.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,500 --> 00:00:02,000\nhello\n")
    rc, err = ff(["-i", v, "-i", v, "-i", v, "-i", srt, "-i", srt, "-i", srt,
                  "-map", "0:v", "-map", "0:a", "-map", "1:a", "-map", "2:a", "-map", "3", "-map", "4", "-map", "5",
                  "-c", "copy", "-c:s", "srt",
                  "-metadata:s:a:0", "language=zh-CN", "-metadata:s:a:1", "language=zho", "-metadata:s:a:2", "language=yue",
                  "-metadata:s:s:0", "language=pt-BR", "-metadata:s:s:1", "language=chi", "-metadata:s:s:2", "language=qaa",
                  "-disposition:a:0", "default", "-disposition:a:1", "comment", "-disposition:a:2", "visual_impaired+descriptions",
                  "-disposition:s:0", "hearing_impaired", "-disposition:s:1", "forced+default", "-disposition:s:2", "0",
                  mkv])
    row = {"case": "build lang_disp.mkv", "rc": rc, "err": short(err)}
    if rc == 0:
        row["src"] = [(s["i"], s["type"], s["tags"].get("language"), s["disp"]) for s in streams(mkv)]
        dst = o("lang_disp.mp4")
        rc2, err2 = ff(["-i", mkv, "-map", "0", "-c", "copy", "-c:s", "mov_text", dst])
        row["convert_rc"], row["convert_err"] = rc2, short(err2)
        if rc2 == 0:
            row["out"] = [(s["i"], s["type"], s["tags"].get("language"), s["disp"]) for s in streams(dst)]
            row["kind_atoms"] = find_atom_path(dst, b"kind")
    rows.append(row)
    results["language_disposition"] = rows


def extra_codecs():
    rows = []
    lavfi_v = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=2"]
    lavfi_a = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2"]
    vids = {
        "h264_hi10": ["-c:v", "libx264", "-pix_fmt", "yuv420p10le", "-preset", "veryfast"],
        "h264_444": ["-c:v", "libx264", "-pix_fmt", "yuv444p", "-preset", "veryfast"],
        "mpeg4_xvid": ["-c:v", "mpeg4", "-vtag", "XVID"],
        "msmpeg4v3": ["-c:v", "msmpeg4v3"],
        "wmv2": ["-c:v", "wmv2"],
        "mjpeg": ["-c:v", "mjpeg", "-pix_fmt", "yuvj420p"],
        "prores": ["-c:v", "prores_ks"],
        "ffv1": ["-c:v", "ffv1"],
        "h263p": ["-c:v", "h263p"],
    }
    auds = {
        "mp3": ["-c:a", "libmp3lame"],
        "pcm_s16le": ["-c:a", "pcm_s16le"],
        "pcm_f32le": ["-c:a", "pcm_f32le"],
        "wavpack": ["-c:a", "wavpack"],
        "tta": ["-c:a", "tta"],
        "aac_he": ["-c:a", "aac", "-profile:a", "aac_he"],
        "ac3_51": ["-c:a", "ac3", "-ac", "6"],
        "dts_51": ["-c:a", "dca", "-strict", "-2", "-ac", "6"],
        "wmav2": ["-c:a", "wmav2"],
        "speex": ["-c:a", "libspeex", "-ar", "16000"],
    }
    jobs = [(k, lavfi_v, a) for k, a in vids.items()] + [(k, lavfi_a, a) for k, a in auds.items()]
    for name, inp, cargs in jobs:
        mkv = os.path.join(EXTRA, f"{name}.mkv")
        rc, err = ff(inp + cargs + [mkv])
        row = {"codec": name, "make_rc": rc, "make_err": short(err)}
        if rc == 0:
            s0 = streams(mkv)[0]
            row["probe_codec"] = s0["codec"]
            for mode, margs in [("plain", []), ("unofficial", ["-strict", "unofficial"]), ("experimental", ["-strict", "experimental"])]:
                dst = o(f"x_{name}_{mode}.mp4")
                rc2, err2 = ff(["-i", mkv, "-map", "0", "-c", "copy"] + margs + [dst])
                if rc2 == 0:
                    row["works_with"] = mode
                    drc, derr = ff(["-i", dst, "-map", "0", "-f", "null", "-"])
                    row["decode_ok"] = drc == 0 and not derr
                    row["decode_msg"] = short(derr) or "clean"
                    s = streams(dst)[0]
                    row["out_codec"], row["out_tag"] = s["codec"], s["tag"]
                    break
                row.setdefault("errors", {})[mode] = short(err2)
            row.setdefault("works_with", None)
        rows.append(row)
        print("codec", name, row.get("works_with"), row.get("decode_ok"), row.get("make_err", "")[:80])
    results["extra_codecs"] = rows


def harness_fixes():
    rows = []
    path = os.path.join(HERE, "compat_out", "中文 空格 [测试] (1).mp4")
    rc, err = ff(["-i", path, "-map", "0:v", "-map", "0:a", "-f", "null", "-"])
    rows.append({"case": "unicode filename mp4 decode (v+a only)", "rc": rc, "err": short(err) or "clean"})
    r = subprocess.run(["ffprobe", "-v", "error", "-show_frames", "-select_streams", "s", "-of", "json", path],
                       capture_output=True, encoding="utf-8", errors="replace")
    n = len(json.loads(r.stdout or "{}").get("frames", []))
    rows.append({"case": "unicode filename mp4 subtitle events", "events": n, "err": short(r.stderr)})
    for name in ["multi_full_no_use_metadata_tags.mp4"]:
        path = os.path.join(HERE, "compat_out", name)
        rows.append({"case": f"full stream list of {name}", "streams": [(s["i"], s["type"], s["codec"], s["tag"], s["disp"],
                                                                          s["tags"].get("handler_name")) for s in streams(path)]})
    results["harness_fixes"] = rows


def faststart():
    rows = []
    for label, extra in [("no faststart", []), ("+faststart", ["-movflags", "+faststart"])]:
        dst = o(f"fs_{len(rows)}.mp4")
        rc, err = ff(["-i", MULTI, "-map", "0:v:0", "-map", "0:a:0", "-c", "copy"] + extra + [dst])
        top = []
        with open(dst, "rb") as fh:
            data = fh.read()
        pos = 0
        while pos + 8 <= len(data):
            size = int.from_bytes(data[pos:pos + 4], "big")
            typ = data[pos + 4:pos + 8].decode("latin-1")
            if size == 1:
                size = int.from_bytes(data[pos + 8:pos + 16], "big")
            top.append(typ)
            if size < 8:
                break
            pos += size
        rows.append({"variant": label, "rc": rc, "top_atoms": top})
    results["faststart"] = rows


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(EXTRA, exist_ok=True)
    for fn in [stream_titles, global_tags, chapters, cover_art, attachments_dump, bitmap_subs, language_disposition,
               harness_fixes, faststart, extra_codecs]:
        try:
            fn()
        except Exception as e:
            results[fn.__name__ + "_exception"] = repr(e)
            print("EXC", fn.__name__, repr(e))
    with open(RESULTS, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    print("written", RESULTS)


if __name__ == "__main__":
    main()
