import os
import struct
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "media")
SRC = os.path.join(MEDIA, "_src")
DUR = "6"
FONT_NAME = "testfont.ttf"

SRT_ZH = """1
00:00:00,500 --> 00:00:02,500
第一行字幕：你好，世界

2
00:00:03,000 --> 00:00:05,500
第二行字幕 <i>斜体</i>
"""

SRT_SIMPLE = """1
00:00:00,500 --> 00:00:03,000
中文 字幕 测试

2
00:00:03,500 --> 00:00:05,500
第二句
"""

ASS_EN = """[Script Info]
Title: styled test
ScriptType: v4.00+
PlayResX: 640
PlayResY: 360
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,28,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,20,20,20,1
Style: Sign,Arial,36,&H0000FFFF,&H000000FF,&H00400000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,8,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.50,Default,,0,0,0,,{\\b1}Bold{\\b0} and {\\c&H00FF00&}green{\\r} text
Dialogue: 0,0:00:01.00,0:00:04.00,Sign,,0,0,0,,{\\pos(320,60)\\fad(200,200)}Positioned sign
Dialogue: 0,0:00:03.00,0:00:05.50,Default,,0,0,0,,{\\i1}Italic line{\\i0}\\Nsecond row
"""

VTT = """WEBVTT

00:00:00.500 --> 00:00:02.500
<b>WebVTT</b> line one

00:00:03.000 --> 00:00:05.500 align:start position:10%
WebVTT line two
"""

FFMETA = """;FFMETADATA1
title=多轨测试 Multi Track Test
artist=测试艺术家 Test Artist
comment=全局注释 global comment
date=2026
MY_CUSTOM_TAG=custom value 自定义
ENCODED_BY_TEST=make_samples.py

[CHAPTER]
TIMEBASE=1/1000
START=0
END=2000
title=第一章 Opening

[CHAPTER]
TIMEBASE=1/1000
START=2000
END=4000
title=Chapter 2 中段

[CHAPTER]
TIMEBASE=1/1000
START=4000
END=6000
title=第三章 Ending
"""


def run(args, check=True):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("FAILED:", " ".join(cmd))
        print(r.stderr)
        if check:
            raise SystemExit(1)
    return r.returncode == 0


def write(name, text):
    path = os.path.join(SRC, name)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def out(name):
    return os.path.join(MEDIA, name)


def video_src(size="640x360", rate=24):
    return ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={DUR}"]


def sine(freq, extra=""):
    return ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={DUR}{extra}"]


def stereo(freq):
    return sine(freq, ",pan=stereo|c0=c0|c1=c0")


def make_cover():
    path = os.path.join(SRC, "cover.jpg")
    run(["-f", "lavfi", "-i", "testsrc=size=600x600:rate=1", "-frames:v", "1", "-q:v", "3", path])
    return path


def _box_glyph(x0, y0, x1, y1):
    pts = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
    xs = [pts[0][0]] + [pts[i][0] - pts[i - 1][0] for i in range(1, 4)]
    ys = [pts[0][1]] + [pts[i][1] - pts[i - 1][1] for i in range(1, 4)]
    return (struct.pack(">hhhhhHH", 1, x0, y0, x1, y1, 3, 0) + bytes([1] * 4)
            + struct.pack(">4h", *xs) + struct.pack(">4h", *ys))


def _name_table(names):
    recs, data = b"", b""
    for nid, text in names:
        raw = text.encode("utf-16-be")
        recs += struct.pack(">6H", 3, 1, 0x409, nid, len(raw), len(data))
        data += raw
    return struct.pack(">3H", 0, len(names), 6 + len(recs)) + recs + data


def _checksum(data):
    data += b"\0" * (-len(data) % 4)
    return sum(struct.unpack(f">{len(data) // 4}I", data)) & 0xFFFFFFFF


