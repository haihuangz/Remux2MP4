import glob
import hashlib
import json
import os
import struct
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

VIDEO_COPY = {"h264", "hevc", "av1", "vp9", "mpeg1video", "mpeg2video", "mpeg4", "mjpeg", "ffv1"}
AUDIO_COPY = {"aac", "mp3", "mp2", "ac3", "eac3", "dts", "flac", "alac", "opus", "vorbis", "truehd"}
COMPANION = {"dts", "vorbis", "truehd"}
TEXT_SUBS = {"subrip": ".srt", "ass": ".ass", "ssa": ".ssa", "webvtt": ".vtt"}
LANG_EQ = {"zho": "chi", "fra": "fre", "deu": "ger", "zh": "chi", "en": "eng", "ja": "jpn", "fr": "fre",
           "pt": "por", "yue": "yue"}
TS_NORM = {"h264": ("filter_units=remove_types=7|8|9", "h264_mp4toannexb,filter_units=remove_types=7|8|9"),
           "hevc": ("filter_units=remove_types=32|33|34|35", "hevc_mp4toannexb,filter_units=remove_types=32|33|34|35"),
           "aac": ("aac_adtstoasc", None), "av1": ("filter_units=remove_types=2|15", "filter_units=remove_types=2|15")}
FLV_NORM = {"av1": TS_NORM["av1"]}
STD_TAGS = {"title", "artist", "comment", "date", "album", "genre", "copyright", "description"}


def run(args, timeout=600):
    r = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def probe(path):
    rc, out, err = run(["ffprobe", "-v", "error", "-show_streams", "-show_chapters", "-show_format", "-of", "json", path])
    if rc != 0:
        return None
    return json.loads(out)


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def packet_hashes(path, idx, bsf=None, extradata=True):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-map", f"0:{idx}", "-c", "copy"]
    if bsf:
        cmd += ["-bsf:0", bsf]
    rc, out, err = run(cmd + ["-f", "framemd5", "-"])
    res = [l.split("#extradata 0,", 1)[1].strip() for l in out.splitlines() if l.startswith("#extradata")] if extradata else []
    res += [l.split(",")[5].strip() for l in out.splitlines() if l and not l.startswith("#")]
    return res


def start_of(s):
    try:
        return float(s.get("start_time"))
    except (TypeError, ValueError):
        return None


def frame_dur(s):
    try:
        n, d = s.get("avg_frame_rate", "0/0").split("/")
        return float(d) / float(n) if float(n) > 0 and float(d) > 0 else 1 / 30
    except ValueError:
        return 1 / 30


def norm_lang(l):
    if not l:
        return "und"
    l = l.lower()
    base = l.split("-")[0]
    return LANG_EQ.get(l, LANG_EQ.get(base, base))


def boxes(path, start=0, end=None, hdr=8):
    res = []
    size_total = os.path.getsize(path)
    end = size_total if end is None else end
    with open(path, "rb") as f:
        pos = start
        while pos + 8 <= end:
            f.seek(pos)
            h = f.read(16)
            size, typ = struct.unpack(">I4s", h[:8])
            hs = 8
            if size == 1:
                size = struct.unpack(">Q", h[8:16])[0]
                hs = 16
            elif size == 0:
                size = end - pos
            res.append((typ.decode("latin1"), pos, size, hs))
            if size < 8:
                break
            pos += size
    return res


def layout(path):
    top = boxes(path)
    names = [b[0] for b in top]
    info = {"top": names, "moof": "moof" in names, "mvex": False, "moov_first": False}
    if "moov" in names and "mdat" in names:
        info["moov_first"] = names.index("moov") < names.index("mdat")
    for t, pos, size, hs in top:
        if t == "moov":
            info["mvex"] = any(c[0] == "mvex" for c in boxes(path, pos + hs, pos + size))
    return info


def hdr_side(path):
    rc, out, err = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1",
                        "-show_frames", "-show_entries", "frame=side_data_list", "-of", "json", path])
    try:
        frames = json.loads(out).get("frames", [])
    except Exception:
        return {}
    res = {}
    for sd in (frames[0].get("side_data_list", []) if frames else []):
        t = sd.get("side_data_type", "")
        if "Mastering" in t or "light level" in t.lower():
            res[t] = {k: v for k, v in sd.items() if k != "side_data_type"}
    return res


