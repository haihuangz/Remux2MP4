## 视频转MP4 1.1.0

把 OBS 录的 MKV、FLV、TS、分片 MP4/MOV 一键换成普通 MP4：不重新压缩，音轨、轨道名、语言、章节尽量原样保留，转完逐条和源文件核对并写一份中文报告。界面是中文，只支持 Windows 64 位（macOS / Linux 可以用源代码）。

### 1.1.0 新内容

- **支持 FLV 和 TS / M2TS 输入**：同样不重新编码；TS 的多条音轨和语言、增强型 FLV 里的 HEVC/AV1 都保留，音画同步转完会核对；录制中断的 FLV/TS 能读多少转多少。
- **新选项“把每条音轨另存成单独的音频文件”**（默认关闭）：给剪映等只认 MP4 第一条音轨的软件用，每条音轨一个文件，不重新编码、逐个核对。OBS 32 默认的混合 MP4 打开这个选项时不转换、只另存音轨。
- **附带的 FFmpeg 换成自己编译的精简版 FFmpeg 8.1.1**，`bin` 文件夹从 455 MB 降到约 59 MB。
- 报告里只写文件名，不再写完整路径（不会带出 Windows 用户名）；还有若干提示文字和稳定性改进，详见仓库里的 CHANGELOG.md。

### 下载和使用

1. 下载下面的 `Remux2MP4-v1.1.0-win64.zip`，右键 →“全部解压缩”。
2. 双击 `视频转MP4.exe`，把录像文件或文件夹拖进窗口，点“开始转换”。
3. 转完点“打开输出文件夹”；双击列表里的文件可以看转换报告。详细说明见压缩包里的 `README-使用说明.txt`。

第一次运行时 Windows 可能提示“Windows 已保护你的电脑”（SmartScreen），因为程序没有付费的代码签名：点“更多信息”→“仍要运行”即可。程序不联网、不修改系统设置。

已知限制（哪些情况会重新压缩、哪些没有实测）见仓库首页 README 的“保留什么、已知限制”一节。

### FFmpeg 许可和源代码

本工具代码使用 MIT 许可。压缩包 `bin` 文件夹里的 FFmpeg 8.1.1（带 x264、x265、dav1d、zlib）按 GPL 第 2 版或更新版本发布，是独立的程序，本工具只以命令行方式调用它。它对应的完整源代码就是本发布页上的 `ffmpeg-slim-8.1.1-source.zip`（FFmpeg 源代码、所有静态链接库的源代码、编译脚本和参数）；编译脚本也在仓库的 `tools/build_ffmpeg.sh`。压缩包里的 `licenses\FFmpeg-说明.txt` 有许可说明和三年有效的书面承诺。`SHA256SUMS.txt` 是两个文件的校验值。

---

## Video to MP4 (视频转MP4) 1.1.0

Converts OBS recordings (MKV, FLV, MPEG-TS, fragmented MP4/MOV) into regular MP4 files without re-encoding, keeps tracks, track names, languages and chapters as far as MP4 allows, checks every output against its source and writes a report. The user interface is in Chinese; Windows 64-bit only (macOS/Linux can run the source).

### What's new in 1.1.0

- **FLV and TS/M2TS input** by stream copy: multiple TS audio tracks with languages, enhanced-FLV HEVC/AV1 and audio/video sync are kept and checked; interrupted FLV/TS recordings are converted as far as they can be read.
- **New option to export every audio track as its own file** (off by default), for editors such as CapCut/剪映 that only read the first audio track; no re-encoding, every file is hash-checked. A cleanly stopped OBS 32 Hybrid MP4 is not converted, only its audio tracks are exported.
- **The bundled FFmpeg is now a self-built slim FFmpeg 8.1.1**; `bin` shrinks from 455 MB to about 59 MB.
- Reports contain file names only, no absolute paths; plus message and robustness improvements, see CHANGELOG.md in the repository.

### Download and use

1. Download `Remux2MP4-v1.1.0-win64.zip` below and extract it (right-click → Extract All).
2. Run `视频转MP4.exe`, drop recordings or folders into the window and press 开始转换 (Start).
3. Press 打开输出文件夹 (open output folder) when done; double-click a row to open its report. The full guide is `README-使用说明.txt` in the zip (Chinese).

Windows SmartScreen may say "Windows protected your PC" on first start because the program is not code-signed: click "More info" → "Run anyway". The program does not access the network and does not change system settings.

Known limitations (what gets re-encoded, what was not tested): see the section "What is preserved, known limitations" of the README on the repository's front page.

### FFmpeg license and source

The tool's own code is MIT licensed. The FFmpeg 8.1.1 in `bin` (with x264, x265, dav1d, zlib) is licensed under the GPL version 2 or later; it is a separate program that the tool only runs on the command line. Its complete corresponding source is `ffmpeg-slim-8.1.1-source.zip` on this release page (FFmpeg source, the source of every statically linked library, build script and configure line); the build script is also in the repository as `tools/build_ffmpeg.sh`. `licenses\FFmpeg-说明.txt` in the zip contains the license notice and a written offer valid for three years. `SHA256SUMS.txt` lists the checksums of both files.