def font_bytes():
    glyphs = [_box_glyph(50, 0, 450, 700), _box_glyph(100, 0, 500, 700)]
    glyf, loca = b"", []
    for g in glyphs:
        loca.append(len(glyf) // 2)
        glyf += g
    loca.append(len(glyf) // 2)
    n = len(glyphs)
    cmap_sub = struct.pack(">7H", 4, 32, 0, 4, 4, 1, 0) + struct.pack(">2H", 0x41, 0xFFFF) + b"\0\0"
    cmap_sub += struct.pack(">2H", 0x41, 0xFFFF) + struct.pack(">2h", 1 - 0x41, 1) + struct.pack(">2H", 0, 0)
    family = "MKV2MP4 Test"
    tables = {
        b"head": struct.pack(">IIIIHHqqhhhhHHhhh", 0x00010000, 0x00010000, 0, 0x5F0F3CF5, 0x000B, 1000, 3850070400, 3850070400,
                             0, 0, 550, 700, 0, 8, 2, 0, 0),
        b"hhea": struct.pack(">Ihhh H hhh hhh 4h hH".replace(" ", ""), 0x00010000, 800, -200, 0, 600, 50, 50, 500,
                             1, 0, 0, 0, 0, 0, 0, 0, n),
        b"maxp": struct.pack(">IHHHHHHHHHHHHHH", 0x00010000, n, 4, 1, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0),
        b"OS/2": struct.pack(">HhHHH10hh10s4I4sHHHhhhHH2IhhHHH", 4, 600, 400, 5, 0,
                             650, 600, 0, 75, 650, 600, 0, 350, 50, 250, 0, bytes(10), 0, 0, 0, 0, b"NONE",
                             0x40, 0x41, 0x41, 800, -200, 0, 800, 200, 1, 0, 500, 700, 0, 0x20, 1),
        b"cmap": struct.pack(">HHHHI", 0, 1, 3, 1, 12) + cmap_sub,
        b"glyf": glyf,
        b"loca": struct.pack(f">{len(loca)}H", *loca),
        b"hmtx": struct.pack(">HhHh", 500, 50, 600, 100),
        b"name": _name_table([(1, family), (2, "Regular"), (3, family + " Regular 1.0"), (4, family + " Regular"),
                              (5, "Version 1.000"), (6, "MKV2MP4Test-Regular")]),
        b"post": struct.pack(">IIhhIIIII", 0x00030000, 0, -100, 50, 0, 0, 0, 0, 0),
    }
    tags = sorted(tables)
    entry = 1 << (len(tags).bit_length() - 1)
    out = struct.pack(">IHHHH", 0x00010000, len(tags), entry * 16, entry.bit_length() - 1, len(tags) * 16 - entry * 16)
    offset = 12 + 16 * len(tags)
    body = b""
    for tag in tags:
        data = tables[tag]
        out += struct.pack(">4sIII", tag, _checksum(data), offset + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    font = bytearray(out + body)
    head_off = offset + sum(len(tables[t]) + (-len(tables[t]) % 4) for t in tags[:tags.index(b"head")])
    struct.pack_into(">I", font, head_off + 8, (0xB1B0AFBA - _checksum(bytes(font))) & 0xFFFFFFFF)
    return bytes(font)


def make_font():
    dst = os.path.join(SRC, FONT_NAME)
    with open(dst, "wb") as fh:
        fh.write(font_bytes())
    return dst


def make_multi(srt, ass, vtt, meta, font, cover):
    run(video_src() + stereo(440)
        + sine(330, ",pan=5.1|c0=c0|c1=c0|c2=c0|c3=c0|c4=c0|c5=c0")
        + sine(550)
        + ["-i", srt, "-i", ass, "-i", vtt, "-i", meta,
           "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a", "-map", "4:s", "-map", "5:s", "-map", "6:s",
           "-map_metadata", "7", "-map_chapters", "7",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a:0", "aac", "-b:a:0", "128k",
           "-c:a:1", "ac3", "-b:a:1", "384k",
           "-c:a:2", "flac",
           "-c:s:0", "srt", "-c:s:1", "ass", "-c:s:2", "webvtt",
           "-metadata:s:v:0", "title=主视频 Main Video", "-metadata:s:v:0", "language=und",
           "-metadata:s:a:0", "language=jpn", "-metadata:s:a:0", "title=日语",
           "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=English 5.1",
           "-metadata:s:a:2", "language=chi", "-metadata:s:a:2", "title=国语",
           "-metadata:s:s:0", "language=chi", "-metadata:s:s:0", "title=简体中文",
           "-metadata:s:s:1", "language=eng", "-metadata:s:s:1", "title=English Signs (ASS)",
           "-metadata:s:s:2", "language=jpn", "-metadata:s:s:2", "title=WebVTT 日本語",
           "-disposition:a:0", "default", "-disposition:a:1", "0", "-disposition:a:2", "0",
           "-disposition:s:0", "default", "-disposition:s:1", "forced", "-disposition:s:2", "0",
           "-attach", font, "-metadata:s:t:0", "mimetype=application/x-truetype-font",
           "-metadata:s:t:0", f"filename={os.path.basename(font)}",
           "-attach", cover, "-metadata:s:t:1", "mimetype=image/jpeg", "-metadata:s:t:1", "filename=cover.jpg",
           out("multi.mkv")])


X265_HDR = ("hdr10=1:repeat-headers=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:range=limited:"
            "master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):max-cll=1000,400:log-level=error")

RARE_AUDIO = [
    ("eac3", ["-b", "384k"], 2),
    ("truehd", ["-strict", "-2"], 2),
    ("dca", ["-strict", "-2"], 2),
    ("libopus", ["-b", "128k"], 2),
    ("pcm_s24le", [], 2),
    ("libvorbis", ["-q", "4"], 2),
    ("mp2", ["-b", "192k"], 2),
    ("alac", [], 2),
]


def make_hevc10_rare_audio():
    args = video_src("640x360")
    for i, _ in enumerate(RARE_AUDIO):
        args += stereo(300 + 60 * i)
    args += ["-map", "0:v"]
    for i, _ in enumerate(RARE_AUDIO):
        args += ["-map", f"{i + 1}:a"]
    args += ["-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le", "-x265-params", X265_HDR,
             "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc", "-color_range", "tv"]
    for i, (enc, extra, _) in enumerate(RARE_AUDIO):
        args += [f"-c:a:{i}", enc]
        for j in range(0, len(extra), 2):
            key = extra[j]
            args += [f"{key}:a:{i}" if key != "-strict" else key, extra[j + 1]]
        args += [f"-metadata:s:a:{i}", f"title={enc} track", f"-metadata:s:a:{i}", "language=eng"]
    args += ["-metadata:s:v:0", "title=HEVC 10bit HDR10", out("hevc10_rare_audio.mkv")]
    run(args)


def make_av1_vp9_family():
    jobs = [
        ("av1_opus.mkv", ["-c:v", "libsvtav1", "-preset", "12", "-pix_fmt", "yuv420p"], ["-c:a", "libopus", "-b:a", "96k"]),
        ("vp9_vorbis.mkv", ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "500k"], ["-c:a", "libvorbis", "-q:a", "3"]),
        ("vp8_vorbis.mkv", ["-c:v", "libvpx", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "500k"], ["-c:a", "libvorbis", "-q:a", "3"]),
        ("mpeg2_mp2.mkv", ["-c:v", "mpeg2video", "-q:v", "4"], ["-c:a", "mp2", "-b:a", "192k"]),
        ("theora_vorbis.mkv", ["-c:v", "libtheora", "-q:v", "6"], ["-c:a", "libvorbis", "-q:a", "3"]),
    ]
    for name, v, a in jobs:
        run(video_src("640x360", 25) + stereo(500) + ["-map", "0:v", "-map", "1:a"] + v + a
            + ["-metadata:s:a:0", "language=fre", "-metadata:s:a:0", f"title={name} audio", out(name)])


def rle_line(runs):
    nibbles = []
    for n, c in runs:
        if n == 0:
            code, width = c, 4
        elif n < 4:
            code, width = (n << 2) | c, 1
        elif n < 16:
            code, width = (n << 2) | c, 2
        elif n < 64:
            code, width = (n << 2) | c, 3
        else:
            code, width = (n << 2) | c, 4
        for k in range(width - 1, -1, -1):
            nibbles.append((code >> (4 * k)) & 0xF)
    if len(nibbles) % 2:
        nibbles.append(0)
    return bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))


