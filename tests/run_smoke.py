import hashlib
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mkv2mp4_core as core


def fingerprint(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    st = os.stat(p)
    return h.hexdigest(), st.st_size, st.st_mtime_ns


def main():
    import tool_ffmpeg
    print(tool_ffmpeg.describe())
    dirs = sys.argv[1:] or ["media", "media/obs", "media/fmp4", "media/extra", "media/flv_ts"]
    out_root = os.path.join(HERE, "_smoke")
    shutil.rmtree(out_root, ignore_errors=True)
    totals = {}
    for d in dirs:
        src_dir = os.path.join(HERE, d)
        out_dir = os.path.join(out_root, d.replace("/", "_"))
        os.makedirs(out_dir)
        conv = core.Converter(core.Options(out_dir=out_dir), log=lambda m: None)
        for f in core.collect_inputs([src_dir]):
            before = fingerprint(f)
            r = conv.convert(f)
            after = fingerprint(f)
            print(core.result_summary(r))
            if before != after:
                print("  !!! SOURCE CHANGED !!!")
                totals["SOURCE_CHANGED"] = totals.get("SOURCE_CHANGED", 0) + 1
            partials = [x for x in os.listdir(out_dir) if ".partial" in x]
            if partials:
                print("  !!! leftover partial files:", partials)
            totals[r.status] = totals.get(r.status, 0) + 1
    print("\nTOTALS:", totals)


if __name__ == "__main__":
    main()
