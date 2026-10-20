import glob, os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import mkv2mp4_core as core
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for f in sorted(glob.glob(os.path.join(H, "media", "**", "*.mkv"), recursive=True) + glob.glob(os.path.join(H, "out", "_gen", "*.mkv")) + glob.glob(os.path.join(H, "media", "**", "*.mp4"), recursive=True)+ glob.glob(os.path.join(H, "media", "**", "*.mov"), recursive=True)):
    if "_out" in f: continue
    print(core.classify(f)[0] if f.endswith((".mp4",".mov")) else core.mkv_end_state(f), os.path.relpath(f, H), core.classify(f)[1][:60])
