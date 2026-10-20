import fnmatch
import hashlib
import os
import re
import shutil
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "publish", "repo")
RELEASE = os.path.join(ROOT, "publish", "release")
RELEASE_NOTES = os.path.join(ROOT, "docs", "release-notes.md")
ZIP_SCAN_LIMIT = 64 * 1024 ** 2
IDENTITY_KINDS = {"Windows user name", "Windows user folder", "personal drive path"}
OWN_TEXTS = {"README-使用说明.txt", "licenses/FFmpeg-说明.txt", "licenses/LICENSE-视频转MP4.txt",
             "README-SOURCE.txt", "build_ffmpeg.sh", "configure-command.txt", "msys2-packages.txt"}
ALWAYS_SKIP = {".git"}
BINARY_LIMIT = 2 * 1024 ** 2
TOTAL_LIMIT = 10 * 1024 ** 2

PATTERNS = [
    ("Windows user folder", re.compile("C:" + r"[\\/]+" + "Users", re.I)),
    ("personal drive path", re.compile("D:" + r"[\\/]+" + "AI" + r"\b", re.I)),
    ("personal drive path", re.compile("D:" + r"[\\/]+" + "素材")),
    ("e-mail address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    ("phone number", re.compile(r"(?<![\w.])(\+?86[- ]?)?1[3-9]\d[- ]?\d{4}[- ]?\d{4}(?![\w.])")),
]


def load_ignore():
    rules = []
    with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            if neg:
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.strip("/")
            rules.append((line, dir_only, "/" in line, neg))
    return rules


def ignored(rel, is_dir, rules):
    parts = rel.split("/")
    result = False
    for pat, dir_only, anchored, neg in rules:
        if dir_only and not is_dir:
            continue
        hit = fnmatch.fnmatchcase(rel, pat) if anchored else fnmatch.fnmatchcase(parts[-1], pat)
        if hit:
            result = not neg
    return result


def collect():
    rules = load_ignore()
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = sorted(d for d in dirnames
                             if d not in ALWAYS_SKIP and not ignored(rel_dir + d, True, rules))
        for fn in sorted(filenames):
            rel = rel_dir + fn
            if not ignored(rel, False, rules):
                files.append(rel)
    return files


def read_text(path):
    with open(path, "rb") as f:
        data = f.read()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def user_patterns():
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    patterns = list(PATTERNS)
    if len(user) >= 3:
        patterns.insert(0, ("Windows user name", re.compile(re.escape(user), re.I)))
    return user, patterns


def scan_text(name, text, patterns, findings):
    for kind, rx in patterns:
        if rx.search(name):
            findings.append(f"{name}: file name: {kind}")
    if text is None:
        return
    for no, line in enumerate(text.splitlines(), 1):
        for kind, rx in patterns:
            if rx.search(line):
                findings.append(f"{name}:{no}: {kind}")


def decode(data):
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def export_repo(patterns):
    shutil.rmtree(DEST, ignore_errors=True)
    files = collect()
    findings = []
    n_text = n_bin = total = 0
    for rel in files:
        src = os.path.join(ROOT, *rel.split("/"))
        dst = os.path.join(DEST, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        size = os.path.getsize(dst)
        total += size
        text = read_text(dst)
        scan_text(rel, text, patterns, findings)
        if text is None:
            n_bin += 1
            if size > BINARY_LIMIT:
                findings.append(f"{rel}: binary file is {size / 1024 ** 2:.1f} MB (limit {BINARY_LIMIT / 1024 ** 2:.0f} MB)")
            continue
        n_text += 1
    if total > TOTAL_LIMIT:
        findings.append(f"repository total is {total / 1024 ** 2:.1f} MB (limit {TOTAL_LIMIT / 1024 ** 2:.0f} MB)")
    print(f"exported {len(files)} files ({n_text} text, {n_bin} binary, {total / 1024:.0f} KB) to {os.path.relpath(DEST, ROOT)}")
    return findings


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_release():
    sys.path.insert(0, ROOT)
    import build
    app_zip = build.ZIP
    src_zip = os.path.join(os.environ.get(build.SLIM_DIR_ENV) or build.SLIM_DIR_DEFAULT, build.SLIM_SOURCE_ZIP)
    for p in (app_zip, src_zip):
        if not os.path.isfile(p):
            raise SystemExit(f"missing {p}: run python build.py first / set {build.SLIM_DIR_ENV}")
    shutil.rmtree(RELEASE, ignore_errors=True)
    os.makedirs(RELEASE)
    for p in (app_zip, src_zip):
        shutil.copy2(p, RELEASE)
    shutil.copy2(RELEASE_NOTES, os.path.join(RELEASE, "release-notes.md"))
    with open(os.path.join(RELEASE, "SHA256SUMS.txt"), "w", encoding="utf-8", newline="\n") as f:
        for p in (app_zip, src_zip):
            f.write(f"{sha256(p)}  {os.path.basename(p)}\n")
    print(f"release files written to {os.path.relpath(RELEASE, ROOT)}")


def scan_release(user, patterns):
    findings = []
    if not os.path.isdir(RELEASE):
        return findings
    identity = [(k, rx) for k, rx in patterns if k in IDENTITY_KINDS]
    needles = [user.encode("utf-8"), user.encode("utf-16-le")] if len(user) >= 3 else []
    for sep in ("\\", "/"):
        folder = "C:" + sep + "Users"
        needles += [folder.encode("utf-8"), folder.encode("utf-16-le")]
    for fn in sorted(os.listdir(RELEASE)):
        full = os.path.join(RELEASE, fn)
        if not fn.endswith(".zip"):
            with open(full, "rb") as f:
                scan_text(fn, decode(f.read()), patterns, findings)
            continue
        n_text = n_bin = 0
        with zipfile.ZipFile(full) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = f"{fn}/{info.filename}"
                own = info.filename.split("/", 1)[-1] in OWN_TEXTS or "/源代码/" in info.filename
                if info.file_size > ZIP_SCAN_LIMIT:
                    scan_text(name, None, patterns, findings)
                    n_bin += 1
                    continue
                data = z.read(info)
                text = decode(data)
                scan_text(name, text, patterns if own else identity, findings)
                if text is None:
                    n_bin += 1
                    low = data.lower()
                    for nd in needles:
                        if nd.lower() in low:
                            findings.append(f"{name}: binary contains {nd!r}")
                else:
                    n_text += 1
        print(f"scanned {fn}: {n_text} text, {n_bin} binary members")
    return findings


def main():
    user, patterns = user_patterns()
    if "--release" in sys.argv[1:]:
        build_release()
    findings = export_repo(patterns) + scan_release(user, patterns)
    if findings:
        print(f"{len(findings)} finding(s):")
        for f in findings:
            print("  " + f)
        return 1
    print("privacy scan: no findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
