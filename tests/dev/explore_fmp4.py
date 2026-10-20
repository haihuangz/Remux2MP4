import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "compat_out", "fmp4_explore")


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-show_chapters", "-of", "json", p],
                       capture_output=True, encoding="utf-8", errors="replace")
    try:
        d = json.loads(r.stdout or "{}")
    except ValueError:
        d = {}
    return r.returncode, d, r.stderr.strip()[-300:]


def summary(d):
    rows = []
    for s in d.get("streams", []):
        t = s.get("tags", {})
        rows.append(f"#{s['index']} {s.get('codec_type')}/{s.get('codec_name')}/{s.get('codec_tag_string')} "
                    f"lang={t.get('language')} hdl={t.get('handler_name')} title={t.get('title')} "
                    f"def={s.get('disposition', {}).get('default')} dur={s.get('duration')}")
    f = d.get("format", {})
    rows.append(f"format dur={f.get('duration')} tags={f.get('tags')} chapters={len(d.get('chapters', []))}")
    return rows


def top_boxes(p):
    out = []
    size = os.path.getsize(p)
    with open(p, "rb") as f:
        pos = 0
        while pos + 8 <= size and len(out) < 12:
            f.seek(pos)
            h = f.read(16)
            n = int.from_bytes(h[:4], "big")
            typ = h[4:8].decode("latin1")
            if n == 1:
                n = int.from_bytes(h[8:16], "big")
            elif n == 0:
                n = size - pos
            out.append(typ)
            if n < 8:
                break
            pos += n
    return out


def remux(src, dst, extra=()):
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "warning", "-i", src, "-map", "0", "-c", "copy",
           "-map_metadata", "0", "-map_chapters", "0", "-movflags", "+faststart"] + list(extra) + [dst]
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stderr.strip()[-600:]


def decode_errors(p):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-map", "0:v?", "-map", "0:a?", "-f", "null", "-"],
                       capture_output=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stderr.strip()[-300:]


def main():
    os.makedirs(OUT, exist_ok=True)
    files = sys.argv[1:]
    for src in files:
        print("=" * 70)
        print(os.path.basename(src), "boxes:", top_boxes(src))
        rc, d, err = probe(src)
        print(" probe rc", rc, err)
        for r in summary(d):
            print("  ", r)
        ext = ".mp4"
        dst = os.path.join(OUT, os.path.splitext(os.path.basename(src))[0] + "_remux" + ext)
        rc, err = remux(src, dst)
        print(" remux rc", rc, err)
        if os.path.exists(dst):
            print(" out boxes:", top_boxes(dst))
            rc, d, err = probe(dst)
            for r in summary(d):
                print("  ", r)
            print(" decode", decode_errors(dst))


if __name__ == "__main__":
    main()
