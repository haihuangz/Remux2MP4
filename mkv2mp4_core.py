import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

APP_NAME = "视频转MP4"
VERSION = "1.1.0"

MKV_EXTS = {".mkv", ".webm"}
MP4_EXTS = {".mp4", ".m4v", ".mov", ".m4s"}
TS_EXTS = {".ts", ".m2ts", ".mts"}
FLV_EXTS = {".flv"}
ALL_EXTS = MKV_EXTS | MP4_EXTS | TS_EXTS | FLV_EXTS

VIDEO_COPY = {"h264", "hevc", "av1", "vp9", "mpeg1video", "mpeg2video", "mpeg4", "mjpeg", "ffv1"}
AUDIO_COPY = {"aac", "mp3", "mp2", "ac3", "eac3", "dts", "flac", "alac", "opus", "vorbis", "truehd",
              "pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be", "pcm_s32le", "pcm_s32be",
              "pcm_f32le", "pcm_f32be", "pcm_f64le", "pcm_f64be"}
AUDIO_NEEDS_STRICT = {"truehd"}
AUDIO_LOSSLESS = {"truehd", "mlp", "flac", "alac", "wavpack", "tta", "ape", "tak", "mp4als"}
COMPANION_LOSSY = {"dts", "vorbis"}
COMPANION_LOSSLESS = {"truehd"}
TEXT_SUBS = {"subrip": ".srt", "ass": ".ass", "ssa": ".ssa", "webvtt": ".vtt", "text": ".srt", "mov_text": ".srt"}
FONT_EXTS = {".ttf", ".otf", ".ttc", ".woff", ".woff2", ".fon"}
COVER_WORDS = ("cover", "poster", "folder", "front", "封面", "海报")
DISPOSITIONS = ("default", "dub", "original", "comment", "lyrics", "karaoke", "forced",
                "hearing_impaired", "visual_impaired", "captions", "descriptions")
STANDARD_GLOBAL_TAGS = {"title", "artist", "album_artist", "album", "date", "comment", "genre", "copyright",
                        "composer", "grouping", "lyrics", "description", "synopsis", "show", "episode_id",
                        "network", "track", "disc", "compilation"}
IGNORED_GLOBAL_TAGS = {"encoder", "creation_time", "major_brand", "minor_version", "compatible_brands",
                       "duration", "encoded_by", "encoding_tool", "writing_application", "muxing_application"}
IGNORED_STREAM_TAGS = {"language", "title", "handler_name", "duration", "bps", "number_of_frames",
                       "number_of_bytes", "_statistics_writing_app", "_statistics_writing_date_utc",
                       "_statistics_tags", "encoder", "vendor_id", "creation_time", "filename", "mimetype",
                       "timecode", "language_bcp47"}
LANG_MAP = {
    "zh": "chi", "en": "eng", "ja": "jpn", "ko": "kor", "fr": "fre", "de": "ger", "es": "spa", "pt": "por",
    "ru": "rus", "it": "ita", "ar": "ara", "th": "tha", "vi": "vie", "id": "ind", "ms": "may", "nl": "dut",
    "sv": "swe", "pl": "pol", "tr": "tur", "uk": "ukr", "hi": "hin", "he": "heb", "el": "gre", "cs": "cze",
    "da": "dan", "fi": "fin", "no": "nor", "nb": "nob", "nn": "nno", "hu": "hun", "ro": "rum", "bg": "bul",
    "hr": "hrv", "sr": "srp", "sk": "slo", "sl": "slv", "et": "est", "lv": "lav", "lt": "lit", "fa": "per",
    "ta": "tam", "te": "tel", "bn": "ben", "ur": "urd", "fil": "fil", "tl": "tgl", "ca": "cat", "eu": "baq",
    "gl": "glg", "is": "ice", "ga": "gle", "cy": "wel", "mn": "mon", "bo": "tib", "ug": "uig", "km": "khm",
    "lo": "lao", "my": "bur", "ne": "nep", "si": "sin", "ka": "geo", "hy": "arm", "az": "aze", "kk": "kaz",
    "uz": "uzb", "la": "lat", "eo": "epo", "sw": "swa", "af": "afr", "zu": "zul", "yi": "yid",
}
ANNEXB_STRIP = {"h264": "7|8|9", "hevc": "32|33|34|35"}
ANNEXB_PS = {"h264": "7|8", "hevc": "32|33|34"}
AV1_STRIP = "filter_units=remove_types=2|15"
AUDIO_EXPORT = {"aac": (".m4a", "ipod"), "alac": (".m4a", "ipod"), "mp3": (".mp3", "mp3"), "flac": (".flac", "flac"),
                "opus": (".opus", "opus"), "vorbis": (".ogg", "ogg"), "ac3": (".ac3", "ac3"), "eac3": (".eac3", "eac3"),
                "pcm_u8": (".wav", "wav"), "pcm_s16le": (".wav", "wav"), "pcm_s24le": (".wav", "wav"),
                "pcm_s32le": (".wav", "wav"), "pcm_f32le": (".wav", "wav"), "pcm_f64le": (".wav", "wav")}
AUDIO_DIR_SUFFIX = "_音轨"
AUDIO_OFFSET_WARN = 0.1
FULL_HASH_LIMIT = 8 * 1024 ** 3
SAMPLE_PACKETS = 3000
DECODE_WINDOW = 20


class Cancelled(Exception):
    pass


class ConvertError(Exception):
    def __init__(self, msg, tech=""):
        super().__init__(msg)
        self.tech = tech


class SkipError(ConvertError):
    pass


@dataclass
class Options:
    out_dir: str = None
    companion: bool = True
    sidecars: bool = True
    faststart: bool = True
    verify: bool = True
    export_audio: bool = False


@dataclass
class OutStream:
    src: int
    kind: str
    codec_args: list
    expect_codec: str
    lang: str
    title: str
    disposition: list
    role: str
    hash_check: bool = False


@dataclass
class Sidecar:
    src: int
    path: str
    args: list
    what: str
    partial: str = ""


@dataclass
class Plan:
    container: str = "mp4"
    streams: list = field(default_factory=list)
    sidecars: list = field(default_factory=list)
    dumps: list = field(default_factory=list)
    strict: bool = False
    write_tmcd: bool = False
    lines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    metadata_sidecar: bool = False
    companions: int = 0
    input_flags: list = field(default_factory=list)


@dataclass
class FileResult:
    src: str
    kind: str = ""
    status: str = "pending"
    output: str = ""
    message: str = ""
    report_path: str = ""
    extra_files: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    recovered_until: float = None
    tech: str = ""
    tech_lines: list = field(default_factory=list)
    audio_dir: str = ""
    audio_files: list = field(default_factory=list)


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _exe(name):
    return name + ".exe" if os.name == "nt" else name


FFMPEG_DIR_ENV = "MKV2MP4_FFMPEG_DIR"
TOOLS = ("ffmpeg", "ffprobe")


def locate_tool(name):
    dirs = [os.path.join(app_dir(), "bin")]
    if os.environ.get(FFMPEG_DIR_ENV):
        dirs.append(os.environ[FFMPEG_DIR_ENV])
    for d in dirs:
        p = os.path.join(d, _exe(name))
        if os.path.isfile(p):
            return p
    return shutil.which(name)


def missing_tools():
    return [n for n in TOOLS if not locate_tool(n)]


def missing_tools_message(names=None):
    names = names or missing_tools()
    files = " 和 ".join(_exe(n) for n in names)
    return (f"找不到 {files}，没法转换。\n\n"
            f"请把 {' 和 '.join(_exe(n) for n in TOOLS)} 放到程序文件夹里的 bin 文件夹：\n"
            f"  {os.path.join(app_dir(), 'bin')}\n"
            f"或者设置环境变量 {FFMPEG_DIR_ENV}，指向放着它们的文件夹；\n"
            "或者安装 ffmpeg 并加入系统 PATH。")


def find_tool(name):
    found = locate_tool(name)
    if found:
        return found
    raise ConvertError(missing_tools_message([name]))


def _popen_kwargs():
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000
    return kw


_cancel_local = threading.local()


def _current_cancel():
    return getattr(_cancel_local, "event", None)


def run_quiet(args, timeout=None):
    cancel = _current_cancel()
    if cancel is None:
        return subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=timeout, **_popen_kwargs())
    if cancel.is_set():
        raise Cancelled()
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         encoding="utf-8", errors="replace", **_popen_kwargs())
    start = time.time()
    while True:
        try:
            out, err = p.communicate(timeout=0.3)
            break
        except subprocess.TimeoutExpired:
            if cancel.is_set() or (timeout and time.time() - start > timeout):
                p.kill()
                p.communicate()
                if cancel.is_set():
                    raise Cancelled()
                raise subprocess.TimeoutExpired(args, timeout)
    return subprocess.CompletedProcess(args, p.returncode, out, err)


