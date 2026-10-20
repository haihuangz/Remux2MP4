import argparse
import os
import signal
import sys
import threading

import mkv2mp4_core as core


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        prog="mkv2mp4",
        description=f"{core.APP_NAME}：MKV/WebM/FLV/TS 转 MP4、分片 MP4 转普通 MP4，保留全部轨道，不改动源文件。")
    ap.add_argument("inputs", nargs="+", help="文件或文件夹")
    ap.add_argument("-o", "--outdir", help="输出文件夹（默认：和源文件同一个文件夹）")
    ap.add_argument("-r", "--recursive", action="store_true", help="文件夹里的子文件夹也一起处理")
    ap.add_argument("--no-companion", action="store_true", help="不为冷门音轨额外添加兼容音轨")
    ap.add_argument("--no-sidecars", action="store_true", help="不另存 MP4 装不下的字幕/字体/附件")
    ap.add_argument("--no-faststart", action="store_true", help="不把索引移到文件开头（大文件更快）")
    ap.add_argument("--no-verify", action="store_true", help="跳过逐包比对和试解码")
    ap.add_argument("--export-audio", action="store_true",
                    help="把每条音轨另存成单独的音频文件（放在“<名字>_音轨”文件夹；剪映等只认第一条音轨时用）。"
                         "已经是普通 MP4 的文件不转换，只另存音轨")
    a = ap.parse_args(argv)
    missing = core.missing_tools()
    if missing:
        print(core.missing_tools_message(missing), file=sys.stderr)
        return 3

    if a.outdir:
        a.outdir = os.path.abspath(a.outdir)
        os.makedirs(a.outdir, exist_ok=True)
    opts = core.Options(out_dir=a.outdir, companion=not a.no_companion, sidecars=not a.no_sidecars,
                        faststart=not a.no_faststart, verify=not a.no_verify, export_audio=a.export_audio)
    files = core.collect_inputs(a.inputs, a.recursive)
    if not files:
        print("没有找到可以处理的文件（支持 " + " ".join(sorted(core.ALL_EXTS)) + "）")
        return 2

    cancel = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    state = {"last": -1}

    tty = sys.stdout is not None and sys.stdout.isatty()

    def progress(frac, stage):
        pct = int(frac * 100)
        step = 1 if tty else 25
        if state["last"] < 0 or pct // step != state["last"] // step:
            state["last"] = pct
            if tty:
                print(f"\r  {stage} {pct:3d}%" + " " * 20, end="", flush=True)
            else:
                print(f"  {stage} {pct}%", flush=True)

    def log(msg):
        prefix = "\r" if tty else ""
        print(prefix + "  " + msg.replace("\n", "\n  ") + (" " * 20 if tty else ""), flush=True)

    conv = core.Converter(opts, log=log, progress=progress, cancel_event=cancel)
    results = []
    for i, f in enumerate(files, 1):
        print(f"\n({i}/{len(files)}) {f}")
        state["last"] = -1
        r = conv.convert(f)
        if tty:
            print("\r" + " " * 60 + "\r", end="")
        print(core.result_summary(r, tech=True))
        results.append(r)
        if r.status == "cancelled":
            break

    counts = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    names = {"ok": "成功", "warn": "完成有提示", "failed": "失败", "skipped": "跳过", "cancelled": "取消"}
    print("\n合计：" + "，".join(f"{names.get(k, k)} {v}" for k, v in counts.items()))
    return 1 if any(r.status in ("failed", "cancelled") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
