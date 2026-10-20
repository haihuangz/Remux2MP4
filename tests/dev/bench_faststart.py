import json
import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))
import mkv2mp4_core as core

WORK = os.path.join(HERE, "media", "_big")
SRC = os.path.join(HERE, "media", "obs", "obs_h264_6aac.mkv")
LOOPS = int(sys.argv[1]) if len(sys.argv) > 1 else 320


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    big = os.path.join(WORK, "obs_big.mkv")
    t = time.time()
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-stream_loop", str(LOOPS), "-i", SRC,
                    "-map", "0", "-c", "copy", big], check=True)
    size = os.path.getsize(big)
    print(f"generated {size / 1024 ** 3:.2f} GB in {time.time() - t:.0f}s")
    results = {"size_gb": round(size / 1024 ** 3, 2), "runs": []}
    plan = [("no_faststart", False, False), ("faststart", True, False),
            ("no_faststart", False, False), ("faststart", True, False), ("faststart+verify", True, True)]
    for label, fs, verify in plan:
        out = os.path.join(WORK, label)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        stages = {}
        t0 = time.time()

        def progress(frac, stage):
            stages.setdefault(stage, time.time() - t0)

        conv = core.Converter(core.Options(out_dir=out, faststart=fs, verify=verify), progress=progress)
        r = conv.convert(big)
        dt = time.time() - t0
        row = {"label": label, "seconds": round(dt, 1), "status": r.status,
               "stage_start_s": {k: round(v, 1) for k, v in stages.items()},
               "out_gb": round(os.path.getsize(r.output) / 1024 ** 3, 2) if r.output and os.path.exists(r.output) else None}
        print(json.dumps(row, ensure_ascii=False))
        if r.status not in ("ok", "warn"):
            print(core.result_summary(r))
        results["runs"].append(row)
        shutil.rmtree(out, ignore_errors=True)
    with open(os.path.join(HERE, "bench_faststart_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    shutil.rmtree(WORK, ignore_errors=True)
    print("cleaned up", WORK)


if __name__ == "__main__":
    main()
