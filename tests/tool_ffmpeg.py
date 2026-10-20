import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mkv2mp4_core as core


def describe(path=None):
    path = path or core.locate_tool("ffmpeg")
    if not path:
        return "ffmpeg used by the tool: not found"
    out = core.run_quiet([path, "-version"]).stdout.splitlines()
    conf = next((l for l in out if l.startswith("configuration:")), "")
    build = "slim (--disable-network)" if "--disable-network" in conf else "full"
    return f"ffmpeg used by the tool: {path} | {out[0] if out else '?'} | {build}"


def log_line():
    return "ffmpeg:" + describe()
