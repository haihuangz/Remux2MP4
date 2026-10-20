import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mkv2mp4_core as core

MEDIA = os.path.join(HERE, "media")
OUT = os.path.join(HERE, "out", "_gen2")
os.makedirs(OUT, exist_ok=True)


def cut(src, dst, size):
    with open(src, "rb") as f, open(dst, "wb") as g:
        g.write(f.read(size))


def mid_sample_cut(src, dst):
    boxes, size = core.scan_boxes(src)
    mdats = [b for b in boxes if b[0] == "mdat" and b[3]]
    typ, off, n, _ = mdats[-2]
    with open(src, "rb") as f:
        moofs = [b for b in boxes if b[0] == "moof" and b[1] < off]
        samples = core._moof_samples(f, moofs[-1][1], moofs[-1][2], core._trex_sizes(f, boxes))
    big = max(samples, key=lambda s: s[1])
    point = big[0] + big[1] // 2
    cut(src, dst, point)
    return point, big


def crashed_plain_mp4(dst):
    tmp = dst + ".tmp.mp4"
    if os.path.exists(tmp):
        os.remove(tmp)
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i",
                          "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=frequency=440",
                          "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-t", "30", tmp],
                         stdin=subprocess.DEVNULL)
    time.sleep(4)
    p.kill()
    p.wait()
    shutil.move(tmp, dst)


def corrupt_middle(src, dst):
    shutil.copyfile(src, dst)
    size = os.path.getsize(dst)
    with open(dst, "r+b") as f:
        f.seek(int(size * 0.55))
        f.write(b"\x00" * 4096)


if __name__ == "__main__":
    for name in ("frag_truncated.mp4",):
        pass
    p, big = mid_sample_cut(os.path.join(MEDIA, "fmp4", "frag_h264_2aac_sub_chapters.mp4"),
                            os.path.join(OUT, "frag_midsample.mp4"))
    print("frag_midsample.mp4 cut at", p, "inside sample", big)
    p, big = mid_sample_cut(os.path.join(MEDIA, "obs", "obs_fragmented.mp4"), os.path.join(OUT, "obs_frag_midsample.mp4"))
    print("obs_frag_midsample.mp4 cut at", p, "inside sample", big)
    crashed_plain_mp4(os.path.join(OUT, "crashed_plain.mp4"))
    print("crashed_plain.mp4", core.mp4_layout(os.path.join(OUT, "crashed_plain.mp4"))["boxes"])
    shutil.copyfile(os.path.join(MEDIA, "obs", "obs_h264_6aac.mkv"), os.path.join(OUT, "renamed_mkv.mp4"))
    corrupt_middle(os.path.join(MEDIA, "obs", "obs_h264_6aac.mkv"), os.path.join(OUT, "complete_corrupt_middle.mkv"))
    src = os.path.join(MEDIA, "multi.mkv")
    with open(src, "rb") as f:
        data = f.read()
    first_cluster = data.find(bytes.fromhex("1F43B675"))
    cut(src, os.path.join(OUT, "multi_trunc80.mkv"), int(len(data) * 0.8))
    cut(src, os.path.join(OUT, "header_only.mkv"), 3000)
    print("multi.mkv first cluster at", first_cluster, "size", len(data))
