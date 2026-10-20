import os
import shutil
import subprocess
import sys
import time
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkv2mp4_core as core

NAME = core.APP_NAME
BUILD = os.path.join(HERE, "build")
DIST = os.environ.get("MKV2MP4_DIST_DIR") or os.path.join(HERE, "dist")
APP = os.path.join(DIST, NAME)
ZIP = os.path.join(DIST, f"Video2MP4-v{core.VERSION}-win64.zip")
ICON = os.path.join(HERE, "assets", "app.ico")
GUIDE = "README-使用说明.txt"
SOURCE_FILES = ["mkv2mp4_core.py", "mkv2mp4.py", "gui.py", "LICENSE", GUIDE]

PROJECT_URL = "https://github.com/haihuangz/Video2MP4"

FFMPEG_PACKAGING = "bundle-slim"
FFMPEG_PACKAGING_CHOICES = ("bundle-slim",)
SLIM_DIR_ENV = "MKV2MP4_FFMPEG_SLIM_DIR"
SLIM_DIR_DEFAULT = r"D:\build\ffmpeg-slim\out"
SLIM_BIN_FILES = ("ffmpeg.exe", "ffprobe.exe", "avcodec-62.dll", "avdevice-62.dll", "avfilter-11.dll",
                  "avformat-62.dll", "avutil-60.dll", "swresample-6.dll", "swscale-9.dll")
SLIM_SOURCE_ZIP = "ffmpeg-slim-8.1.1-source.zip"

PROJECT_PAGE = "本程序的 GitHub 项目页（发布页 Releases）"
PROJECT_ISSUES = "本程序 GitHub 项目页上的 Issues（问题反馈）"
PROJECT_PAGE_EN = "this program's GitHub project page (Releases)"
PROJECT_ISSUES_EN = "the Issues section of this program's GitHub project page"

FFMPEG_NOTICE = """FFmpeg 说明 / FFmpeg notice
==========================

本软件包 bin\\ 文件夹里的 ffmpeg.exe、ffprobe.exe 和 7 个 DLL 是 FFmpeg 项目（https://ffmpeg.org）
的程序，由本项目自己从 FFmpeg 官方发布的源代码编译，没有修改 FFmpeg 的源代码：

  版本      : {version}
  许可      : GNU General Public License 第 2 版或（任选）任何更新版本（GPLv2+），
              全文见 ffmpeg\\FFmpeg-COPYING.GPLv2.txt，FFmpeg 自己的许可说明见 ffmpeg\\FFmpeg-LICENSE.md
  静态链接  : x264、x265（GPLv2+），dav1d（BSD-2-Clause），zlib（Zlib 许可），以及 MinGW-w64 / GCC
              运行库；各自的许可全文都在 ffmpeg\\ 文件夹
  精简内容  : 不含网络、采集设备和硬件加速功能（本工具用不到）
  编译信息  : ffmpeg\\BUILD-INFO.txt（configure 参数、各个库的版本、编译环境）

“视频转MP4”本身是独立的程序，只是以命令行方式调用 ffmpeg.exe / ffprobe.exe（GPL 所说的
“mere aggregation”），它自己的代码采用 MIT 许可，见 LICENSE-视频转MP4.txt。

对应的完整源代码：
  - 文件 {source_zip}：和本软件包放在同一个发布版本（Release v{app_version}）里，
    在{page}。里面有 FFmpeg 源代码包（含官方签名）、所有静态链接库的源代码包、编译脚本
    和 configure 参数，照着里面的 README-SOURCE.txt 可以编出同样的程序。
  - 编译脚本也在本程序源代码仓库的 tools\\build_ffmpeg.sh。

书面承诺：
  本软件包制作于 {date}。自发布之日起三年内，任何收到本软件包的人（不管是从哪里拿到的，
  例如朋友转发的压缩包）都可以在{issues}里向我们索取上述 FFmpeg 程序对应的完整
  源代码（即 {source_zip} 的全部内容）。通过网络提供不收费；如果需要寄送实体介质，
  只收取不超过实际成本的费用。

换成你自己的 FFmpeg：
  你可以把 bin\\ 文件夹里的文件换成你自己的 ffmpeg.exe 和 ffprobe.exe（以及它们需要的 DLL），
  也可以删掉 bin\\ 文件夹，改用环境变量 MKV2MP4_FFMPEG_DIR 指向的文件夹或系统 PATH 里的 ffmpeg。

FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project.

----------------------------------------------------------------------------

English

ffmpeg.exe, ffprobe.exe and the 7 DLLs in the bin\\ folder of this package are programs of the FFmpeg project
(https://ffmpeg.org), built by this project from the official FFmpeg release source without modifying it.

  Version        : {version}
  License        : GNU General Public License version 2 or (at your option) any later version (GPLv2+),
                   see ffmpeg\\FFmpeg-COPYING.GPLv2.txt and ffmpeg\\FFmpeg-LICENSE.md
  Statically linked: x264, x265 (GPLv2+), dav1d (BSD-2-Clause), zlib (Zlib license) and the MinGW-w64 / GCC
                   runtime; their license texts are in the ffmpeg\\ folder
  Left out       : network protocols, capture devices and hardware acceleration (not used by this tool)
  Build details  : ffmpeg\\BUILD-INFO.txt (configure line, library versions, build environment)

"视频转MP4" itself is a separate program that only runs ffmpeg.exe / ffprobe.exe on the command line (mere
aggregation); its own code is MIT licensed, see LICENSE-视频转MP4.txt.

Complete corresponding source: the file {source_zip}, published in the same release (Release v{app_version})
as this package on {page_en}. It contains the FFmpeg source tarball with its signature, the source packages of
every statically linked library, the build script and the configure line; README-SOURCE.txt inside explains
how to rebuild. The build script is also in the source repository as tools/build_ffmpeg.sh.

Written offer: this package was made on {date}. For three years from its distribution, anyone who received it,
from wherever (for example a zip forwarded by a friend), may ask for the complete corresponding source code of the
FFmpeg programs above (the full content of {source_zip}) in {issues_en}. It is provided free of charge
for download, or for no more than the cost of physically performing the distribution on a medium.

You may replace the files in bin\\ with your own ffmpeg.exe and ffprobe.exe (and the DLLs they need), or delete
bin\\ and use the folder named by the MKV2MP4_FFMPEG_DIR environment variable or an ffmpeg on PATH instead.
"""