def spu_packet(width, height, x, y, duration_ticks):
    lines = []
    for row in range(height):
        if row < 2 or row >= height - 2:
            lines.append(rle_line([(width, 1)]))
        else:
            mid = width - 8
            stripe = 2 if (row // 4) % 2 else 3
            lines.append(rle_line([(4, 1), (mid, stripe), (4, 1)]))
    top = b"".join(lines[0::2])
    bottom = b"".join(lines[1::2])
    data_start = 4
    top_off = data_start
    bot_off = top_off + len(top)
    ctrl1 = bot_off + len(bottom)
    x2, y2 = x + width - 1, y + height - 1
    coords = bytes([x >> 4, ((x & 0xF) << 4) | (x2 >> 8), x2 & 0xFF, y >> 4, ((y & 0xF) << 4) | (y2 >> 8), y2 & 0xFF])
    seq1_body = (b"\x01" + b"\x03" + bytes([0x32, 0x10]) + b"\x04" + bytes([0xFF, 0xF0]) + b"\x05" + coords
                 + b"\x06" + top_off.to_bytes(2, "big") + bot_off.to_bytes(2, "big") + b"\xff")
    ctrl2 = ctrl1 + 4 + len(seq1_body)
    seq1 = (0).to_bytes(2, "big") + ctrl2.to_bytes(2, "big") + seq1_body
    seq2 = duration_ticks.to_bytes(2, "big") + ctrl2.to_bytes(2, "big") + b"\x02\xff"
    body = top + bottom + seq1 + seq2
    total = 4 + len(body)
    return total.to_bytes(2, "big") + ctrl1.to_bytes(2, "big") + body


def pts_bytes(pts):
    return bytes([
        0x21 | ((pts >> 29) & 0x0E),
        (pts >> 22) & 0xFF,
        ((pts >> 14) & 0xFE) | 1,
        (pts >> 7) & 0xFF,
        ((pts << 1) & 0xFE) | 1,
    ])


def ps_sector(spu, pts):
    pack = bytes.fromhex("000001BA4400040004010189C3F8")
    payload = b"\x20" + spu
    pes_body = b"\x81\x80\x05" + pts_bytes(pts) + payload
    pes = b"\x00\x00\x01\xbd" + len(pes_body).to_bytes(2, "big") + pes_body
    sector = pack + pes
    pad = 2048 - len(sector)
    if pad >= 6:
        sector += b"\x00\x00\x01\xbe" + (pad - 6).to_bytes(2, "big") + b"\xff" * (pad - 6)
    elif pad > 0:
        sector += b"\xff" * pad
    return sector


def make_vobsub():
    idx = os.path.join(SRC, "dvd.idx")
    sub = os.path.join(SRC, "dvd.sub")
    events = [(0.5, 2.0), (3.0, 2.5)]
    palette = ["000000", "ffffff", "ffff00", "00a0ff"] + ["808080"] * 12
    sectors, idx_lines = [], []
    for i, (start, dur) in enumerate(events):
        spu = spu_packet(200, 40, 220, 300, int(dur * 90000 / 1024))
        sectors.append(ps_sector(spu, int(start * 90000)))
        ms = int(start * 1000)
        ts = f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}:{ms % 1000:03d}"
        idx_lines.append(f"timestamp: {ts}, filepos: {i * 2048:09x}")
    with open(sub, "wb") as fh:
        fh.write(b"".join(sectors))
    with open(idx, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# VobSub index file, v7 (do not modify this line!)\n")
        fh.write("size: 720x480\norg: 0, 0\nscale: 100%, 100%\nalpha: 100%\nsmooth: OFF\nfadein/out: 0, 0\n")
        fh.write("align: OFF at LEFT TOP\ntime offset: 0\nforced subs: OFF\n")
        fh.write("palette: " + ", ".join(palette) + "\n")
        fh.write("custom colors: OFF, tridx: 0000, colors: 000000, 000000, 000000, 000000\n")
        fh.write("langidx: 0\n\nid: en, index: 0\n")
        fh.write("\n".join(idx_lines) + "\n")
    return idx


def make_dvdsub():
    idx = make_vobsub()
    ok = run(video_src("720x480", 25) + stereo(600) + ["-i", idx,
             "-map", "0:v", "-map", "1:a", "-map", "2:s",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "copy",
             "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "title=DVD bitmap subs",
             out("dvdsub.mkv")], check=False)
    print("dvdsub.mkv", "OK" if ok else "could not be synthesized")


def _pgs_rle(row):
    out, i = bytearray(), 0
    while i < len(row):
        c, n = row[i], 1
        while i + n < len(row) and row[i + n] == c and n < 16383:
            n += 1
        if c and n < 3:
            out += bytes([c]) * n
        elif c == 0:
            out += bytes([0, n]) if n < 64 else bytes([0, 0x40 | n >> 8, n & 0xFF])
        else:
            out += bytes([0, 0x80 | n, c]) if n < 64 else bytes([0, 0xC0 | n >> 8, n & 0xFF, c])
        i += n
    return bytes(out) + b"\0\0"


def _pgs_segment(pts, kind, body):
    return b"PG" + struct.pack(">IIBH", int(pts * 90000), 0, kind, len(body)) + body


def make_pgs_sup(path, events, size=(640, 360), box=(200, 300, 240, 40)):
    x, y, w, h = box
    rows = []
    for r in range(h):
        if r < 2 or r >= h - 2:
            rows.append([2] * w)
        else:
            rows.append([2, 2] + [0 if (c // 12) % 3 == 0 else 1 for c in range(w - 4)] + [2, 2])
    rle = b"".join(_pgs_rle(r) for r in rows)
    window = struct.pack(">BBHHHH", 1, 0, x, y, w, h)
    palette = struct.pack(">BB", 0, 0) + bytes([0, 16, 128, 128, 0, 1, 235, 128, 128, 255, 2, 81, 90, 240, 255])
    obj = struct.pack(">HBB", 0, 0, 0xC0) + (len(rle) + 4).to_bytes(3, "big") + struct.pack(">HH", w, h) + rle
    data, num = b"", 0
    for start, end in events:
        data += _pgs_segment(start, 0x16, struct.pack(">HHBHBBBB", *size, 0x10, num, 0x80, 0, 0, 1)
                             + struct.pack(">HBBHH", 0, 0, 0, x, y))
        data += _pgs_segment(start, 0x17, window) + _pgs_segment(start, 0x14, palette)
        data += _pgs_segment(start, 0x15, obj) + _pgs_segment(start, 0x80, b"")
        data += _pgs_segment(end, 0x16, struct.pack(">HHBHBBBB", *size, 0x10, num + 1, 0, 0, 0, 0))
        data += _pgs_segment(end, 0x17, window) + _pgs_segment(end, 0x80, b"")
        num += 2
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def make_pgs():
    sup = make_pgs_sup(os.path.join(SRC, "pgs.sup"), [(0.5, 3.0), (3.5, 6.0)])
    ok = run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=8"]
             + ["-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=8,pan=stereo|c0=c0|c1=c0", "-i", sup,
                "-map", "0:v", "-map", "1:a", "-map", "2:s",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "copy",
                "-metadata:s:s:0", "language=chi", "-metadata:s:s:0", "title=PGS 中文",
                out("pgs.mkv")], check=False)
    print("pgs.mkv", "OK" if ok else "could not be synthesized")


def make_simple_family(srt_simple):
    run(video_src() + stereo(440) + ["-i", srt_simple, "-map", "0:v", "-map", "1:a", "-map", "2:s",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "srt",
        "-metadata:s:a:0", "language=chi", "-metadata:s:s:0", "language=chi", "-metadata:s:s:0", "title=中文",
        out("中文 空格 [测试] (1).mkv")])
    run(video_src() + ["-map", "0:v", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        out("no_audio.mkv")])
    run(video_src() + stereo(440) + ["-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-metadata:s:a:0", "language=eng", out("already_compatible.mkv")])
    with open(out("multi.mkv"), "rb") as fh:
        data = fh.read()
    first_cluster = data.find(bytes.fromhex("1F43B675"))
    cut_at = max(int(len(data) * 0.8), first_cluster + (len(data) - first_cluster) // 2)
    with open(out("truncated.mkv"), "wb") as fh:
        fh.write(data[:cut_at])
    with open(out("header_only.mkv"), "wb") as fh:
        fh.write(data[:3000])


def main():
    os.makedirs(SRC, exist_ok=True)
    srt = write("zh.srt", SRT_ZH)
    srt_simple = write("simple_zh.srt", SRT_SIMPLE)
    ass = write("en_styled.ass", ASS_EN)
    vtt = write("ja.vtt", VTT)
    meta = write("meta_chapters.ffmeta", FFMETA)
    font = make_font()
    cover = make_cover()
    make_multi(srt, ass, vtt, meta, font, cover)
    print("multi.mkv OK")
    make_hevc10_rare_audio()
    print("hevc10_rare_audio.mkv OK")
    make_av1_vp9_family()
    print("av1/vp9/vp8/mpeg2/theora OK")
    make_dvdsub()
    make_pgs()
    make_simple_family(srt_simple)
    print("simple family OK")
    for f in sorted(os.listdir(MEDIA)):
        p = os.path.join(MEDIA, f)
        if os.path.isfile(p):
            print(f"{os.path.getsize(p):>10}  {f}")


if __name__ == "__main__":
    main()