def fmt_time(sec):
    if sec is None:
        return "?"
    sec = max(0, int(round(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def probe(path):
    r = run_quiet([find_tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-show_chapters",
                   "-of", "json", path])
    try:
        data = json.loads(r.stdout) if r.stdout.strip() else {}
    except ValueError:
        data = {}
    data.setdefault("streams", [])
    data.setdefault("chapters", [])
    data.setdefault("format", {})
    data["_rc"] = r.returncode
    data["_stderr"] = r.stderr.strip()
    return data


def scan_boxes(path, max_boxes=2_000_000):
    size = os.path.getsize(path)
    boxes = []
    with open(path, "rb") as f:
        pos = 0
        while pos + 8 <= size and len(boxes) < max_boxes:
            f.seek(pos)
            head = f.read(16)
            if len(head) < 8:
                break
            n = int.from_bytes(head[:4], "big")
            typ = head[4:8].decode("latin1")
            hdr = 8
            if n == 1:
                if len(head) < 16:
                    break
                n = int.from_bytes(head[8:16], "big")
                hdr = 16
            elif n == 0:
                n = size - pos
            if n < hdr or not re.fullmatch(r"[\x20-\x7e]{4}", typ):
                boxes.append((typ, pos, n, False))
                break
            boxes.append((typ, pos, n, pos + n <= size))
            pos += n
    return boxes, size


def _child_types(path, offset, length, hdr=8):
    out = []
    with open(path, "rb") as f:
        pos = offset + hdr
        end = offset + length
        while pos + 8 <= end:
            f.seek(pos)
            head = f.read(8)
            n = int.from_bytes(head[:4], "big")
            typ = head[4:8].decode("latin1", "replace")
            if n < 8:
                break
            out.append(typ)
            pos += n
    return out


def mp4_layout(path):
    boxes, size = scan_boxes(path)
    types = [b[0] for b in boxes]
    info = {"boxes": types, "size": size, "fragmented": False, "truncated": False, "has_moov": "moov" in types,
            "moov_first": False, "valid": bool(boxes) and types[0] in ("ftyp", "styp", "moov", "free", "skip", "wide", "mdat")}
    if not info["valid"]:
        return info
    if boxes and not boxes[-1][3]:
        info["truncated"] = True
    if "moof" in types:
        info["fragmented"] = True
    for typ, off, n, complete in boxes:
        if typ == "moov" and complete:
            if "mvex" in _child_types(path, off, n):
                info["fragmented"] = True
            break
    if "moov" in types and "mdat" in types:
        info["moov_first"] = types.index("moov") < types.index("mdat")
    elif "moov" in types:
        info["moov_first"] = True
    if info["truncated"] and types[-1] == "moov" and not info["fragmented"]:
        for typ, off, n, complete in boxes:
            if typ == "mdat" and complete and n > 16:
                inner = _child_types(path, off, min(n, 64 * 1024 ** 2), 16 if _box_hdr(path, off) == 16 else 8)
                if inner[:1] == ["moov"] or "moof" in inner[:4]:
                    info["hybrid_unfinished"] = True
                break
    return info


def _iter_boxes(f, start, end):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        h = f.read(16)
        if len(h) < 8:
            return
        n = int.from_bytes(h[:4], "big")
        hdr = 8
        if n == 1:
            if len(h) < 16:
                return
            n = int.from_bytes(h[8:16], "big")
            hdr = 16
        elif n == 0:
            n = end - pos
        if n < hdr or pos + n > end:
            return
        yield h[4:8].decode("latin1"), pos, hdr, n
        pos += n


def _u32(b, o):
    return int.from_bytes(b[o:o + 4], "big")


def _trex_sizes(f, boxes):
    sizes = {}
    for typ, off, n, complete in boxes:
        if typ != "moov" or not complete:
            continue
        for t2, o2, h2, n2 in _iter_boxes(f, off + _hdr_at(f, off), off + n):
            if t2 != "mvex":
                continue
            for t3, o3, h3, n3 in _iter_boxes(f, o2 + h2, o2 + n2):
                if t3 == "trex" and n3 - h3 >= 24:
                    f.seek(o3 + h3)
                    b = f.read(24)
                    sizes[_u32(b, 4)] = _u32(b, 16)
    return sizes


def _hdr_at(f, off):
    f.seek(off)
    return 16 if int.from_bytes(f.read(4), "big") == 1 else 8


def _moof_samples(f, moof_off, moof_len, trex):
    samples = []
    hdr = _hdr_at(f, moof_off)
    prev_end = None
    for typ, toff, thdr, tlen in _iter_boxes(f, moof_off + hdr, moof_off + moof_len):
        if typ != "traf":
            continue
        tfhd = None
        runs = []
        for t2, o2, h2, n2 in _iter_boxes(f, toff + thdr, toff + tlen):
            f.seek(o2 + h2)
            body = f.read(n2 - h2)
            if t2 == "tfhd":
                tfhd = body
            elif t2 == "trun":
                runs.append(body)
        if tfhd is None or len(tfhd) < 8:
            return None
        flags = _u32(tfhd, 0) & 0xFFFFFF
        track = _u32(tfhd, 4)
        p = 8
        base = None
        if flags & 0x1:
            base = int.from_bytes(tfhd[p:p + 8], "big")
            p += 8
        if flags & 0x2:
            p += 4
        if flags & 0x8:
            p += 4
        default_size = trex.get(track)
        if flags & 0x10:
            default_size = _u32(tfhd, p)
            p += 4
        if base is None:
            base = moof_off if (flags & 0x20000 or prev_end is None) else prev_end
        ptr = base
        for body in runs:
            rflags = _u32(body, 0) & 0xFFFFFF
            count = _u32(body, 4)
            q = 8
            if rflags & 0x1:
                ptr = base + int.from_bytes(body[q:q + 4], "big", signed=True)
                q += 4
            if rflags & 0x4:
                q += 4
            per = sum(4 for bit in (0x100, 0x200, 0x400, 0x800) if rflags & bit)
            for i in range(count):
                e = q + i * per
                if e + per > len(body):
                    return None
                k = e + (4 if rflags & 0x100 else 0)
                size = _u32(body, k) if rflags & 0x200 else default_size
                if size is None:
                    return None
                samples.append((ptr, size))
                ptr += size
        prev_end = ptr
    return samples


def fmp4_safe_end(path):
    boxes, size = scan_boxes(path)
    if not boxes or boxes[-1][3]:
        return None
    typ, off, n, _ = boxes[-1]
    if typ != "mdat":
        return off
    try:
        with open(path, "rb") as f:
            moofs = [b for b in boxes[:-1] if b[0] == "moof" and b[3]]
            if not moofs:
                return None
            samples = _moof_samples(f, moofs[-1][1], moofs[-1][2], _trex_sizes(f, boxes))
    except (OSError, ValueError, IndexError):
        return None
    if not samples:
        return None
    broken = [o for o, sz in samples if o + sz > size]
    if not broken:
        return None
    return min(broken)


def _ebml_vint(f, is_id):
    b = f.read(1)
    if not b:
        return None, 0
    first = b[0]
    length = 1
    mask = 0x80
    while length <= 8 and not first & mask:
        mask >>= 1
        length += 1
    if length > 8:
        return None, 0
    rest = f.read(length - 1)
    if len(rest) < length - 1:
        return None, 0
    raw = bytes([first]) + rest
    if is_id:
        return int.from_bytes(raw, "big"), length
    val = (first & (mask - 1)).to_bytes(1, "big") + rest
    v = int.from_bytes(val, "big")
    if v == (1 << (7 * length)) - 1:
        return -1, length
    return v, length


def mkv_end_state(path, max_elements=2_000_000):
    size = os.path.getsize(path)
    try:
        with open(path, "rb") as f:
            eid, _ = _ebml_vint(f, True)
            if eid != 0x1A45DFA3:
                return "unknown"
            n, _ = _ebml_vint(f, False)
            if n is None or n < 0:
                return "unknown"
            f.seek(n, 1)
            eid, _ = _ebml_vint(f, True)
            if eid != 0x18538067:
                return "truncated" if eid is None else "unknown"
            seg_size, _ = _ebml_vint(f, False)
            if seg_size is None:
                return "truncated"
            start = f.tell()
            if seg_size >= 0:
                return "truncated" if start + seg_size > size else "complete"
            pos = start
            count = 0
            while pos < size and count < max_elements:
                f.seek(pos)
                eid, _ = _ebml_vint(f, True)
                n, _ = _ebml_vint(f, False)
                if eid is None or n is None or n < 0:
                    return "truncated"
                pos = f.tell() + n
                count += 1
            if pos > size:
                return "truncated"
            return "unfinalized" if pos == size else "unknown"
    except OSError:
        return "unknown"


def _box_hdr(path, off):
    with open(path, "rb") as f:
        f.seek(off)
        return 16 if int.from_bytes(f.read(4), "big") == 1 else 8


def sniff_magic(path):
    with open(path, "rb") as f:
        head = f.read(188 * 3 + 1)
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "mkv"
    if head[:3] == b"FLV":
        return "flv"
    if ts_packet_size(head):
        return "ts"
    return ""


def ts_packet_size(head):
    for size, off in ((188, 0), (192, 4)):
        if len(head) > 2 * size + off and all(head[off + k * size] == 0x47 for k in range(3)):
            return size
    return 0


def ts_end_state(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(192 * 3 + 5)
        pkt = ts_packet_size(head)
        if not pkt:
            return "unknown", 0
        if size % pkt:
            return "truncated", pkt
        f.seek(size - 188)
        if f.read(1) != b"\x47":
            return "truncated", pkt
    return "complete", pkt


def ts_safe_end(path, pkt, pids, max_scan=64 * 1024 ** 2):
    size = os.path.getsize(path)
    end = size - size % pkt
    off = pkt - 188
    pos = end
    chunk_pkts = 4096
    with open(path, "rb") as f:
        while pos > 0 and end - pos < max_scan:
            start = max(0, pos - chunk_pkts * pkt)
            f.seek(start)
            buf = f.read(pos - start)
            for k in range((len(buf) // pkt) - 1, -1, -1):
                p = k * pkt + off
                if buf[p] != 0x47:
                    return None
                pid = ((buf[p + 1] & 0x1F) << 8) | buf[p + 2]
                if pid in pids and buf[p + 1] & 0x40:
                    cut = start + k * pkt
                    return cut if cut > 0 else None
            pos = start
    return None


def flv_end_state(path):
    size = os.path.getsize(path)
    try:
        with open(path, "rb") as f:
            head = f.read(9)
            if head[:3] != b"FLV" or len(head) < 9:
                return "unknown"
            first = int.from_bytes(head[5:9], "big") + 4
            if size < first:
                return "truncated"
            if size == first:
                return "complete"
            f.seek(size - 4)
            prev = int.from_bytes(f.read(4), "big")
            start = size - 4 - prev
            if prev < 11 or start < first:
                return "truncated"
            f.seek(start)
            tag = f.read(11)
            if (tag[0] & 0x1F) in (8, 9, 18) and int.from_bytes(tag[1:4], "big") == prev - 11:
                return "complete"
            return "truncated"
    except OSError:
        return "unknown"


PLAIN_MP4_TEXT = "已经是普通 MP4，无需转换"


def classify(path):
    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    if ".partial" in name.lower():
        return "skip", "这是未完成的临时文件，已跳过"
    if ext in MKV_EXTS:
        return "mkv", ""
    if ext in TS_EXTS or ext in FLV_EXTS:
        try:
            magic = sniff_magic(path)
        except OSError as e:
            return "skip", "无法读取文件（可能被其他程序占用，或没有权限）：" + (e.strerror or type(e).__name__)
        own = "ts" if ext in TS_EXTS else "flv"
        if magic == "mkv":
            return "mkv", "这个文件其实是 MKV（扩展名被改成了 " + ext + "），已按 MKV 转换"
        if magic in ("ts", "flv") and magic != own:
            return magic, f"这个文件其实是 {magic.upper()} 格式（扩展名是 {ext}），已按 {magic.upper()} 转换"
        if magic != own:
            return "skip", (f"不是 {own.upper()} 视频（文件开头没有 {own.upper()} 的标记，可能是扩展名相同的其他文件，"
                            "例如 TypeScript 代码），已跳过")
        return own, ""
    if ext in MP4_EXTS:
        try:
            magic = sniff_magic(path)
            if magic == "mkv":
                return "mkv", "这个文件其实是 MKV（扩展名被改成了 " + ext + "），已按 MKV 转换"
            if magic in ("ts", "flv"):
                return magic, f"这个文件其实是 {magic.upper()} 格式（扩展名被改成了 {ext}），已按 {magic.upper()} 转换"
            info = mp4_layout(path)
        except OSError as e:
            return "skip", "无法读取文件（可能被其他程序占用，或没有权限）：" + (e.strerror or type(e).__name__)
        if not info["valid"]:
            return "skip", "不是有效的 MP4/MOV 文件，已跳过"
        types = info["boxes"]
        if info["fragmented"]:
            return "fmp4", ""
        if not info["has_moov"]:
            if info["truncated"] and "moof" in types:
                return "fmp4", ""
            return "skip", ("这是录制中断的普通 MP4（缺少索引 moov，常见于 OBS 用“MP4”格式录制时崩溃或断电），"
                            "本工具无法恢复，已跳过。以后建议用 MKV 或“混合 MP4”格式录制")
        if info["truncated"]:
            if info.get("hybrid_unfinished"):
                return "skip", ("这是“混合 MP4”录制在最后收尾（写索引）时中断的文件，本工具暂时无法恢复，已跳过。"
                                "请保留源文件，可以用 OBS 的“重新封装录像”或专业修复工具尝试")
            return "skip", "这是普通 MP4，但文件末尾不完整，本工具只能修复分片式 MP4，已跳过"
        return "plain", PLAIN_MP4_TEXT
    return "skip", "不支持的文件类型（支持 MKV、WebM、FLV、TS 和分片式 MP4/MOV），已跳过"


def collect_inputs(paths, recursive=False):
    found = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            if recursive:
                for root, dirs, files in os.walk(p):
                    dirs[:] = [d for d in dirs if not d.endswith(("_fonts", "_附件", AUDIO_DIR_SUFFIX))]
                    for fn in sorted(files):
                        if os.path.splitext(fn)[1].lower() in ALL_EXTS:
                            found.append(os.path.join(root, fn))
            else:
                for fn in sorted(os.listdir(p)):
                    fp = os.path.join(p, fn)
                    if os.path.isfile(fp) and os.path.splitext(fn)[1].lower() in ALL_EXTS:
                        found.append(fp)
        else:
            found.append(p)
    seen = set()
    out = []
    for f in found:
        key = os.path.normcase(f)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def normalize_lang(lang):
    if not lang:
        return "und", None
    raw = lang.strip()
    low = raw.lower()
    if re.fullmatch(r"[a-z]{3}", low):
        return low, None
    primary = re.split(r"[-_]", low)[0]
    if re.fullmatch(r"[a-z]{3}", primary):
        return primary, raw
    if primary in LANG_MAP:
        return LANG_MAP[primary], raw
    return "und", raw


def safe_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s or "").strip(" .")
    return s or "file"


def _tags(s):
    return {k.lower(): v for k, v in (s.get("tags") or {}).items()}


def _disp(s):
    d = s.get("disposition") or {}
    return [k for k in DISPOSITIONS if d.get(k) == 1]


def _is_attached_pic(s):
    return (s.get("disposition") or {}).get("attached_pic") == 1


def _is_chapter_track(s, n_chapters):
    t = _tags(s)
    return (s.get("codec_type") == "data" and s.get("codec_tag_string") == "text"
            and (n_chapters > 0 or t.get("handler_name") == "SubtitleHandler"))


def describe_stream(s):
    t = _tags(s)
    kind = {"video": "视频", "audio": "音轨", "subtitle": "字幕", "attachment": "附件", "data": "数据"}.get(
        s.get("codec_type"), s.get("codec_type") or "?")
    parts = [f"#{s['index']} {kind} {s.get('codec_name') or s.get('codec_tag_string') or '?'}"]
    if s.get("codec_type") == "audio" and s.get("channels"):
        parts.append(f"{s['channels']}声道")
    if t.get("language") and t.get("language") != "und":
        parts.append(f"语言={t['language']}")
    if t.get("title"):
        parts.append(f"「{t['title']}」")
    elif t.get("handler_name") and t.get("handler_name") not in ("VideoHandler", "SoundHandler", "SubtitleHandler"):
        parts.append(f"「{t['handler_name']}」")
    if t.get("filename"):
        parts.append(f"文件名={t['filename']}")
    return " ".join(parts)


def _stream_title(s):
    t = _tags(s)
    title = t.get("title")
    if not title:
        h = t.get("handler_name")
        if h and h not in ("VideoHandler", "SoundHandler", "SubtitleHandler", "TimeCodeHandler"):
            title = h
    return title or ""


def _companion_codec(codec):
    if codec in COMPANION_LOSSY:
        return "aac"
    if codec in COMPANION_LOSSLESS or codec.startswith("pcm_"):
        return "flac"
    return None


def _aac_bitrate(channels):
    return f"{min(640, max(320, 64 * (channels or 2)))}k"


def _layout_fix(s):
    layout = s.get("channel_layout") or ""
    ch = s.get("channels")
    if ch and (not layout or layout == "unknown"):
        return ["-ac", str(ch)]
    return []


def _cover_like(s):
    t = _tags(s)
    name = (t.get("filename") or t.get("title") or t.get("comment") or "").lower()
    return any(w in name for w in COVER_WORDS)


HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


def _is_high_depth(s):
    pf = s.get("pix_fmt") or ""
    depth = s.get("bits_per_raw_sample")
    try:
        depth = int(depth)
    except (TypeError, ValueError):
        depth = 0
    return (depth > 8 or bool(re.search(r"(p1[0-6]|p010|p016|1[0-6]le|1[0-6]be)", pf))
            or (s.get("color_transfer") or "") in HDR_TRANSFERS)


def _color_args(s):
    out = []
    for key, opt in (("color_primaries", "-color_primaries"), ("color_transfer", "-color_trc"),
                     ("color_space", "-colorspace")):
        v = s.get(key)
        if v and v not in ("unknown", "reserved"):
            out += [opt, v]
    return out


def build_plan(info, kind, opts, src_ext):
    plan = Plan()
    streams = info["streams"]
    n_chap = len(info["chapters"])
    sidecars_on = opts.sidecars

    if kind == "fmp4" and src_ext == ".mov":
        for s in streams:
            c = s.get("codec_name") or ""
            ct = s.get("codec_type")
            if (ct == "video" and not _is_attached_pic(s) and c not in VIDEO_COPY) or \
               (ct == "audio" and c not in AUDIO_COPY):
                plan.container = "mov"
                plan.lines.append(f"源文件含 MP4 装不下的编码（{c}），输出为普通 MOV，同样不重新编码")
                break

    def add(src, kind_, codec_args, expect, lang, title, disp, role, hash_check=False):
        plan.streams.append(OutStream(src, kind_, codec_args, expect, lang, title, disp, role, hash_check))
        return len(plan.streams) - 1

    def sidecar(s, ext, args, what):
        lang = normalize_lang(_tags(s).get("language"))[0]
        plan.sidecars.append(Sidecar(s["index"], f".{s['index']}.{lang}{ext}", args, what))

    covers = [s for s in streams if s.get("codec_type") == "video" and _is_attached_pic(s)]
    cover_ids = {s["index"] for s in covers if _cover_like(s) or kind == "fmp4"}

    for s in streams:
        idx = s["index"]
        ct = s.get("codec_type")
        codec = s.get("codec_name") or ""
        t = _tags(s)
        lang, orig_lang = normalize_lang(t.get("language"))
        title = _stream_title(s)
        disp = _disp(s)
        desc = describe_stream(s)
        if orig_lang:
            plan.lines.append(f"{desc}：语言代码 {orig_lang} 在 MP4 里写成 {lang}")
            plan.metadata_sidecar = True
        extra_tags = [k for k in t if k not in IGNORED_STREAM_TAGS and not k.startswith("_statistics")]
        if extra_tags and kind == "mkv":
            plan.metadata_sidecar = True

        if ct == "video" and _is_attached_pic(s):
            ext = ".png" if codec == "png" else ".jpg"
            fname = safe_name(t.get("filename") or f"cover_{idx}{ext}")
            if idx in cover_ids:
                add(idx, "v", ["copy"], codec, lang, "", ["attached_pic"], "cover")
                plan.lines.append(f"{desc} → 嵌入为 MP4 封面")
            if kind == "mkv":
                if sidecars_on:
                    plan.dumps.append(("cover", idx, fname))
                    plan.lines.append(f"{desc} → 原图另存到附件文件夹")
                elif idx not in cover_ids:
                    plan.warnings.append(f"{desc}：MP4 只能放封面图，此图片没有保存（已关闭“另存到旁边”）")
            continue

        if ct == "video":
            if codec in VIDEO_COPY or (kind == "fmp4" and plan.container == "mov"):
                args = ["copy"]
                if codec == "hevc" and kind != "fmp4":
                    args += ["-tag", "hvc1"]
                add(idx, "v", args, codec, lang, title, disp, "copy", True)
                plan.lines.append(f"{desc} → 原样保留（不重新编码）" + ("，标记为 hvc1 以兼容苹果设备" if "-tag" in args else ""))
                if (s.get("side_data_list") and any("DOVI" in (sd.get("side_data_type") or "") for sd in s["side_data_list"])):
                    plan.lines.append(f"{desc}：含杜比视界信息，已原样复制，转换后会检查是否保留")
            else:
                if kind == "fmp4":
                    sidecar(s, ".mov", ["-c", "copy", "-f", "mov"], "MP4 装不下的视频，原样另存")
                    plan.warnings.append(f"{desc}：MP4 装不下这种视频编码，已原样另存为 .mov 旁车文件")
                    continue
                if _is_high_depth(s):
                    vargs = ["libx265", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p10le", "-tag", "hvc1"]
                    vargs += _color_args(s)
                    add(idx, "v", vargs, "hevc", lang, title, disp, "encoded")
                    plan.warnings.append(f"{desc} → MP4 装不下 {codec}，已重新编码为 10 位 H.265（CRF 18，保留 HDR/10 位色深，"
                                         "画质接近原片，但不是原始数据）")
                else:
                    add(idx, "v", ["libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p"] + _color_args(s),
                        "h264", lang, title, disp, "encoded")
                    plan.warnings.append(f"{desc} → MP4 装不下 {codec}，已重新编码为 H.264（CRF 16，画质接近原片，但不是原始数据）")
                if sidecars_on:
                    sidecar(s, ".mkv", ["-c", "copy", "-f", "matroska"], "原始视频流")
                    plan.lines.append(f"{desc} → 原始视频流另存为 .mkv 旁车文件")
            continue

        if ct == "audio":
            if codec in AUDIO_COPY or (kind == "fmp4" and plan.container == "mov"):
                add(idx, "a", ["copy"], "mp3" if codec == "mp2" else codec, lang, title, disp, "copy", True)
                if codec in AUDIO_NEEDS_STRICT:
                    plan.strict = True
                plan.lines.append(f"{desc} → 原样保留（不重新编码）")
                comp = _companion_codec(codec)
                if comp and kind != "fmp4":
                    if opts.companion:
                        ctitle = f"{title or ('音轨' + str(idx))} (兼容)"
                        cargs = ["aac", "-b", _aac_bitrate(s.get("channels"))] if comp == "aac" else ["flac"]
                        cargs += _layout_fix(s)
                        add(idx, "a", cargs, comp, lang, ctitle, [], "companion")
                        plan.companions += 1
                        plan.lines.append(f"{desc} → 另加一条 {comp.upper()} 兼容音轨「{ctitle}」（原音轨仍保留）")
                    else:
                        plan.warnings.append(f"{desc}：{codec} 在部分播放器/剪辑软件里没有声音（已关闭兼容音轨）")
                if codec in ("ac3", "eac3"):
                    plan.lines.append(f"{desc}：注意 Windows 11 24H2 全新安装的“媒体播放器”可能不带杜比解码")
            else:
                target = "flac" if codec in AUDIO_LOSSLESS or codec.startswith("pcm_") else "aac"
                cargs = ["flac"] if target == "flac" else ["aac", "-b", _aac_bitrate(s.get("channels"))]
                cargs += _layout_fix(s)
                add(idx, "a", cargs, target, lang, title, disp, "encoded")
                plan.warnings.append(f"{desc} → MP4 装不下 {codec}，已转换为 {target.upper()}")
                if sidecars_on:
                    sidecar(s, ".mka", ["-c", "copy", "-f", "matroska"], "原始音轨")
                    plan.lines.append(f"{desc} → 原始音轨另存为 .mka 旁车文件")
            continue

        if ct == "subtitle":
            if codec == "mov_text":
                add(idx, "s", ["copy"], "mov_text", lang, title, disp, "copy")
                plan.lines.append(f"{desc} → 原样保留")
            elif codec in TEXT_SUBS:
                add(idx, "s", ["mov_text"], "mov_text", lang, title, disp, "converted")
                plan.lines.append(f"{desc} → 转为 MP4 文字字幕（mov_text）")
                if sidecars_on:
                    ext = TEXT_SUBS[codec]
                    args = ["-c", "copy"] if codec in ("subrip", "ass", "ssa", "webvtt") else ["-c", "srt"]
                    sidecar(s, ext, args, "原始字幕")
                    plan.lines.append(f"{desc} → 原始字幕另存为 {ext}" + ("（保留特效样式）" if codec in ("ass", "ssa") else ""))
                elif codec in ("ass", "ssa"):
                    plan.warnings.append(f"{desc}：ASS 特效样式在 MP4 里会丢失（已关闭“另存到旁边”）")
            elif codec == "dvd_subtitle":
                add(idx, "s", ["copy"], "dvd_subtitle", lang, title, disp, "copy")
                plan.lines.append(f"{desc} → 原样放进 MP4（多数非 FFmpeg 播放器不显示）")
                if sidecars_on:
                    sidecar(s, ".mks", ["-c", "copy", "-f", "matroska"], "原始图形字幕")
                    plan.lines.append(f"{desc} → 另存为 .mks 字幕文件")
            elif codec == "hdmv_pgs_subtitle":
                if sidecars_on:
                    sidecar(s, ".sup", ["-c", "copy"], "PGS 图形字幕")
                    plan.lines.append(f"{desc} → MP4 装不下 PGS 图形字幕，另存为 .sup")
                else:
                    plan.warnings.append(f"{desc}：MP4 装不下 PGS 图形字幕，且已关闭“另存到旁边”，此字幕未保存")
            else:
                if sidecars_on:
                    sidecar(s, ".mks", ["-c", "copy", "-f", "matroska"], "字幕")
                    plan.lines.append(f"{desc} → MP4 装不下，原样另存为 .mks")
                else:
                    plan.warnings.append(f"{desc}：MP4 装不下，且已关闭“另存到旁边”，未保存")
            continue

        if ct == "attachment":
            fname = safe_name(t.get("filename") or f"attachment_{idx}")
            mime = (t.get("mimetype") or "").lower()
            is_font = os.path.splitext(fname)[1].lower() in FONT_EXTS or "font" in mime
            if sidecars_on:
                plan.dumps.append(("font" if is_font else "other", idx, fname))
                plan.lines.append(f"{desc} → MP4 装不下附件，另存到{'字体' if is_font else '附件'}文件夹")
            else:
                plan.warnings.append(f"{desc}：附件未保存（已关闭“另存到旁边”）")
            continue

        if ct == "data":
            if _is_chapter_track(s, n_chap):
                plan.lines.append(f"{desc} → 章节数据，按章节重新写入")
                continue
            if s.get("codec_tag_string") == "tmcd":
                plan.write_tmcd = True
                plan.lines.append(f"{desc} → 时间码，重新写入时间码轨")
                continue
            if kind in ("ts", "flv"):
                plan.lines.append(f"{desc} → {kind.upper()} 里的附加数据（不是画面、声音或字幕），MP4 用不上，已忽略")
                continue
            if sidecars_on:
                ext = ".mov" if kind == "fmp4" else ".mks"
                fmt = "mov" if kind == "fmp4" else "matroska"
                sidecar(s, ext, ["-c", "copy", "-f", fmt], "数据流")
                plan.lines.append(f"{desc} → 数据流，原样另存为 {ext}")
            else:
                plan.warnings.append(f"{desc}：数据流未保存（已关闭“另存到旁边”）")
            continue

        plan.warnings.append(f"{desc}：未知类型，未处理")

    if not any(o.kind in ("v", "a") for o in plan.streams):
        if not any(o.kind == "s" for o in plan.streams):
            raise ConvertError("源文件里没有可以放进 MP4 的音视频轨道")

    custom = [k for k in _tags(info["format"]) if k not in STANDARD_GLOBAL_TAGS and k not in IGNORED_GLOBAL_TAGS]
    if custom:
        plan.metadata_sidecar = True
        plan.lines.append(f"自定义标签 {', '.join(custom[:6])}{'…' if len(custom) > 6 else ''} MP4 存不下，已记录到 .metadata.txt")
    if not sidecars_on:
        plan.metadata_sidecar = False
    return plan


def _ffmeta_escape(v):
    return re.sub(r"([=;#\\\n])", r"\\\1", str(v))


def ffmetadata_text(info):
    lines = [";FFMETADATA1"]
    for k, v in (info["format"].get("tags") or {}).items():
        lines.append(f"{_ffmeta_escape(k)}={_ffmeta_escape(v)}")
    for ch in info["chapters"]:
        lines.append("[CHAPTER]")
        lines.append(f"TIMEBASE={ch.get('time_base', '1/1000')}")
        lines.append(f"START={ch.get('start', 0)}")
        lines.append(f"END={ch.get('end', 0)}")
        for k, v in (ch.get("tags") or {}).items():
            lines.append(f"{_ffmeta_escape(k)}={_ffmeta_escape(v)}")
    return "\n".join(lines) + "\n"


def _exists_any(paths):
    return any(os.path.lexists(p) for p in paths)


def choose_output(src, kind, opts, container):
    folder = opts.out_dir or os.path.dirname(src)
    stem = os.path.splitext(os.path.basename(src))[0]
    if kind == "fmp4":
        stem += "_标准MOV" if container == "mov" else "_标准MP4"
    ext = ".mov" if container == "mov" else ".mp4"
    n = 0
    while True:
        cand = stem if n == 0 else f"{stem} ({n})"
        base = os.path.join(folder, cand)
        related = [base + ext, base + ".转换报告.txt", base + "_fonts", base + "_附件", base + ".metadata.txt",
                   base + ".源文件信息.json", base + AUDIO_DIR_SUFFIX]
        if not _exists_any(related) and not _has_own_sidecars(folder, cand):
            return folder, cand, ext
        n += 1


def _has_own_sidecars(folder, cand):
    pat = re.compile(re.escape(cand) + r"\.\d+\.[a-z]{3}(\.partial(-\d+)?)?\.[A-Za-z0-9]+$", re.IGNORECASE)
    try:
        return any(pat.match(fn) for fn in os.listdir(folder))
    except OSError:
        return False


def _write_new(path, write, mode="x", **kw):
    root, ext = os.path.splitext(path)
    n = 1
    while True:
        try:
            with open(path, mode, **kw) as f:
                write(f)
            return path
        except FileExistsError:
            path = f"{root} ({n}){ext}"
            n += 1


def _unique_partial(path):
    root, ext = os.path.splitext(path)
    cand = f"{root}.partial{ext}"
    n = 2
    while os.path.lexists(cand):
        cand = f"{root}.partial-{n}{ext}"
        n += 1
    return cand


def free_space(folder):
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None


def filesystem_name(folder):
    if os.name != "nt":
        return ""
    try:
        import ctypes
        root = os.path.splitdrive(os.path.abspath(folder))[0] + "\\"
        buf = ctypes.create_unicode_buffer(64)
        if ctypes.windll.kernel32.GetVolumeInformationW(root, None, 0, None, None, None, buf, 64):
            return buf.value
    except Exception:
        pass
    return ""


def same_file(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class FFmpegRunner:
    def __init__(self, cancel_event=None):
        self.cancel_event = cancel_event or threading.Event()
        self.proc = None
        self.first_issue_at = None

    def cancelled(self):
        return self.cancel_event.is_set()

    def run(self, args, duration=None, total_bytes=None, on_progress=None):
        cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "warning", "-progress", "pipe:1", "-nostats",
               "-stats_period", "0.5"] + args
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                     encoding="utf-8", errors="replace", **_popen_kwargs())
        err_lines = []
        cur = {}
        self.first_issue_at = None

        def read_err():
            for line in self.proc.stderr:
                err_lines.append(line.rstrip())
                if self.first_issue_at is None and any(p in line for p in TRUNC_PATTERNS):
                    try:
                        self.first_issue_at = int(cur.get("out_time_us", "")) / 1e6
                    except ValueError:
                        pass
                if len(err_lines) > 400:
                    del err_lines[:200]

        t = threading.Thread(target=read_err, daemon=True)
        t.start()
        killed = False
        for line in self.proc.stdout:
            if self.cancelled() and not killed:
                self._kill()
                killed = True
            line = line.strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            cur[k] = v
            if k == "progress" and on_progress:
                frac = None
                try:
                    us = int(cur.get("out_time_us", "0"))
                    if duration and duration > 0 and us > 0:
                        frac = us / 1e6 / duration
                except ValueError:
                    pass
                if frac is None and total_bytes:
                    try:
                        frac = int(cur.get("total_size", "0")) / total_bytes
                    except ValueError:
                        pass
                on_progress(1.0 if v == "end" else min(max(frac or 0.0, 0.0), 1.0), v == "end")
        self.proc.wait()
        t.join(timeout=5)
        rc = self.proc.returncode
        self.proc = None
        if self.cancelled():
            raise Cancelled()
        return rc, err_lines

    def _kill(self):
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def cancel(self):
        self.cancel_event.set()
        self._kill()


TRUNC_PATTERNS = ("File ended prematurely", "exceeds containing master element", "Truncat", "End of file",
                  "partial file", "Invalid NAL unit size", "error reading header", "stream 0, offset",
                  "moov atom not found", "Packet corrupt", "EBML header parsing failed", "I/O error")


def _err_summary(lines, n=6):
    useful = [l for l in lines if l and not l.startswith("  ") and "Last message repeated" not in l]
    return "\n".join(useful[-n:])


FFMPEG_ERROR_TEXT = (
    (("Permission denied", "Access is denied"), "输出位置没有写入权限（或文件被其他程序占用），请换一个输出文件夹"),
    (("No space left", "There is not enough space"), "磁盘空间不够，请清理磁盘或换一个输出文件夹"),
    (("Decode error rate", "error while decoding", "Error while decoding", "unpack_block", "Invalid data found when processing input"),
     "源文件里的画面或声音数据已损坏，无法重新编码"),
    (("Error initializing output stream", "Error while opening encoder", "Could not open encoder"),
     "无法为这个文件创建编码器（源文件格式参数异常）"),
    (("does not support", "Could not find tag for codec", "codec not currently supported in container"),
     "这种编码放不进 MP4"),
)


def _stream_bytes(s, dur, fallback):
    t = _tags(s)
    for key in ("number_of_bytes", "number_of_bytes-eng"):
        try:
            return int(t[key])
        except (KeyError, ValueError):
            pass
    br = s.get("bit_rate") or t.get("bps") or t.get("bps-eng")
    try:
        if br and dur:
            return int(int(br) * dur / 8)
    except ValueError:
        pass
    return fallback


def estimate_extra_bytes(info, plan, src_size, dur):
    by_index = {s["index"]: s for s in info["streams"]}
    total = 0
    for sc in plan.sidecars:
        s = by_index.get(sc.src)
        if s is not None:
            total += _stream_bytes(s, dur, src_size if s.get("codec_type") in ("video", "audio") else 0)
    for o in plan.streams:
        if o.role == "encoded" and o.kind == "v":
            total += src_size
    return total


def explain_ffmpeg(lines):
    text = "\n".join(lines)
    for pats, msg in FFMPEG_ERROR_TEXT:
        if any(p in text for p in pats):
            return msg
    return "转换过程中出错"


def _explain_os_error(e):
    if isinstance(e, PermissionError):
        return "没有权限写入输出位置（或文件被其他程序占用），请换一个输出文件夹"
    if getattr(e, "winerror", None) == 112 or getattr(e, "errno", None) == 28:
        return "磁盘空间不够，请清理磁盘或换一个输出文件夹"
    return "读写文件时出错，没有生成文件（源文件没有改动）"


def check_writable(folder):
    probe_path = os.path.join(folder, f".mkv2mp4_write_test_{os.getpid()}_{threading.get_ident()}.tmp")
    try:
        with open(probe_path, "x") as f:
            f.write("x")
    except OSError as e:
        return f"{type(e).__name__}: {e}"
    try:
        os.remove(probe_path)
    except OSError:
        pass
    return None


def build_command(src, plan, partial_main, opts, attach_dirs, include_extras=True, include_companions=True):
    args = []
    if include_extras:
        for kind_, idx, fname in plan.dumps:
            if kind_ in ("font", "other"):
                d = attach_dirs["font" if kind_ == "font" else "other"]
                args += [f"-dump_attachment:{idx}", os.path.join(d, fname)]
    args += ["-n"] + plan.input_flags + ["-i", src]
    out_i = 0
    for o in plan.streams:
        if o.role == "companion" and not include_companions:
            continue
        args += ["-map", f"0:{o.src}"]
        ca = o.codec_args
        args += [f"-c:{out_i}", ca[0]]
        rest = ca[1:]
        while rest:
            opt, val = rest[0], rest[1]
            args += [f"{opt}:{out_i}", val]
            rest = rest[2:]
        if o.title:
            args += [f"-metadata:s:{out_i}", f"handler_name={o.title}", f"-metadata:s:{out_i}", f"title={o.title}"]
        args += [f"-metadata:s:{out_i}", f"language={o.lang}"]
        args += [f"-disposition:{out_i}", "+".join(o.disposition) if o.disposition else "0"]
        out_i += 1
    args += ["-map_metadata", "0", "-map_chapters", "0", "-max_muxing_queue_size", "9999"]
    if plan.strict:
        args += ["-strict", "experimental"]
    if plan.write_tmcd:
        args += ["-write_tmcd", "1"]
    if opts.faststart:
        args += ["-movflags", "+faststart"]
    args += ["-f", plan.container, partial_main]
    if include_extras:
        for sc in plan.sidecars:
            args += ["-map", f"0:{sc.src}"] + sc.args + [sc.partial]
        for kind_, idx, fname in plan.dumps:
            if kind_ == "cover":
                args += ["-map", f"0:{idx}", "-c", "copy", "-frames:v", "1", "-update", "1", "-f", "image2",
                         os.path.join(attach_dirs["other"], fname)]
    return args


def stream_hashes(path, indices, limit=None, bsfs=None, in_flags=()):
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error"] + list(in_flags) + ["-i", path]
    for i in indices:
        cmd += ["-map", f"0:{i}"]
    cmd += ["-c", "copy"]
    for k, b in enumerate(bsfs or []):
        if b:
            cmd += [f"-bsf:{k}", b]
    if limit:
        cmd += ["-frames", str(limit)]
    cmd += ["-f", "streamhash", "-hash", "md5", "-"]
    r = run_quiet(cmd)
    out = []
    for line in r.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) == 3:
            out.append(parts[2])
    return out, r.returncode


HDR_SIDE_DATA = {"Mastering display metadata": "母版显示信息", "Content light level metadata": "亮度信息",
                 "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)": "HDR10+", "Dolby Vision RPU Data": "杜比视界 RPU",
                 "Dolby Vision Metadata": "杜比视界"}


def hdr_side_data(path, index):
    r = run_quiet([find_tool("ffprobe"), "-v", "error", "-select_streams", str(index), "-read_intervals", "%+#1",
                   "-show_frames", "-show_entries", "frame_side_data=side_data_type", "-of", "json", path])
    found = set()
    try:
        for fr in json.loads(r.stdout or "{}").get("frames", []):
            for sd in fr.get("side_data_list", []) or []:
                name = sd.get("side_data_type", "")
                if name in HDR_SIDE_DATA:
                    found.add(HDR_SIDE_DATA[name])
    except ValueError:
        pass
    return found


def first_pts(path, index, in_flags=()):
    r = run_quiet([find_tool("ffprobe"), "-v", "error"] + list(in_flags) + ["-select_streams", str(index),
                   "-show_entries", "packet=pts_time", "-read_intervals", "%+#1", "-of", "csv=p=0", path])
    for line in r.stdout.splitlines():
        v = line.strip().strip(",")
        if v:
            try:
                return float(v)
            except ValueError:
                return None
    return None


def packet_md5s(path, index, limit=None, bsf=None, in_flags=()):
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error"] + list(in_flags) + ["-i", path, "-map", f"0:{index}",
                                                                                           "-c", "copy"]
    if bsf:
        cmd += ["-bsf:0", bsf]
    if limit:
        cmd += ["-frames", str(limit)]
    cmd += ["-f", "framemd5", "-"]
    r = run_quiet(cmd)
    out = []
    for line in r.stdout.splitlines():
        if line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6:
            out.append((parts[4], parts[5]))
    return out


def hash_filters(kind, codec):
    if kind in ("ts", "flv") and codec == "av1":
        return AV1_STRIP, AV1_STRIP
    if kind != "ts":
        return None, None
    if codec in ANNEXB_STRIP:
        f = "filter_units=remove_types=" + ANNEXB_STRIP[codec]
        return f, f"{codec}_mp4toannexb,{f}"
    if codec == "aac":
        return "aac_adtstoasc", None
    return None, None


def _nal_set(data):
    return {n.rstrip(b"\x00") for n in re.split(b"\x00\x00\x01", data) if n.rstrip(b"\x00")}


def first_param_sets(path, index, codec, annexb_from_mp4):
    f = "filter_units=pass_types=" + ANNEXB_PS[codec]
    bsf = f"{codec}_mp4toannexb,{f}" if annexb_from_mp4 else f
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-i", path, "-map", f"0:{index}", "-c", "copy",
           "-bsf:0", bsf, "-frames", "1", "-f", "data", "-"]
    cancel = _current_cancel()
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=120, **_popen_kwargs())
    return _nal_set(r.stdout)


STATS_TIME = re.compile(r"\btime=(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def decode_check(path, start, length):
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-stats", "-stats_period", "0.02"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-t", str(length), "-i", path, "-map", "0:V?", "-map", "0:a?", "-f", "null", "-"]
    r = run_quiet(cmd)
    errs, at, last = [], None, None
    for l in r.stderr.splitlines():
        if "time=" in l and "speed=" in l:
            m = STATS_TIME.search(l)
            if m:
                last = start + int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
                if errs and at is None:
                    at = last
        elif l.strip():
            errs.append(l)
    if errs and at is None:
        at = last if last is not None else start
    return r.returncode, errs, at


def _fdur(d):
    try:
        v = float(d)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _out_duration(info):
    durs = []
    for s in info["streams"]:
        if s.get("codec_type") in ("video", "audio") and not _is_attached_pic(s):
            v = _fdur(s.get("duration"))
            if v:
                durs.append(v)
    return max(durs) if durs else _fdur(info["format"].get("duration"))


def _start(s):
    try:
        return float(s.get("start_time"))
    except (TypeError, ValueError):
        return None


def _frame_dur(s):
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            n, d = (s.get(key) or "0/0").split("/")
            if float(n) > 0 and float(d) > 0:
                return float(d) / float(n)
        except ValueError:
            pass
    return 1 / 30


def _main_video(streams):
    for s in streams:
        if s.get("codec_type") == "video" and not _is_attached_pic(s):
            return s
    return None


def check_sync(src_info, plan, real, result):
    sv = _main_video(src_info["streams"])
    pairs = [(o, s) for o, s in zip(plan.streams, real) if o.kind in ("v", "a") and o.role != "cover"]
    ov = next((s for o, s in pairs if o.kind == "v"), None)
    if sv is None or ov is None or _start(sv) is None or _start(ov) is None:
        return
    tol = _frame_dur(sv) + 0.002
    bad = []
    for o, s in pairs:
        a, b = _start(src_info["streams"][o.src]), _start(s)
        if a is None or b is None:
            continue
        shift = (b - _start(ov)) - (a - _start(sv))
        if abs(shift) > tol:
            bad.append(f"源 #{o.src}（{shift:+.3f} 秒）")
    if bad:
        result.warnings.append("和源文件相比，这些轨道相对画面的起始时间变了，可能音画不同步：" + "、".join(bad))
    else:
        result.lines.append("校验：各轨道相对画面的起始时间和源文件一致（音画同步，误差不超过 1 帧）")


def verify_output(src, src_info, plan, out_path, result, opts, kind, truncated, log, src_input=None, ts_jump=False):
    src_input = src_input or src
    out = probe(out_path)
    if out["_rc"] != 0 or not out["streams"]:
        result.errors.append("转换结果无法读取")
        return
    n_chap_src = len(src_info["chapters"])
    real = [s for s in out["streams"] if not (s.get("codec_type") == "data")]
    expected = plan.streams
    if len(real) != len(expected):
        result.errors.append(f"MP4 里的轨道数量不对：应为 {len(expected)}，实际 {len(real)}")
    type_name = {"v": "video", "a": "audio", "s": "subtitle"}
    first_seen = {}
    any_default = {}
    for o in expected:
        if "default" in o.disposition and o.role != "cover":
            any_default[o.kind] = True
    for i, (o, s) in enumerate(zip(expected, real)):
        t = _tags(s)
        label = f"输出第 {i + 1} 轨（来自源 #{o.src}）"
        if s.get("codec_type") != type_name[o.kind]:
            result.errors.append(f"{label} 类型不对")
            continue
        cname = s.get("codec_name")
        if o.expect_codec and cname != o.expect_codec and not (o.expect_codec == "mp3" and cname in ("mp3", "mp2")):
            result.errors.append(f"{label} 编码不对：应为 {o.expect_codec}，实际 {cname}")
        if (t.get("language") or "und") != o.lang:
            result.warnings.append(f"{label} 语言变成了 {t.get('language') or 'und'}（应为 {o.lang}）")
        if o.title and t.get("handler_name") != o.title:
            result.warnings.append(f"{label} 轨道名没写进去（应为「{o.title}」）")
        d = s.get("disposition") or {}
        if o.role == "cover":
            if d.get("attached_pic") != 1:
                result.errors.append(f"{label} 封面没有嵌入")
            continue
        is_first = o.kind not in first_seen
        first_seen[o.kind] = True
        want_def = "default" in o.disposition
        if bool(d.get("default")) != want_def:
            if not (is_first and not any_default.get(o.kind) and d.get("default") == 1):
                result.warnings.append(f"{label} 默认轨标记不一致")
        if bool(d.get("forced")) != ("forced" in o.disposition):
            result.warnings.append(f"{label} 强制字幕标记不一致")

    out_chap = len(out["chapters"])
    if out_chap != n_chap_src:
        result.warnings.append(f"章节数量不一致：源 {n_chap_src}，输出 {out_chap}")

    src_tags = _tags(src_info["format"])
    out_tags = _tags(out["format"])
    for k, v in src_tags.items():
        if k in STANDARD_GLOBAL_TAGS and out_tags.get(k) != v:
            result.warnings.append(f"全局标签 {k} 没有完整保留")

    src_dur = _fdur(src_info["format"].get("duration"))
    out_dur = _out_duration(out)
    result.recovered_until = out_dur
    if out_dur is None or out_dur < 0.05:
        result.errors.append("输出文件里没有可播放的内容")
        return
    if ts_jump:
        result.lines.append("源文件里的时间戳中途有跳变（例如几段 TS 接在了一起，或录制设备的时钟重置过），已按实际内容连续排列；"
                            f"源文件标称时长 {fmt_time(src_dur)} 不准，以输出的 {fmt_time(out_dur)} 为准")
    elif src_dur and abs(src_dur - out_dur) > 1.0:
        if truncated or out_dur < src_dur:
            if not truncated:
                result.warnings.append(f"时长比源文件短：源 {fmt_time(src_dur)}，输出 {fmt_time(out_dur)}")
        else:
            result.warnings.append(f"时长不一致：源 {fmt_time(src_dur)}，输出 {fmt_time(out_dur)}")

    lay = mp4_layout(out_path)
    if lay["fragmented"]:
        result.errors.append("输出文件仍然是分片式 MP4")
    if lay["truncated"]:
        result.errors.append("输出文件结构不完整")
    if opts.faststart and not lay["moov_first"]:
        result.warnings.append("索引（moov）没有移到文件开头")

    for o, s in zip(expected, real):
        if o.role == "copy" and o.kind == "v" and s.get("codec_name") == "hevc":
            src_s = src_info["streams"][o.src]
            had = any("DOVI" in (sd.get("side_data_type") or "") for sd in src_s.get("side_data_list") or [])
            has = any("DOVI" in (sd.get("side_data_type") or "") for sd in s.get("side_data_list") or [])
            if had and not has:
                result.warnings.append("杜比视界信息没有保留下来（画面仍是 HDR10/普通 HDR 基础层）；需要杜比视界请保留原 MKV")

    for i, (o, s) in enumerate(zip(expected, real)):
        if o.role == "copy" and o.kind == "v":
            a = hdr_side_data(src, o.src)
            if a:
                b = hdr_side_data(out_path, i)
                missing = a - b
                if missing:
                    result.warnings.append(f"源 #{o.src} 的 HDR 信息没有完整保留：缺少 {', '.join(sorted(missing))}")
                else:
                    result.lines.append(f"校验：源 #{o.src} 的 HDR 信息（{', '.join(sorted(a))}）已保留")

    if kind in ("ts", "flv"):
        check_sync(src_info, plan, real, result)

    if not opts.verify:
        return
    pairs =[(o.src, i) for i, o in enumerate(expected) if o.hash_check and i < len(real)]
    if pairs:
        total = os.path.getsize(src) + os.path.getsize(out_path)
        limit = None if total <= FULL_HASH_LIMIT else SAMPLE_PACKETS
        log("正在逐包比对原样保留的轨道…" if limit is None else f"文件很大，抽查每条轨道前 {SAMPLE_PACKETS} 个数据包…")
        filters = {p: hash_filters(kind, src_info["streams"][p[0]].get("codec_name")) for p in pairs}
        h_src, _ = stream_hashes(src_input, [p[0] for p in pairs], limit, [filters[p][0] for p in pairs], plan.input_flags)
        h_out, _ = stream_hashes(out_path, [p[1] for p in pairs], limit, [filters[p][1] for p in pairs])
        bad = [p for k, p in enumerate(pairs) if k >= len(h_src) or k >= len(h_out) or h_src[k] != h_out[k]]
        for s_idx, o_idx in bad:
            a = packet_md5s(src_input, s_idx, limit, filters[(s_idx, o_idx)][0], plan.input_flags)
            b = packet_md5s(out_path, o_idx, limit, filters[(s_idx, o_idx)][1])
            same = 0
            while same < min(len(a), len(b)) and a[same] == b[same]:
                same += 1
            if same == len(b) and len(a) - len(b) <= 2 and not truncated:
                result.warnings.append(f"源 #{s_idx}：MP4 的时间表把结尾最后 {len(a) - len(b)} 个音频包（不到 0.1 秒）标成不播放，其余数据完全一致")
            elif truncated and same >= min(len(a), len(b)) - 2:
                result.warnings.append(f"源 #{s_idx}：源文件末尾损坏，最后一小段数据无法逐包比对，前面 {same} 个数据包完全一致")
            else:
                result.errors.append(f"源 #{s_idx} 的数据与源文件不一致（第 {same + 1} 个数据包开始不同）")
        good = len(pairs) - len(bad)
        if good:
            scope = "全部数据包" if limit is None else f"前 {SAMPLE_PACKETS} 个数据包"
            result.lines.append(f"校验：{good} 条原样保留的轨道与源文件逐包一致（{scope}）")
            if any(filters[p][0] for p in pairs if p not in bad):
                result.lines.append(f"校验：{kind.upper()} 里的部分编码在 MP4 里要换一种标准的打包方式（H.264/H.265 的起始码换成长度前缀、"
                                    "AAC 去掉 ADTS 头、AV1 去掉帧分隔符），比对时先把两边统一成同一种形式，画面和声音数据本身逐字节一致")
        for s_idx, o_idx in pairs:
            codec = src_info["streams"][s_idx].get("codec_name")
            if kind == "ts" and codec in ANNEXB_PS:
                a = first_param_sets(src_input, s_idx, codec, False)
                if a and a != first_param_sets(out_path, o_idx, codec, True):
                    result.warnings.append(f"源 #{s_idx} 的视频参数集（SPS/PPS）和 MP4 里的不一致，建议打开 MP4 看一下画面")

    log("正在试解码开头和结尾…")
    problems = []
    spots = []
    rc1, e1, t1 = decode_check(out_path, 0, DECODE_WINDOW)
    start2 = max(0.0, out_dur - DECODE_WINDOW)
    rc2, e2, t2 = decode_check(out_path, start2, DECODE_WINDOW + 1) if start2 > 0 else (0, [], None)
    for rc, errs, at, where in ((rc1, e1, t1, "开头"), (rc2, e2, t2, "结尾")):
        if rc != 0 or errs:
            if errs and at is not None and all(abs(at - s) > 3 for s in spots):
                spots.append(at)
            near = f"（约 {fmt_time(at)}）" if errs and at is not None else ""
            problems.append(f"{where}{near}：" + ("; ".join(errs[:2]) if errs else f"返回码 {rc}"))
    if problems:
        where = "、".join(p.split("：", 1)[0].split("（", 1)[0] for p in problems)
        at = f"，位置约在 {'、'.join(fmt_time(s) for s in spots)}" if spots else ""
        result.warnings.append(f"试解码时{where}有少量数据解不开{at}（多半是源文件本身就有的小瑕疵，一般只是一瞬间的花屏或杂音），"
                               "建议打开 MP4 看一下对应位置；详细信息见报告末尾“技术细节”")
        result.tech_lines += ["试解码：" + p for p in problems]
    else:
        result.lines.append(f"校验：开头和结尾各 {DECODE_WINDOW} 秒试解码正常")
    result.lines.append(f"校验：轨道 {len(real)} 条、章节 {out_chap} 个、时长 {fmt_time(out_dur)}"
                        + ("，索引在文件开头" if lay["moov_first"] else ""))


AUDIO_ERR = "另存音轨："
DURATION_TAG = re.compile(r"(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def _stream_duration(s):
    v = _fdur(s.get("duration"))
    if v:
        return v
    for k, raw in _tags(s).items():
        if k.startswith("duration"):
            m = DURATION_TAG.fullmatch(str(raw).strip())
            if m:
                return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    return None


def audio_export_bytes(info, dur):
    return sum(_stream_bytes(s, dur, int((dur or 0) * 1536000 / 8))
               for s in info["streams"] if s.get("codec_type") == "audio")


def audio_export_items(info, kind=None):
    streams = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    width = len(str(len(streams)))
    sv = _main_video(info["streams"])
    first = _start(info["format"])
    starts = [_start(s) for s in streams if _start(s) is not None]
    if kind == "ts" and starts:
        first = min(starts)
    items = []
    for n, s in enumerate(streams, 1):
        codec = s.get("codec_name") or ""
        ext, fmt = AUDIO_EXPORT.get(codec, (".mka", "matroska"))
        title = _stream_title(s)
        lang = normalize_lang(_tags(s).get("language"))[0]
        clean = (title or "").strip(" .")
        label = safe_name((clean or (lang if lang != "und" else f"音轨{n}"))[:80])
        offset = None
        if sv is not None and _start(sv) is not None and _start(s) is not None:
            offset = _start(s) - _start(sv)
        lead = _start(s) - first if first is not None and _start(s) is not None else 0.0
        items.append({"stream": s, "codec": codec, "name": f"{n:0{width}d}-{label}{ext}", "fmt": fmt, "title": title,
                      "lang": lang, "offset": offset, "frame": _frame_dur(sv) if sv is not None else None,
                      "lead": max(0.0, lead), "solo_lead": 0.0 if kind == "ts" else max(0.0, lead)})
    return items


def audio_export_args(it, solo=False):
    a = ["-map", f"0:{it['stream']['index']}", "-c", "copy", "-map_metadata", "-1", "-map_chapters", "-1"]
    lead = it["solo_lead" if solo else "lead"]
    if lead > 0.0005:
        a += ["-output_ts_offset", f"{-lead:.6f}"]
    if it["title"]:
        a += ["-metadata", f"title={it['title']}", "-metadata:s:0", f"title={it['title']}",
              "-metadata:s:0", f"handler_name={it['title']}"]
    if it["lang"] != "und":
        a += ["-metadata", f"language={it['lang']}"]
    a += ["-metadata:s:0", f"language={it['lang']}"]
    if it["fmt"] == "mp3":
        a += ["-id3v2_version", "3"]
    if it["fmt"] == "wav":
        a += ["-rf64", "auto"]
    return a + ["-f", it["fmt"], it["partial"]]


def verify_audio_export(src, src_input, kind, in_flags, items, result, opts, truncated, log, check_duration=True):
    todo = []
    for it in items:
        if it.get("failed") is not None:
            continue
        p = it["partial"]
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            it["failed"] = ""
            continue
        out = probe(p)
        a = [s for s in out["streams"] if s.get("codec_type") == "audio"]
        if out["_rc"] != 0 or not a:
            result.errors.append(f"{AUDIO_ERR}{it['name']} 无法读取")
            it["bad"] = True
            continue
        if a[0].get("codec_name") != it["codec"]:
            result.errors.append(f"{AUDIO_ERR}{it['name']} 编码不对：应为 {it['codec']}，实际 {a[0].get('codec_name')}")
            it["bad"] = True
            continue
        got, src_first, start = first_pts(p, 0), first_pts(src_input, it["stream"]["index"], in_flags), _start(it["stream"])
        if got is not None and src_first is not None and start is not None and got < src_first - start - 0.002:
            result.errors.append(f"{AUDIO_ERR}{it['name']} 开头缺了约 {src_first - start - got:.3f} 秒声音")
            it["bad"] = True
            continue
        it["duration"] = _out_duration(out)
        want = _stream_duration(it["stream"])
        if check_duration and want and it["duration"] and abs(want - it["duration"]) > 1.0 and not truncated:
            result.warnings.append(f"{it['name']}：时长和源文件里的音轨不一致（源 {fmt_time(want)}，另存的 {fmt_time(it['duration'])}）")
        todo.append(it)
    if not opts.verify or not todo:
        return
    limit = None if os.path.getsize(src) <= FULL_HASH_LIMIT else SAMPLE_PACKETS
    if limit:
        todo = [it for it in todo if it["fmt"] != "wav"]
    log("正在核对另存的音轨…")
    bsfs = [hash_filters(kind, it["codec"])[0] for it in todo]
    h_src, _ = stream_hashes(src_input, [it["stream"]["index"] for it in todo], limit, bsfs, in_flags)
    good = 0
    for k, it in enumerate(todo):
        h_out, _ = stream_hashes(it["partial"], [0], limit)
        if k < len(h_src) and h_out and h_src[k] == h_out[0]:
            good += 1
            continue
        same, la, lb = 0, 0, 0
        if it["fmt"] != "wav":
            a = packet_md5s(src_input, it["stream"]["index"], limit, bsfs[k], in_flags)
            b = packet_md5s(it["partial"], 0, limit)
            la, lb = len(a), len(b)
            while same < min(la, lb) and a[same] == b[same]:
                same += 1
        if lb and same == lb and la - lb <= 2 and not truncated:
            result.warnings.append(f"{it['name']}：结尾最后 {la - lb} 个音频包（不到 0.1 秒）没有放进去，其余数据和源文件完全一致")
        elif lb and truncated and same >= min(la, lb) - 2:
            result.warnings.append(f"{it['name']}：源文件末尾损坏，最后一小段无法逐包比对，前面 {same} 个数据包完全一致")
        else:
            result.errors.append(f"{AUDIO_ERR}{it['name']} 的数据和源文件里的音轨不一致")
            it["bad"] = True
    if good:
        scope = "全部数据包" if limit is None else f"前 {SAMPLE_PACKETS} 个数据包"
        result.lines.append(f"校验：另存的 {good} 个音轨文件和源文件里的音轨数据一致（{scope}，没有重新编码）")


def choose_audio_base(src, opts):
    folder = opts.out_dir or os.path.dirname(src)
    stem = os.path.splitext(os.path.basename(src))[0]
    n = 0
    while True:
        cand = stem if n == 0 else f"{stem} ({n})"
        base = os.path.join(folder, cand)
        if not _exists_any([base + AUDIO_DIR_SUFFIX, base + ".转换报告.txt"]):
            return folder, cand
        n += 1


def hide_folders(text, paths):
    for p in paths:
        if not p:
            continue
        d = os.path.dirname(os.path.abspath(p)).rstrip("\\/")
        for v in (d + os.sep, d.replace("\\", "/") + "/", d.replace("/", "\\") + "\\"):
            if len(v) > 3:
                text = text.replace(v, "")
    return text


KIND_REPORT = {"mkv": "MKV/WebM → MP4", "fmp4": "分片式 MP4/MOV → 普通 MP4", "ts": "TS → MP4", "flv": "FLV → MP4",
               "plain": "普通 MP4/MOV（无需转换，只另存音轨）"}


def write_report(path, result, plan, src_info):
    status = {"ok": "成功", "warn": "完成，但有需要注意的地方", "failed": "失败"}.get(result.status, result.status)
    lines = [f"{APP_NAME} {VERSION} 转换报告", "=" * 40,
             f"源文件：{os.path.basename(result.src)}",
             f"输出文件：{os.path.basename(result.output) if result.output else '（没有转换，只另存音轨）'}",
             f"类型：{KIND_REPORT.get(result.kind, result.kind)}",
             f"结果：{status}", f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    if result.message:
        lines += [result.message, ""]
    lines.append("源文件内容：")
    for s in src_info["streams"]:
        lines.append("  " + describe_stream(s))
    lines.append(f"  章节 {len(src_info['chapters'])} 个")
    lines += ["", "处理方式："]
    lines += ["  " + l for l in (plan.lines if plan else [])]
    if result.extra_files:
        lines += ["", "另存到旁边的文件（播放器会自动加载同名字幕；删掉也不影响 MP4 播放）："]
        lines += ["  " + os.path.basename(p.rstrip(os.sep)) + (os.sep if p.endswith(os.sep) else "") for p in result.extra_files]
    if result.audio_files:
        lines += ["", f"另存的音轨（在“{os.path.basename(result.audio_dir)}”文件夹里，每条音轨一个文件，没有重新编码）：",
                  "  每个文件都从这条音轨的第一个声音开始。剪映等软件只认 MP4 第一条音轨时，把需要的音轨文件拖进去，"
                  "和画面开头对齐即可（如果下面“注意”里写了某条音轨比画面晚或早开始，按那里说的挪一下）。"]
        lines += ["  " + os.path.basename(p) for p in result.audio_files]
    if result.lines:
        lines += ["", "检查结果："] + ["  " + l for l in result.lines]
    if result.warnings or result.notes:
        lines += ["", "注意："] + ["  ! " + w for w in result.warnings + result.notes]
    if result.errors:
        lines += ["", "问题："] + ["  × " + e for e in result.errors]
    lines += ["", "源文件没有被修改、移动或删除。"]
    if result.tech_lines:
        lines += ["", "技术细节（给懂 ffmpeg 的人看，一般用户可以忽略）："] + ["  " + l for l in result.tech_lines]
    text = hide_folders("\n".join(lines) + "\n", [result.src, result.output, path])
    return _write_new(path, lambda f: f.write(text), encoding="utf-8-sig", newline="\r\n")


class Converter:
    def __init__(self, opts=None, log=None, progress=None, cancel_event=None):
        self.opts = opts or Options()
        self.log = log or (lambda m: None)
        self.progress = progress or (lambda frac, stage: None)
        self.runner = FFmpegRunner(cancel_event)

    def cancel(self):
        self.runner.cancel()

    def convert(self, src):
        result = FileResult(src=src)
        kind, msg = classify(src)
        result.kind = kind
        if kind == "skip" or (kind == "plain" and not self.opts.export_audio):
            result.status = "skipped"
            result.message = msg
            return result
        created = []
        _cancel_local.event = self.runner.cancel_event
        try:
            if kind == "plain":
                self._export_only(src, result, created, msg)
            else:
                self._convert(src, kind, result, created, msg)
        except Cancelled:
            self._cleanup(created)
            result.status = "cancelled"
            result.message = "已取消，已删除未完成的文件"
        except SkipError as e:
            self._cleanup(created)
            result.status = "skipped"
            result.message = str(e)
            result.tech = e.tech
        except ConvertError as e:
            self._cleanup(created)
            result.status = "failed"
            result.message = str(e)
            result.tech = e.tech
        except OSError as e:
            self._cleanup(created)
            result.status = "failed"
            result.message = _explain_os_error(e)
            result.tech = f"{type(e).__name__}: {e}"
        except Exception as e:
            self._cleanup(created)
            result.status = "failed"
            result.message = "程序内部出错，没有生成文件（源文件没有改动）"
            result.tech = f"{type(e).__name__}: {e}"
        finally:
            _cancel_local.event = None
        return result

    def _cleanup(self, created):
        for p in reversed(created):
            try:
                if os.path.isdir(p):
                    if not os.listdir(p):
                        os.rmdir(p)
                    else:
                        for fn in os.listdir(p):
                            os.remove(os.path.join(p, fn))
                        os.rmdir(p)
                elif os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    def _convert(self, src, kind, result, created, note=""):
        opts = self.opts
        if not os.path.isfile(src):
            raise ConvertError("文件不存在")
        self.progress(0.0, "读取文件信息")
        info = probe(src)
        layout = mp4_layout(src) if kind == "fmp4" else None
        end_state = mkv_end_state(src) if kind == "mkv" else None
        ts_pkt = 0
        if kind == "ts":
            end_state, ts_pkt = ts_end_state(src)
        elif kind == "flv":
            end_state = flv_end_state(src)
        if not info["streams"]:
            raise ConvertError("文件无法读取（可能已损坏，或录制刚开始就中断了，里面没有可用的画面和声音）",
                               info.get("_stderr", ""))
        src_ext = os.path.splitext(src)[1].lower()
        plan = build_plan(info, kind, opts, src_ext)
        if note:
            plan.lines.insert(0, note)
            self.log(note)
        if kind == "fmp4" and opts.companion:
            plan.lines.append("分片 MP4 只做原样整理，不添加兼容音轨、不重新编码")

        src_input = src
        if kind == "fmp4" and layout and layout["truncated"]:
            safe_end = fmp4_safe_end(src)
            if safe_end:
                src_input = f"subfile,,start,0,end,{safe_end},,:{src}"
                plan.lines.append("录制中断时最后一帧只写了一半，已把这半帧去掉，避免转出来的文件结尾花屏或爆音")
        if kind == "ts" and end_state == "truncated" and ts_pkt:
            pids = set()
            for s in info["streams"]:
                if s.get("codec_type") == "video" and not _is_attached_pic(s):
                    try:
                        pids.add(int(s.get("id") or "", 16))
                    except ValueError:
                        pass
            safe_end = ts_safe_end(src, ts_pkt, pids) if pids else None
            if safe_end:
                src_input = f"subfile,,start,0,end,{safe_end},,:{src}"
                plan.lines.append("录制中断时最后一帧画面只写了一半，已把这半帧去掉，避免转出来的文件结尾花屏")
        if kind == "flv":
            plan.input_flags = ["-fflags", "+discardcorrupt"]

        folder, stem, ext = choose_output(src, kind, opts, plan.container)
        if not os.path.isdir(folder):
            raise ConvertError(f"输出文件夹不存在：{folder}")
        final_main = os.path.join(folder, stem + ext)
        partial_main = _unique_partial(final_main)
        if same_file(final_main, src) or same_file(partial_main, src):
            raise ConvertError("输出路径和源文件相同，已停止以保护源文件")

        src_size = os.path.getsize(src)
        dur = _fdur(info["format"].get("duration"))
        comp_bytes = 0
        if plan.companions and dur:
            comp_bytes = int(plan.companions * dur * 1536000 / 8)
        extra_bytes = estimate_extra_bytes(info, plan, src_size, dur)
        need = int(src_size * 1.03) + comp_bytes + extra_bytes + 200 * 1024 ** 2
        if opts.export_audio:
            need += audio_export_bytes(info, dur)
        free = free_space(folder)
        if free is not None and free < need:
            raise SkipError(f"已跳过：输出位置空间不够：需要约 {fmt_size(need)}，只剩 {fmt_size(free)}。请清理磁盘或换一个输出文件夹")
        fs = filesystem_name(folder).upper()
        if fs == "FAT32" and src_size > 4 * 1024 ** 3 - 1:
            raise SkipError("已跳过：输出位置是 FAT32 格式（U 盘常见），放不下 4 GB 以上的文件。请换一个输出文件夹")
        werr = check_writable(folder)
        if werr:
            raise ConvertError("输出文件夹不能写入（没有权限、只读或被占用），请换一个输出文件夹：" + folder, werr)

        result.output = final_main
        attach_dirs = {"font": os.path.join(folder, stem + "_fonts"), "other": os.path.join(folder, stem + "_附件")}
        for sc in plan.sidecars:
            final = os.path.join(folder, stem + sc.path)
            sc.path = final
            sc.partial = _unique_partial(final)
        need_dirs = set()
        for kind_, _, _ in plan.dumps:
            need_dirs.add("font" if kind_ == "font" else "other")
        for k in need_dirs:
            os.makedirs(attach_dirs[k], exist_ok=False)
            created.append(attach_dirs[k])
        used_names = {}
        for i, (kind_, idx, fname) in enumerate(plan.dumps):
            d = "font" if kind_ == "font" else "other"
            base, e = os.path.splitext(fname)
            n = used_names.get((d, fname.lower()), 0)
            used_names[(d, fname.lower())] = n + 1
            if n:
                plan.dumps[i] = (kind_, idx, f"{base} ({n}){e}")

        created.append(partial_main)
        for sc in plan.sidecars:
            created.append(sc.partial)

        self.log(f"开始转换：{os.path.basename(src)}（{fmt_size(src_size)}{'，时长 ' + fmt_time(dur) if dur else ''}）")
        total_bytes = src_size + comp_bytes
        tail_label = "整理文件（把索引移到开头，大文件要等一会儿）" if opts.faststart else "收尾"

        stage = {"main": "转换中"}

        def prog(frac, end):
            near_end = end or frac >= 0.985
            self.progress(frac * 0.9, tail_label if near_end else stage["main"])

        args = build_command(src_input, plan, partial_main, opts, attach_dirs)
        rc, err = self.runner.run(args, dur, total_bytes, prog)
        extras_separately = False
        first_err = list(err)
        if rc != 0:
            self.log("一次性转换没有成功，改用更稳妥的方式重试…")
            stage["main"] = "重试中"
            self.progress(0.0, stage["main"])
            for p in [partial_main] + [sc.partial for sc in plan.sidecars]:
                if os.path.exists(p):
                    os.remove(p)
            for k in need_dirs:
                for fn in os.listdir(attach_dirs[k]):
                    os.remove(os.path.join(attach_dirs[k], fn))
            args = build_command(src_input, plan, partial_main, opts, attach_dirs, include_extras=False)
            rc, err = self.runner.run(args, dur, total_bytes, prog)
            if rc != 0 and plan.companions:
                self.log("仍然没有成功，再试一次（这次不加兼容音轨）…")
                self.progress(0.0, stage["main"])
                if os.path.exists(partial_main):
                    os.remove(partial_main)
                kept = [o for o in plan.streams if o.role != "companion"]
                trial = Plan(**{**plan.__dict__, "streams": kept})
                args = build_command(src_input, trial, partial_main, opts, attach_dirs, include_extras=False)
                rc, err = self.runner.run(args, dur, total_bytes, prog)
                if rc == 0:
                    plan.streams = kept
                    plan.companions = 0
                    plan.warnings.append("兼容音轨生成失败，只保留了原始音轨")
            if rc != 0:
                tech = _err_summary(first_err, 8) + "\n---\n" + (_err_summary(err, 8) or f"ffmpeg 返回码 {rc}")
                raise ConvertError("转换失败：" + explain_ffmpeg(first_err + err) + "。没有生成文件，源文件没有改动", tech)
            extras_separately = True

        all_err = "\n".join(err)
        err_hit = any(p in all_err for p in TRUNC_PATTERNS)
        issue_at = self.runner.first_issue_at
        ts_jump = kind == "ts" and "timestamp discontinuity" in all_err
        if kind == "fmp4":
            truncated = bool(layout and layout["truncated"])
            read_error = False
        elif kind in ("ts", "flv"):
            truncated = end_state == "truncated"
            read_error = err_hit and not truncated
        else:
            truncated = end_state in ("truncated", "unfinalized") or (end_state == "unknown" and err_hit and not dur)
            read_error = err_hit and not truncated
        if err_hit:
            result.tech_lines += ["ffmpeg：" + l for l in _err_summary(err, 6).splitlines()]

        if extras_separately:
            self.progress(0.9, "另存字幕和附件")
            self._extract_extras_separately(src, plan, attach_dirs, result)

        if not os.path.exists(partial_main) or os.path.getsize(partial_main) < 1024:
            raise ConvertError("没有转换出任何内容（文件可能已严重损坏）", _err_summary(err, 8))

        self.progress(0.9, "检查结果")
        verify_output(src, info, plan, partial_main, result, opts, kind, truncated, self.log, src_input, ts_jump)
        if result.errors and any("没有可播放的内容" in e for e in result.errors):
            raise ConvertError("文件无法读取（可能已损坏，或录制刚开始就中断了，里面没有可用的画面和声音）")

        src_dur = None if ts_jump else dur
        if truncated or (src_dur and result.recovered_until and result.recovered_until < src_dur - 1.0
                         and kind == "fmp4"):
            when = fmt_time(result.recovered_until)
            if kind != "fmp4":
                result.message = f"录制文件末尾不完整（可能是 OBS 意外退出），已转换到 {when}，后面的部分无法恢复"
            else:
                result.message = f"录制中断，已恢复到 {when}（最后一个不完整的片段无法恢复）"
            result.warnings.insert(0, result.message)
        elif read_error:
            if src_dur and result.recovered_until and result.recovered_until < src_dur - 1.0:
                result.errors.insert(0, f"读取源文件中途出错，输出不完整：源文件 {fmt_time(src_dur)}，只转换到 "
                                        f"{fmt_time(result.recovered_until)}。源文件本身是完整的，请勿删除；"
                                        "可以检查硬盘/U 盘连接后重试")
                result.message = "读取源文件中途出错，输出不完整，请勿删除源文件"
            else:
                where = f"（位置约在 {fmt_time(issue_at)} 或稍后）" if issue_at else ""
                result.warnings.append(f"源文件中间有个别损坏的数据包{where}，已原样照搬（播放到那里可能会花屏或杂音一下），其余内容完整")

        audio_dir = None
        if opts.export_audio:
            self.progress(0.95, "另存音轨")
            audio_dir = self._export_audio(src_input, info, kind, plan.input_flags, folder, stem, result, created,
                                           truncated, src, not ts_jump)

        if self.runner.cancelled():
            raise Cancelled()
        self.progress(0.99, "保存文件")
        os.rename(partial_main, final_main)
        created.remove(partial_main)
        if audio_dir:
            created.remove(audio_dir)
        for sc in plan.sidecars:
            if os.path.exists(sc.partial) and os.path.getsize(sc.partial) > 0:
                target = sc.path
                n = 1
                while os.path.lexists(target):
                    r, e = os.path.splitext(sc.path)
                    target = f"{r} ({n}){e}"
                    n += 1
                os.rename(sc.partial, target)
                created.remove(sc.partial)
                result.extra_files.append(target)
            else:
                if os.path.exists(sc.partial):
                    os.remove(sc.partial)
                created.remove(sc.partial)
                result.errors.append(f"源 #{sc.src} 的{sc.what}没能另存出来")
        for k in need_dirs:
            d = attach_dirs[k]
            created.remove(d)
            files = os.listdir(d)
            if files:
                result.extra_files.append(d + os.sep)
            else:
                os.rmdir(d)
        for kind_, idx, fname in plan.dumps:
            d = attach_dirs["font" if kind_ == "font" else "other"]
            if not os.path.exists(os.path.join(d, fname)):
                result.errors.append(f"源 #{idx} 的附件 {fname} 没能另存出来")
        if plan.metadata_sidecar:
            meta_text = ffmetadata_text(info)
            mpath = _write_new(os.path.join(folder, stem + ".metadata.txt"), lambda f: f.write(meta_text),
                               encoding="utf-8", newline="\n")
            data = {k: v for k, v in info.items() if not k.startswith("_")}
            if "filename" in data.get("format", {}):
                data["format"] = dict(data["format"], filename=os.path.basename(data["format"]["filename"]))
            jpath = _write_new(os.path.join(folder, stem + ".源文件信息.json"),
                               lambda f: json.dump(data, f, ensure_ascii=False, indent=1), encoding="utf-8")
            result.extra_files += [mpath, jpath]

        result.warnings = plan.warnings + result.warnings
        result.status = "failed" if result.errors else ("warn" if result.warnings else "ok")
        if result.status == "failed" and not result.message:
            only_audio = all(e.startswith(AUDIO_ERR) for e in result.errors)
            result.message = "MP4 已转换好，但另存音轨没有全部成功，请看报告" if only_audio else "转换完成但检查没通过，请看报告"
        report = os.path.join(folder, stem + ".转换报告.txt")
        if result.audio_files and not result.message:
            result.message = f"已另存 {len(result.audio_files)} 条音轨到“{os.path.basename(result.audio_dir)}”文件夹"
        result.report_path = write_report(report, result, plan, info)
        self.progress(1.0, "完成")

    def _export_audio(self, src_input, info, kind, in_flags, folder, stem, result, created, truncated, src=None,
                      check_duration=True):
        items = audio_export_items(info, kind)
        if not items:
            result.lines.append("源文件里没有音轨，没有另存音轨文件")
            return None
        d = os.path.join(folder, stem + AUDIO_DIR_SUFFIX)
        os.makedirs(d, exist_ok=False)
        created.append(d)
        for it in items:
            it["path"] = os.path.join(d, it["name"])
            it["partial"] = _unique_partial(it["path"])
        self.log(f"把 {len(items)} 条音轨另存成单独的音频文件…")
        head = ["-n"] + list(in_flags) + ["-i", src_input]
        args = list(head)
        for it in items:
            args += audio_export_args(it)
        rc, err = self.runner.run(args)
        if rc != 0:
            for it in items:
                if os.path.exists(it["partial"]):
                    os.remove(it["partial"])
            for it in items:
                rc1, err1 = self.runner.run(head + audio_export_args(it, solo=True))
                if rc1 != 0:
                    it["failed"] = _err_summary(err1, 2)
        verify_audio_export(src or src_input, src_input, kind, in_flags, items, result, self.opts, truncated, self.log,
                            check_duration)
        if self.runner.cancelled():
            raise Cancelled()
        for it in items:
            if it.get("failed") is not None:
                result.errors.append(f"{AUDIO_ERR}第 {it['name'].split('-', 1)[0]} 条音轨（{it['codec']}）没能另存出来")
                if it["failed"]:
                    result.tech_lines.append(f"另存音轨 {it['name']}：" + it["failed"].replace("\n", " / "))
                if os.path.exists(it["partial"]):
                    os.remove(it["partial"])
                continue
            os.rename(it["partial"], it["path"])
            result.audio_files.append(it["path"])
            off = it["offset"]
            if off is not None and it["frame"] and abs(off) > it["frame"]:
                target = result.warnings if abs(off) >= AUDIO_OFFSET_WARN else result.notes
                if off > 0:
                    target.append(f"{it['name']}：这条音轨比画面晚 {off:.3f} 秒开始，剪辑时请对齐"
                                  f"（放到画面开始后 {off:.3f} 秒的位置）")
                else:
                    target.append(f"{it['name']}：这条音轨比画面早 {-off:.3f} 秒开始，剪辑时请对齐"
                                  f"（把它往前挪 {-off:.3f} 秒，或剪掉开头的 {-off:.3f} 秒）")
        if not result.audio_files:
            os.rmdir(d)
            created.remove(d)
            return None
        result.audio_dir = d
        return d

    def _export_only(self, src, result, created, note):
        opts = self.opts
        if not os.path.isfile(src):
            raise ConvertError("文件不存在")
        self.progress(0.0, "读取文件信息")
        info = probe(src)
        if not info["streams"]:
            raise ConvertError("文件无法读取（可能已损坏）", info.get("_stderr", ""))
        if not any(s.get("codec_type") == "audio" for s in info["streams"]):
            result.status = "skipped"
            result.message = note + "，里面也没有音轨可以另存"
            return
        folder, stem = choose_audio_base(src, opts)
        if not os.path.isdir(folder):
            raise ConvertError(f"输出文件夹不存在：{folder}")
        dur = _fdur(info["format"].get("duration"))
        need = audio_export_bytes(info, dur) + 50 * 1024 ** 2
        free = free_space(folder)
        if free is not None and free < need:
            raise SkipError(f"已跳过：输出位置空间不够：需要约 {fmt_size(need)}，只剩 {fmt_size(free)}。请清理磁盘或换一个输出文件夹")
        werr = check_writable(folder)
        if werr:
            raise ConvertError("输出文件夹不能写入（没有权限、只读或被占用），请换一个输出文件夹：" + folder, werr)
        plan = Plan(lines=[f"{note}；按设置只把音轨另存成单独的音频文件"])
        self.log(f"{note}：{os.path.basename(src)}，只另存音轨")
        self.progress(0.05, "另存音轨")
        d = self._export_audio(src, info, "plain", [], folder, stem, result, created, False)
        if self.runner.cancelled():
            raise Cancelled()
        if d:
            created.remove(d)
        result.status = "failed" if result.errors else ("warn" if result.warnings else "ok")
        if result.audio_files:
            result.message = f"{note}，已把 {len(result.audio_files)} 条音轨另存到“{os.path.basename(d)}”文件夹"
        else:
            result.message = "另存音轨失败，请看报告"
        report = os.path.join(folder, stem + ".转换报告.txt")
        result.report_path = write_report(report, result, plan, info)
        self.progress(1.0, "完成")

    def _extract_extras_separately(self, src, plan, attach_dirs, result):
        for sc in plan.sidecars:
            args = ["-n", "-i", src, "-map", f"0:{sc.src}"] + sc.args + [sc.partial]
            rc, err = self.runner.run(args)
            if rc != 0:
                self.log(f"另存 #{sc.src} 失败：{_err_summary(err, 2)}")
        dumps = [d for d in plan.dumps if d[0] in ("font", "other")]
        if dumps:
            args = []
            for kind_, idx, fname in dumps:
                args += [f"-dump_attachment:{idx}", os.path.join(attach_dirs["font" if kind_ == "font" else "other"], fname)]
            self.runner.run(args + ["-n", "-i", src, "-f", "null", "-"])
        for kind_, idx, fname in plan.dumps:
            if kind_ == "cover":
                self.runner.run(["-n", "-i", src, "-map", f"0:{idx}", "-c", "copy", "-frames:v", "1", "-update", "1",
                                 "-f", "image2", os.path.join(attach_dirs["other"], fname)])


def result_summary(r, tech=False):
    head = {"ok": "成功", "warn": "完成（有提示）", "failed": "失败", "skipped": "跳过", "cancelled": "已取消"}.get(r.status, r.status)
    lines = [f"[{head}] {os.path.basename(r.src)}"]
    if r.output and r.status in ("ok", "warn", "failed") and os.path.exists(r.output):
        lines.append(f"  输出：{r.output}")
    if r.message:
        lines.append(f"  {r.message}")
    for w in r.warnings + r.notes:
        if w != r.message:
            lines.append(f"  ! {w}")
    for e in r.errors:
        lines.append(f"  × {e}")
    if r.extra_files:
        lines.append(f"  另存文件 {len(r.extra_files)} 个：" + "，".join(os.path.basename(p.rstrip(os.sep)) for p in r.extra_files[:6]) + ("…" if len(r.extra_files) > 6 else ""))
    if r.audio_files:
        lines.append(f"  音轨 {len(r.audio_files)} 个（{os.path.basename(r.audio_dir)}）：" + "，".join(os.path.basename(p) for p in r.audio_files[:6]) + ("…" if len(r.audio_files) > 6 else ""))
    if r.report_path:
        lines.append(f"  报告：{r.report_path}")
    if tech and r.tech and r.status in ("failed", "skipped"):
        lines.append("  技术细节：" + r.tech.replace("\n", "\n    "))
    return "\n".join(lines)
