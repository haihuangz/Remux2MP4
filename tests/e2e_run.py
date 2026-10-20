import glob
import json
import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import e2e_check as ck

MEDIA = os.path.join(HERE, "media")
OUT = os.path.join(HERE, "out")
EXE = os.path.join(os.environ.get("MKV2MP4_DIST_DIR") or os.path.join(ROOT, "dist"), "视频转MP4", "视频转MP4.exe")
TRUNC_HINT = ("末尾不完整", "已恢复到", "已转换到", "中断")
STREAM_EXTS = (".mkv", ".webm", ".ts", ".m2ts", ".mts", ".flv")


def sources():
    res = []
    for grp in ("", "obs", "fmp4", "extra", "gen", "flv_ts"):
        d = os.path.join(OUT, "_gen") if grp == "gen" else os.path.join(MEDIA, grp)
        for f in sorted(glob.glob(os.path.join(d, "*.*"))):
            if os.path.isfile(f) and os.path.splitext(f)[1].lower() in (".mkv", ".webm", ".mp4", ".mov", ".m4s", ".ts",
                                                                         ".m2ts", ".mts", ".flv"):
                res.append((grp or "root", f))
    return res


def make_gen():
    d = os.path.join(OUT, "_gen")
    os.makedirs(d, exist_ok=True)
    data = open(os.path.join(MEDIA, "multi.mkv"), "rb").read()
    p = os.path.join(d, "multi_trunc80.mkv")
    if not os.path.exists(p):
        open(p, "wb").write(data[: int(len(data) * 0.8)])
    data = open(os.path.join(MEDIA, "obs", "obs_hevc10_hdr_pq.mkv"), "rb").read()
    p = os.path.join(d, "obs_hevc_trunc35.mkv")
    if not os.path.exists(p):
        open(p, "wb").write(data[: int(len(data) * 0.35)])
    p = os.path.join(d, "header_only.mkv")
    if not os.path.exists(p):
        open(p, "wb").write(data[:3000])
    fix = os.path.join(OUT, "_gen2")
    for src, dst in (("complete_corrupt_middle.mkv", None), ("crashed_plain.mp4", None),
                     ("frag_midsample.mp4", "frag_midsample_trunc.mp4"),
                     ("obs_frag_midsample.mp4", "obs_frag_midsample_trunc.mp4")):
        p = os.path.join(d, dst or src)
        if os.path.exists(os.path.join(fix, src)) and not os.path.exists(p):
            shutil.copyfile(os.path.join(fix, src), p)


def find_output(outdir, src):
    stem = os.path.splitext(os.path.basename(src))[0]
    frag = not src.lower().endswith(STREAM_EXTS)
    for cand in ((stem + "_标准MP4", stem + "_标准MOV") if frag else (stem,)):
        for ext in (".mp4", ".mov"):
            p = os.path.join(outdir, cand + ext)
            if os.path.exists(p) and os.path.normcase(p) != os.path.normcase(src):
                return p, cand
    return None, None


def is_trunc(src):
    n = os.path.basename(src)
    return any(k in n for k in ("trunc", "unfinalised"))


def verify_one(src, outdir, md5_before, stdout, rc, mode):
    md5_after = ck.md5_file(src)
    rec = {"src": os.path.relpath(src, HERE), "mode": mode, "rc": rc, "stdout_tail": stdout.strip().splitlines()[-6:],
           "issues": [], "notes": []}
    if md5_before != md5_after:
        rec["issues"].append("SOURCE MODIFIED")
    out, stem = find_output(outdir, src)
    rec["output"] = out and os.path.basename(out)
    if out is None:
        rec["issues"].append("no output") if rc == 0 and "跳过" not in stdout else rec["notes"].append("no output (expected?)")
        junk = [n for n in os.listdir(outdir) if n.startswith(os.path.splitext(os.path.basename(src))[0]) and
                os.path.join(outdir, n) != src]
        if junk:
            rec["issues"].append(f"junk left without output: {junk}")
        return rec
    low = src.lower()
    kind = "mkv" if low.endswith((".mkv", ".webm")) else "ts" if low.endswith((".ts", ".m2ts", ".mts")) else (
        "flv" if low.endswith(".flv") else "fmp4")
    try:
        iss, notes = ck.check(src, out, outdir, stem, truncated=is_trunc(src), kind=kind)
    except Exception as e:
        iss, notes = [f"checker exception {e!r}"], []
    rec["issues"] += iss
    rec["notes"] += notes
    if is_trunc(src) and not any(k in stdout for k in TRUNC_HINT):
        rec["issues"].append("truncated source but no Chinese truncation warning in output")
    return rec


def run_cli(items):
    results = []
    for grp, src in items:
        outdir = os.path.join(OUT, "cli", grp)
        os.makedirs(outdir, exist_ok=True)
        before = ck.md5_file(src)
        t0 = time.time()
        r = subprocess.run([sys.executable, os.path.join(ROOT, "mkv2mp4.py"), src, "-o", outdir],
                           capture_output=True, encoding="utf-8", errors="replace", timeout=900)
        rec = verify_one(src, outdir, before, r.stdout + r.stderr, r.returncode, "cli")
        rec["secs"] = round(time.time() - t0, 1)
        print(("FAIL " if rec["issues"] else "ok   ") + rec["src"], rec["issues"][:4], flush=True)
        results.append(rec)
    return results


def run_exe(items):
    results = []
    by_grp = {}
    for grp, src in items:
        by_grp.setdefault(grp, []).append(src)
    for grp, srcs in by_grp.items():
        d = os.path.join(OUT, "exe", grp)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        copies = []
        for s in srcs:
            c = os.path.join(d, os.path.basename(s))
            shutil.copy2(s, c)
            copies.append((s, c, ck.md5_file(c)))
        log = os.path.join(OUT, f"exe_log_{grp}.txt")
        if os.path.exists(log):
            os.remove(log)
        env = dict(os.environ, MKV2MP4_GUI_TEST_LOG=log, PATH=r"C:\Windows\System32;C:\Windows")
        p = subprocess.Popen([EXE] + [c for _, c, _ in copies], env=env)
        t0 = time.time()
        txt = ""
        while time.time() - t0 < 900:
            if os.path.exists(log):
                txt = open(log, encoding="utf-8").read()
                if "finished:" in txt:
                    break
            time.sleep(1)
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        print(f"[exe {grp}] {time.time() - t0:.0f}s log: {txt.strip()[-300:]}", flush=True)
        for s, c, m in copies:
            rep = os.path.join(d, os.path.splitext(os.path.basename(c))[0])
            rtxt = ""
            for rp in glob.glob(glob.escape(rep) + "*.转换报告.txt"):
                rtxt += open(rp, encoding="utf-8-sig").read()
            rec = verify_one(c, d, m, rtxt + "\n" + txt, 0, "exe")
            print(("FAIL " if rec["issues"] else "ok   ") + rec["src"], rec["issues"][:4], flush=True)
            results.append(rec)
    return results


if __name__ == "__main__":
    mode = sys.argv[1]
    import tool_ffmpeg
    print(tool_ffmpeg.describe() if mode == "cli" else tool_ffmpeg.describe(os.path.join(os.path.dirname(EXE), "bin", "ffmpeg.exe")) + " (bundled; the exe log below names the one it located)", flush=True)
    make_gen()
    items = sources()
    if len(sys.argv) > 2:
        items = [i for i in items if any(k in i[1] for k in sys.argv[2:])]
    res = run_cli(items) if mode == "cli" else run_exe(items)
    with open(os.path.join(OUT, f"e2e_{mode}.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
