import ctypes
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
OUT = os.path.join(HERE, "_gui")

user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32")
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND


def make_hdrop(files):
    payload = ("\0".join(files) + "\0\0").encode("utf-16-le")
    header = (20).to_bytes(4, "little") + bytes(8) + bytes(4) + (1).to_bytes(4, "little")
    data = header + payload
    h = kernel32.GlobalAlloc(0x0042, len(data))
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    return h


def window_shot(root, name):
    from PIL import ImageGrab
    root.update()
    hwnd = user32.GetParent(root.winfo_id())
    rect = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
    path = os.path.join(OUT, name)
    img.save(path)
    print("screenshot", path, img.size)


def in_process_test():
    import tkinter as tk
    import gui
    gui.set_dpi_awareness()
    root = tk.Tk()
    root.geometry("1000x760+40+40")
    app = gui.App(root, [])
    print("drop target installed:", app.drop_ok)
    app.out_mode.set("custom")
    app.out_dir.set(os.path.join(OUT, "out"))
    app._mode_changed()
    root.attributes("-topmost", True)
    root.update()
    window_shot(root, "1_empty.png")
    print("export-audio checkbox default:", app.export_audio.get())
    app.export_audio.set(True)
    files = [os.path.join(HERE, "media", "obs", "obs_h264_6aac.mkv"),
             os.path.join(HERE, "media", "fmp4"),
             os.path.join(HERE, "media", "multi.mkv"),
             os.path.join(HERE, "media", "flv_ts", "ts_h264_3aac_lang.ts"),
             os.path.join(HERE, "media", "flv_ts", "flv_h264_aac.flv"),
             os.path.join(HERE, "media", "export", "plain_3aac.mp4")]
    hwnd = user32.GetParent(root.winfo_id())
    user32.PostMessageW(hwnd, 0x0233, make_hdrop(files), 0)
    t0 = time.time()
    while time.time() - t0 < 3:
        root.update()
        time.sleep(0.05)
    print("items after drop:", len(app.items))
    for it in app.items.values():
        print("  ", it["kind"], it["state"], os.path.basename(it["path"]))
    window_shot(root, "2_dropped.png")
    app.start()
    shot_mid = False
    while app.worker is not None or not app.q.empty():
        root.update()
        time.sleep(0.05)
        if not shot_mid and time.time() - t0 > 6:
            window_shot(root, "3_running.png")
            shot_mid = True
        if time.time() - t0 > 600:
            print("timeout")
            break
    for _ in range(20):
        root.update()
        time.sleep(0.05)
    window_shot(root, "4_done.png")
    states = {}
    for it in app.items.values():
        states[it["state"]] = states.get(it["state"], 0) + 1
    print("final states:", states)
    out = os.path.join(OUT, "out")
    folders = sorted(n for n in os.listdir(out) if n.endswith("_音轨"))
    print("audio folders:", folders)
    for want in ("obs_h264_6aac_音轨", "ts_h264_3aac_lang_音轨", "flv_h264_aac_音轨", "plain_3aac_音轨"):
        print("  ", want, "OK" if want in folders and os.listdir(os.path.join(out, want)) else "MISSING")
    print("plain MP4 not converted:", not os.path.exists(os.path.join(out, "plain_3aac.mp4")))
    root.destroy()


def argv_test():
    work = os.path.join(OUT, "argv")
    os.makedirs(work, exist_ok=True)
    src = os.path.join(work, "拖到图标上 测试.mkv")
    shutil.copy(os.path.join(HERE, "media", "obs", "obs_av1_opus.mkv"), src)
    log = os.path.join(OUT, "argv_log.txt")
    env = dict(os.environ, MKV2MP4_GUI_TEST_LOG=log)
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "gui.py"), src], env=env)
    t0 = time.time()
    finished = False
    while time.time() - t0 < 180:
        if os.path.exists(log):
            with open(log, encoding="utf-8") as f:
                if "finished:" in f.read():
                    finished = True
                    break
        time.sleep(0.5)
    with open(log, encoding="utf-8") as f:
        print("argv log:", f.read().strip())
    print("argv outputs:", sorted(os.listdir(work)))
    p.terminate()
    p.wait(timeout=10)
    print("argv auto-start finished:", finished)


if __name__ == "__main__":
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "out"))
    import tool_ffmpeg
    print(tool_ffmpeg.describe())
    in_process_test()
    argv_test()
