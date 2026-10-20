import json
import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import e2e_check as ck
import mkv2mp4_core as core

W = os.path.join(HERE, "out", "_large")


def cli(src, outdir, *flags):
    os.makedirs(outdir, exist_ok=True)
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "mkv2mp4.py"), src, "-o", outdir, *flags],
                       capture_output=True, encoding="utf-8", errors="replace")
    return round(time.time() - t0, 1), r.returncode, r.stdout.strip().splitlines()[-8:]


def main():
    shutil.rmtree(W, ignore_errors=True)
    os.makedirs(W)
    src = os.path.join(W, "OBS 长录像.mkv")
    loops = int(sys.argv[1]) if len(sys.argv) > 1 else 320
    t0 = time.time()
    subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", str(loops), "-i",
                    os.path.join(HERE, "media", "obs", "obs_h264_6aac.mkv"), "-map", "0", "-c", "copy", src], check=True)
    size = os.path.getsize(src)
    res = {"size_gb": round(size / 1024 ** 3, 2), "gen_s": round(time.time() - t0, 1)}
    info = ck.probe(src)
    res["duration_s"] = float(info["format"]["duration"])
    md5_before = ck.md5_file(src)
    for name, flags in (("nofs_1", ["--no-verify", "--no-faststart"]), ("fs_1", ["--no-verify"]),
                        ("nofs_2", ["--no-verify", "--no-faststart"]), ("fs_2", ["--no-verify"]),
                        ("fs_verify", [])):
        od = os.path.join(W, name)
        secs, rc, tail = cli(src, od, *flags)
        out = os.path.join(od, "OBS 长录像.mp4")
        lay = ck.layout(out) if os.path.exists(out) else None
        oi = ck.probe(out) if os.path.exists(out) else None
        res[name] = {"secs": secs, "rc": rc, "tail": tail, "top": lay and lay["top"],
                     "audio": oi and [s.get("tags", {}).get("handler_name") for s in oi["streams"] if s["codec_type"] == "audio"],
                     "dur": oi and oi["format"]["duration"]}
        if name == "fs_verify":
            iss, notes = ck.check(src, out, od, "OBS 长录像", src_info=info, deep=False)
            res[name]["check"] = [iss, notes]
            for idx in (0, 1, 6):
                a = ck.packet_hashes(src, idx)
                b = ck.packet_hashes(out, idx)
                res[name][f"hash_{idx}"] = (a == b, len(a), len(b))
        shutil.rmtree(od, ignore_errors=True)
        print(name, res[name], flush=True)
    samples = []
    od = os.path.join(W, "prog")
    os.makedirs(od)
    t0 = time.time()
    r = core.Converter(core.Options(out_dir=od, verify=False),
                       progress=lambda f, st: samples.append((round(time.time() - t0, 2), round(f, 4), st))).convert(src)
    res["progress"] = {"status": r.status, "n": len(samples), "first": samples[:3], "last": samples[-3:],
                       "monotonic": all(samples[i][1] <= samples[i + 1][1] for i in range(len(samples) - 1)),
                       "mid": [s for s in samples if 0.45 < s[1] < 0.55][:2], "total_s": round(time.time() - t0, 1)}
    print("progress", res["progress"], flush=True)
    res["source_unchanged"] = ck.md5_file(src) == md5_before
    shutil.rmtree(W, ignore_errors=True)
    res["deleted"] = not os.path.exists(W)
    with open(os.path.join(HERE, "out", "e2e_large.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()