def project_texts():
    url = PROJECT_URL.strip().rstrip("/")
    if not url:
        return {"page": PROJECT_PAGE, "issues": PROJECT_ISSUES, "page_en": PROJECT_PAGE_EN,
                "issues_en": PROJECT_ISSUES_EN}
    return {"page": f"本程序的 GitHub 项目页 {url} （发布页 Releases：{url}/releases）",
            "issues": f"本程序 GitHub 项目页上的 Issues（问题反馈，{url}/issues）",
            "page_en": f"{PROJECT_PAGE_EN} {url}/releases",
            "issues_en": f"{PROJECT_ISSUES_EN} ({url}/issues)"}


def with_project_url(text):
    t = project_texts()
    return text.replace(PROJECT_PAGE, t["page"]).replace(PROJECT_ISSUES, t["issues"])


def slim_dir():
    d = os.environ.get(SLIM_DIR_ENV) or SLIM_DIR_DEFAULT
    missing = [f for f in SLIM_BIN_FILES if not os.path.isfile(os.path.join(d, "bin", f))]
    if missing or not os.path.isdir(os.path.join(d, "licenses")):
        raise SystemExit(f"slim FFmpeg build not found in {d} (missing: {', '.join(missing) or 'licenses'}); "
                         f"set {SLIM_DIR_ENV} to the folder that has bin\\ and licenses\\")
    return d


def make_icon(path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("PIL not available: building without icon")
        return False
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, size - 8, size - 8), radius=48, fill=(31, 102, 191, 255))
    d.rounded_rectangle((8, 8, size - 8, 128), radius=48, fill=(52, 132, 222, 255))
    d.rectangle((8, 90, size - 8, 128), fill=(52, 132, 222, 255))
    d.polygon([(92, 52), (92, 150), (172, 101)], fill=(255, 255, 255, 255))
    try:
        font = ImageFont.load_default(58)
    except TypeError:
        font = None
    text = "MP4"
    if font:
        w = d.textlength(text, font=font)
        d.text(((size - w) / 2, 168), text, font=font, fill=(255, 255, 255, 255))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return True


def run_pyinstaller(icon):
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
            "--name", NAME, "--distpath", DIST, "--workpath", os.path.join(BUILD, "pyi"),
            "--specpath", BUILD, "--exclude-module", "numpy", "--exclude-module", "PIL"]
    if icon:
        args += ["--icon", icon]
    args.append(os.path.join(HERE, "gui.py"))
    print(">", " ".join(args))
    subprocess.run(args, check=True, cwd=HERE)


def bundle_slim_ffmpeg(lic):
    src = slim_dir()
    bin_dir = os.path.join(APP, "bin")
    shutil.rmtree(bin_dir, ignore_errors=True)
    os.makedirs(bin_dir)
    for fn in SLIM_BIN_FILES:
        shutil.copy2(os.path.join(src, "bin", fn), bin_dir)
    ff_lic = os.path.join(lic, "ffmpeg")
    shutil.rmtree(ff_lic, ignore_errors=True)
    shutil.copytree(os.path.join(src, "licenses"), ff_lic)
    write_ffmpeg_notice(lic)