def title_of(s):
    t = s.get("tags", {})
    return t.get("title") or t.get("TITLE") or ""


def out_title(s):
    t = s.get("tags", {})
    return {t.get("title", ""), t.get("handler_name", "")}


def is_cover(s):
    return s.get("disposition", {}).get("attached_pic") == 1 or (
        s.get("codec_type") == "video" and s.get("codec_name") in ("mjpeg", "png") and "filename" in s.get("tags", {}))


def check(src, out_path, outdir, out_stem, src_info=None, truncated=False, kind="mkv", deep=True):
    issues, notes = [], []
    si = src_info or probe(src)
    if not os.path.exists(out_path):
        return ["output missing: " + out_path], notes
    oi = probe(out_path)
    if oi is None:
        return ["output unreadable by ffprobe"], notes
    lay = layout(out_path)
    if lay["moof"] or lay["mvex"]:
        issues.append(f"output fragmented: top={lay['top']} mvex={lay['mvex']}")
    if not lay["moov_first"]:
        issues.append(f"moov not before mdat: top={lay['top']}")
    o_streams = [s for s in oi["streams"] if not s.get("disposition", {}).get("attached_pic")]
    o_cov = [s for s in oi["streams"] if s.get("disposition", {}).get("attached_pic")]
    oi_pos = 0
    pairs = []
    sidecars = sorted(set(glob.glob(glob.escape(os.path.join(outdir, out_stem)) + ".*")) - {out_path})
    sidecar_names = [os.path.basename(p) for p in sidecars]
    for s in si["streams"]:
        ct, cn, idx = s.get("codec_type"), s.get("codec_name"), s["index"]
        stags = s.get("tags", {})
        if ct == "attachment":
            continue
        if ct == "data":
            continue
        if is_cover(s):
            if not o_cov:
                issues.append(f"src#{idx} cover ({stags.get('filename')}) not embedded as attached_pic")
            continue
        if ct == "subtitle" and cn in ("hdmv_pgs_subtitle",):
            sup = [n for n in sidecar_names if n.startswith(f"{out_stem}.{idx}.") and n.endswith(".sup")]
            if not sup:
                issues.append(f"src#{idx} PGS: no .sup sidecar among {sidecar_names}")
            else:
                pi = probe(os.path.join(outdir, sup[0]))
                if not pi or pi["streams"][0]["codec_name"] != "hdmv_pgs_subtitle":
                    issues.append(f"src#{idx} sidecar {sup[0]} not valid PGS")
                elif deep:
                    ref = os.path.join(outdir, "_ref_check.sup")
                    run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", f"0:{idx}", "-c", "copy", ref])
                    same = md5_file(ref) == md5_file(os.path.join(outdir, sup[0]))
                    os.remove(ref)
                    if not same:
                        issues.append(f"src#{idx} PGS sidecar bytes differ")
            continue
        while oi_pos < len(o_streams) and o_streams[oi_pos]["codec_type"] != ct:
            issues.append(f"unexpected out#{o_streams[oi_pos]['index']} {o_streams[oi_pos]['codec_type']}/{o_streams[oi_pos]['codec_name']} before src#{idx}")
            oi_pos += 1
        if oi_pos >= len(o_streams):
            issues.append(f"src#{idx} {ct}/{cn} missing in output")
            continue
        o = o_streams[oi_pos]
        oi_pos += 1
        pairs.append((s, o))
        if norm_lang(stags.get("language")) != norm_lang(o.get("tags", {}).get("language")):
            issues.append(f"src#{idx} lang {stags.get('language')} -> out {o.get('tags', {}).get('language')}")
        st = title_of(s)
        if st and st not in out_title(o):
            issues.append(f"src#{idx} title {st!r} -> out {out_title(o)}")
        sd, od = s.get("disposition", {}), o.get("disposition", {})
        if sd.get("forced") != od.get("forced"):
            issues.append(f"src#{idx} forced {sd.get('forced')} -> {od.get('forced')}")
        if sd.get("default") != od.get("default"):
            first_of_type = not any(x["codec_type"] == ct and not is_cover(x) for x in si["streams"][:si["streams"].index(s)])
            if not (first_of_type and od.get("default") == 1 and not any(
                    x.get("disposition", {}).get("default") for x in si["streams"] if x["codec_type"] == ct)):
                issues.append(f"src#{idx} default {sd.get('default')} -> {od.get('default')}")
        copy = (ct == "video" and cn in VIDEO_COPY) or (ct == "audio" and (cn in AUDIO_COPY or cn.startswith("pcm_"))) \
            or (ct == "subtitle" and cn in ("dvd_subtitle", "mov_text"))
        if copy:
            if o["codec_name"] != cn and not (cn == "mp2" and o["codec_name"] == "mp3"):
                issues.append(f"src#{idx} {cn} should be copied but out is {o['codec_name']}")
            elif deep and cn in {"ts": TS_NORM, "flv": FLV_NORM}.get(kind, {}):
                fs, fo = {"ts": TS_NORM, "flv": FLV_NORM}[kind][cn]
                a = packet_hashes(src, idx, fs, extradata=False)
                b = packet_hashes(out_path, o["index"], fo, extradata=False)
                if a != b:
                    diff = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
                    msg = f"src#{idx} {cn} normalised packets differ: src {len(a)} out {len(b)} mismatched idx {diff[:5]}"
                    if not diff and len(b) < len(a) and truncated:
                        notes.append(msg + " (tail only)")
                    else:
                        issues.append(msg)
                else:
                    notes.append(f"src#{idx} {cn} identical after normalising ({fs} / {fo})")
            elif deep:
                a, b = packet_hashes(src, idx), packet_hashes(out_path, o["index"])
                if a != b and a[1:] == b[1:] and cn in ("hevc", "mov_text"):
                    notes.append(f"src#{idx} {cn} packets identical, only codec config record differs")
                elif a != b and cn == "mov_text" and a[1:] == b[1:len(a)]:
                    notes.append(f"src#{idx} mov_text identical plus {len(b) - len(a)} trailing empty sample(s)")
                elif a != b:
                    diff = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
                    msg = f"src#{idx} {cn} packets differ: src {len(a)} out {len(b)} mismatched idx {diff[:5]}"
                    if not diff and len(b) < len(a) and (len(a) - len(b) <= 2 or truncated):
                        notes.append(msg + " (tail only)")
                    else:
                        issues.append(msg)
            if cn == "hevc" and kind in ("mkv", "ts", "flv") and o.get("codec_tag_string") != "hvc1":
                issues.append(f"src#{idx} hevc tag {o.get('codec_tag_string')} not hvc1")
        else:
            notes.append(f"src#{idx} {ct}/{cn} -> {o['codec_name']} (converted)")
            if ct == "subtitle" and cn in TEXT_SUBS:
                ext = TEXT_SUBS[cn]
                sc = [n for n in sidecar_names if n.startswith(f"{out_stem}.{idx}.") and n.endswith(ext)]
                if not sc:
                    issues.append(f"src#{idx} {cn}: no {ext} sidecar")
                else:
                    with open(os.path.join(outdir, sc[0]), "rb") as fh:
                        data = fh.read()
                    rc, orig, _ = run(["ffmpeg", "-v", "error", "-i", src, "-map", f"0:{idx}", "-c", "copy", "-f", cn if cn != "subrip" else "srt", "-"])
                    if probe(os.path.join(outdir, sc[0])) is None:
                        issues.append(f"sidecar {sc[0]} unreadable")
            elif ct in ("video", "audio"):
                ext = ".mkv" if ct == "video" else ".mka"
                sc = [n for n in sidecar_names if n.startswith(f"{out_stem}.{idx}") and n.endswith(ext)]
                if not sc:
                    issues.append(f"src#{idx} {cn} converted but original not saved as {ext} sidecar ({sidecar_names})")
                elif deep and packet_hashes(src, idx) != packet_hashes(os.path.join(outdir, sc[0]), 0):
                    issues.append(f"src#{idx} sidecar {sc[0]} packets differ from source")
        if ct == "audio" and kind in ("mkv", "ts", "flv") and (cn in COMPANION or cn.startswith("pcm_")):
            if oi_pos < len(o_streams) and "(兼容)" in " ".join(out_title(o_streams[oi_pos])):
                c = o_streams[oi_pos]
                oi_pos += 1
                if c.get("disposition", {}).get("default"):
                    issues.append(f"companion for src#{idx} is default")
            else:
                notes.append(f"no companion after src#{idx} {cn}")
    for o in o_streams[oi_pos:]:
        notes.append(f"extra out#{o['index']} {o['codec_type']}/{o['codec_name']} {out_title(o)}")
    sch = [c.get("tags", {}).get("title") for c in si.get("chapters", [])]
    och = [c.get("tags", {}).get("title") for c in oi.get("chapters", [])]
    if sch != och:
        issues.append(f"chapters {sch} -> {och}")
    stg = {k.lower(): v for k, v in si.get("format", {}).get("tags", {}).items()}
    otg = {k.lower(): v for k, v in oi.get("format", {}).get("tags", {}).items()}
    meta_txt = os.path.join(outdir, out_stem + ".metadata.txt")
    meta = open(meta_txt, encoding="utf-8").read() if os.path.exists(meta_txt) else ""
    for k, v in stg.items():
        if k in ("encoder", "major_brand", "minor_version", "compatible_brands", "creation_time"):
            continue
        if k in STD_TAGS:
            if otg.get(k) != v:
                issues.append(f"global tag {k}={v!r} -> {otg.get(k)!r}")
        elif otg.get(k) != v and f"={v}" not in meta:
            issues.append(f"custom tag {k}={v!r} neither in MP4 nor in metadata.txt")
    fonts = [s for s in si["streams"] if s.get("codec_type") == "attachment"]
    for s in fonts:
        fn = s.get("tags", {}).get("filename", "")
        cands = glob.glob(os.path.join(outdir, glob.escape(out_stem) + "_*", fn))
        if not cands:
            issues.append(f"attachment {fn} not extracted")
    if si["streams"] and si["streams"][0].get("codec_name") == "hevc":
        a, b = hdr_side(src), hdr_side(out_path)
        if a != b:
            issues.append(f"HDR side data differs: src {a} out {b}")
        elif a:
            notes.append("HDR side data equal: " + ", ".join(a))
    for p in sidecars:
        if p.endswith((".srt", ".ass", ".vtt", ".ssa", ".sup", ".mks", ".mka", ".mkv", ".mov")) and probe(p) is None:
            issues.append(f"sidecar unreadable: {os.path.basename(p)}")
    rep = os.path.join(outdir, out_stem + ".转换报告.txt")
    if not os.path.exists(rep):
        issues.append("report missing")
    else:
        raw = open(rep, "rb").read()
        if not raw.startswith(b"\xef\xbb\xbf"):
            issues.append("report lacks UTF-8 BOM")
        raw.decode("utf-8")
    partial = glob.glob(os.path.join(outdir, "*.partial*"))
    if partial:
        issues.append(f"leftover partial: {partial}")
    if kind in ("ts", "flv"):
        av = [(s, o) for s, o in pairs if s.get("codec_type") in ("video", "audio")]
        vid = next(((s, o) for s, o in av if s.get("codec_type") == "video"), None)
        if vid and None not in (start_of(vid[0]), start_of(vid[1])):
            tol = frame_dur(vid[0]) + 0.002
            for s, o in av:
                if None in (start_of(s), start_of(o)):
                    continue
                shift = (start_of(o) - start_of(vid[1])) - (start_of(s) - start_of(vid[0]))
                if abs(shift) > tol:
                    issues.append(f"src#{s['index']} start offset vs video changed by {shift:+.3f}s")
            notes.append("sync: start offsets " + ", ".join(
                f"#{s['index']} {start_of(s) - start_of(vid[0]):+.3f}->{start_of(o) - start_of(vid[1]):+.3f}" for s, o in av
                if None not in (start_of(s), start_of(o))))
    sdur = float(si["format"].get("duration") or 0)
    odur = float(oi["format"].get("duration") or 0)
    ts_jump = kind == "ts" and "discont" in os.path.basename(src)
    if ts_jump:
        rep_txt = open(rep, encoding="utf-8-sig").read() if os.path.exists(rep) else ""
        if "跳变" not in rep_txt:
            issues.append("timestamp jump not explained in report")
    elif not truncated and sdur and abs(sdur - odur) > 1.0:
        issues.append(f"duration {sdur} -> {odur}")
    notes.append(f"dur {sdur:.2f}->{odur:.2f}; sidecars={sidecar_names}")
    return issues, notes
