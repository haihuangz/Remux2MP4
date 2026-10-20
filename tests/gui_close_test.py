import os
import shutil
import sys
import time
import tkinter as tk

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import gui
import mkv2mp4_core as core

work = os.path.join(HERE, "out", "_gui_close")
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
src = os.path.join(work, "obs.mkv")
shutil.copyfile(os.path.join(HERE, "media", "obs", "obs_h264_6aac.mkv"), src)

import tool_ffmpeg
print(tool_ffmpeg.describe())
gui.messagebox.askyesno = lambda *a, **k: True
root = tk.Tk()
app = gui.App(root, [src])
t0 = time.time()
events = {}


def tick():
    if "started" not in events and app.worker is not None:
        events["started"] = time.time() - t0
        events["scan_rows"] = len(app.items)
    if "started" in events and "close" not in events and time.time() - t0 > events["started"] + 0.8:
        events["close"] = time.time() - t0
        events["files_at_close"] = sorted(os.listdir(work))
        app.on_close()
    root.after(50, tick)


root.after(50, tick)
root.mainloop()
events["destroyed_after"] = round(time.time() - t0, 2)
events["files_after"] = sorted(os.listdir(work))
print(events)
ok = events.get("started") is not None and events["files_after"] == ["obs.mkv"]
print("PASS" if ok else "FAIL")