def write_ffmpeg_notice(lic):
    version = core.run_quiet([os.path.join(APP, "bin", "ffmpeg.exe"), "-version"]).stdout.splitlines()[0].split(" Copyright")[0]
    text = FFMPEG_NOTICE.format(version=version, source_zip=SLIM_SOURCE_ZIP, app_version=core.VERSION,
                                date=time.strftime("%Y-%m-%d"), **project_texts())
    with open(os.path.join(lic, "FFmpeg-说明.txt"), "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(text)


def package_ffmpeg(lic):
    if FFMPEG_PACKAGING not in FFMPEG_PACKAGING_CHOICES:
        raise SystemExit(f"unknown FFMPEG_PACKAGING: {FFMPEG_PACKAGING}")
    if FFMPEG_PACKAGING == "bundle-slim":
        bundle_slim_ffmpeg(lic)


def write_guides():
    with open(os.path.join(HERE, GUIDE), encoding="utf-8-sig", newline="") as f:
        text = with_project_url(f.read())
    for d in (APP, os.path.join(APP, "源代码")):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, GUIDE), "w", encoding="utf-8", newline="") as f:
            f.write(text)


def copy_payload(icon):
    if icon:
        shutil.copy2(icon, os.path.join(APP, "app.ico"))

    lic = os.path.join(APP, "licenses")
    os.makedirs(lic, exist_ok=True)
    package_ffmpeg(lic)
    shutil.copy2(os.path.join(HERE, "LICENSE"), os.path.join(lic, "LICENSE-视频转MP4.txt"))
    py_lic = os.path.join(sys.base_prefix, "LICENSE.txt")
    if os.path.exists(py_lic):
        shutil.copy2(py_lic, os.path.join(lic, "Python-LICENSE.txt"))
    tcl_lic = os.path.join(sys.base_prefix, "tcl", "tk8.6", "license.terms")
    if os.path.exists(tcl_lic):
        shutil.copy2(tcl_lic, os.path.join(lic, "Tcl-Tk-license.txt"))

    src = os.path.join(APP, "源代码")
    os.makedirs(src, exist_ok=True)
    for fn in SOURCE_FILES:
        if fn != GUIDE:
            shutil.copy2(os.path.join(HERE, fn), src)
    write_guides()


def make_zip():
    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, files in os.walk(APP):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, DIST))
    print(f"zip: {ZIP} ({os.path.getsize(ZIP) / 1024 ** 2:.0f} MB)")


def texts_only():
    if not os.path.isfile(os.path.join(APP, "bin", "ffmpeg.exe")):
        raise SystemExit(f"{APP} has not been built yet: run python build.py first")
    write_guides()
    write_ffmpeg_notice(os.path.join(APP, "licenses"))
    make_zip()


def clear_app_dir():
    if not os.path.isdir(APP):
        return
    trash = APP + "~old"
    shutil.rmtree(trash, ignore_errors=True)
    try:
        os.rename(APP, trash)
    except OSError:
        raise SystemExit(f"{APP} 正被占用：请先关掉正在运行的“视频转MP4”窗口（任务管理器里也不要有它），再运行一次。")
    shutil.rmtree(trash, ignore_errors=True)


def set_project_url(url):
    global PROJECT_URL
    url = url.strip().rstrip("/")
    if not url.startswith("https://"):
        raise SystemExit(f"--project-url must start with https:// (got {url!r})")
    path = os.path.abspath(__file__)
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("PROJECT_URL = "):
            end = "\r\n" if line.endswith("\r\n") else "\n"
            lines[i] = f'PROJECT_URL = "{url}"{end}'
            break
    else:
        raise SystemExit("PROJECT_URL line not found in build.py")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))
    PROJECT_URL = url


def parse_args(argv):
    opts = {"texts_only": False, "release": False, "url": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--texts-only":
            opts["texts_only"] = True
        elif a == "--release":
            opts["release"] = True
        elif a == "--project-url" and i + 1 < len(argv):
            i += 1
            opts["url"] = argv[i]
        elif a.startswith("--project-url="):
            opts["url"] = a.split("=", 1)[1]
        else:
            raise SystemExit(f"unknown argument: {a}\n"
                             "usage: python build.py [--project-url https://github.com/<user>/<repo>] [--texts-only] [--release]")
        i += 1
    return opts


def main():
    opts = parse_args(sys.argv[1:])
    if opts["url"]:
        set_project_url(opts["url"])
    print("PROJECT_URL:", PROJECT_URL or "(not set: this zip names no URL for the FFmpeg source, do not share or upload it)")
    if opts["texts_only"]:
        texts_only()
    else:
        clear_app_dir()
        os.makedirs(BUILD, exist_ok=True)
        icon = ICON
        if not os.path.isfile(icon) and not make_icon(icon):
            icon = None
        run_pyinstaller(icon)
        copy_payload(icon)
        make_zip()
        print("done:", APP)
    if opts["release"]:
        rc = subprocess.run([sys.executable, os.path.join(HERE, "tools", "export_publish.py"), "--release"]).returncode
        if rc:
            raise SystemExit(rc)


if __name__ == "__main__":
    main()
