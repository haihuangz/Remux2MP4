import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))
import mkv2mp4_core as core

od = os.path.join(HERE, "out", "_space")
shutil.rmtree(od, ignore_errors=True)
os.makedirs(od)
src = os.path.join(HERE, "media", "obs", "obs_h264_6aac.mkv")
size = os.path.getsize(src)
real = core.free_space
for label, free in (("tiny", 10 * 1024 ** 2), ("just_below", int(size * 1.03) + 200 * 1024 ** 2 - 1),
                    ("just_above", int(size * 1.03) + 200 * 1024 ** 2 + 1)):
    core.free_space = lambda folder, f=free: f
    r = core.Converter(core.Options(out_dir=od, verify=False)).convert(src)
    print(label, r.status, r.message, sorted(os.listdir(od)))
    for n in os.listdir(od):
        p = os.path.join(od, n)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
core.free_space = real
print("real free_space D:", core.free_space(od), "fs:", core.filesystem_name(od))
print("free_space on missing folder:", core.free_space(os.path.join(od, "nope")))
fsrc = os.path.join(HERE, "media", "obs", "obs_fragmented.mov")
core.free_space = lambda folder: 1024
r = core.Converter(core.Options(out_dir=od, verify=False)).convert(fsrc)
print("fmp4 tiny", r.status, r.message, os.listdir(od))
