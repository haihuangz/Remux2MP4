import os
import shutil
import subprocess
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import mkv2mp4_core as core

WORK = os.path.join(HERE, "_cancel")
EXE = os.path.join(os.environ.get("MKV2MP4_DIST_DIR") or os.path.join(ROOT, "dist"), "视频转MP4", "视频转MP4.exe")


def cancel_test():
    big = os.path.join(WORK, "loop.mkv")
    subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", "40", "-i",
                    os.path.join(HERE, "media", "obs", "obs_h264_6aac.mkv"), "-map", "0", "-c", "copy", big], check=True)
    out = os.path.join(WORK, "out")
    os.makedirs(out)
    ev = threading.Event()
    conv = core.Converter(core.Options(out_dir=out), cancel_event=ev)
    threading.Timer(0.8, conv.cancel).start()
    r = conv.convert(big)
    print("cancel status:", r.status, r.message, "| leftovers:", os.listdir(out))

    space = core.free_space
    core.free_space = lambda folder: 10 * 1024 ** 2
    r = core.Converter(core.Options(out_dir=out)).convert(big)
    core.free_space = space
    print("low-space status:", r.status, r.message, "| leftovers:", os.listdir(out))


def exe_test():
    exe = EXE
    src_dir = os.path.join(WORK, "exe")
    os.makedirs(src_dir)
    src = os.path.join(src_dir, "OBS 录像 2026-10-20.mkv")
    shutil.copy(os.path.join(HERE, "media", "obs", "obs_hevc10_hdr_pq.mkv"), src)
    frag = os.path.join(src_dir, "崩溃的混合录像.mp4")
    shutil.copy(os.path.join(HERE, "media", "obs", "obs_hybrid_unfinalised.mp4"), frag)
    log = os.path.join(WORK, "exe_log.txt")
    env = dict(os.environ, MKV2MP4_GUI_TEST_LOG=log, PATH=r"C:\Windows\System32;C:\Windows")
    p = subprocess.Popen([exe, src, frag], env=env)
    t0 = time.time()
    while time.time() - t0 < 180:
        if os.path.exists(log) and "finished:" in open(log, encoding="utf-8").read():
            break
        time.sleep(0.5)
    print("exe log:", open(log, encoding="utf-8").read().strip() if os.path.exists(log) else None)
    print("exe outputs:", sorted(os.listdir(src_dir)))
    p.terminate()
    p.wait(timeout=10)


if __name__ == "__main__":
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    import tool_ffmpeg
    print(tool_ffmpeg.describe())
    cancel_test()
    if os.path.exists(EXE):
        exe_test()
    shutil.rmtree(os.path.join(WORK, "loop.mkv"), ignore_errors=True)
