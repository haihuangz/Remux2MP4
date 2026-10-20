# 更新记录 / Changelog

## 1.1.0

- 新增：支持 FLV 和 TS 输入（也接受 `.m2ts` / `.mts`），同样不重新编码，输出“原名.mp4”。TS 的多条音轨和语言、增强型 FLV 里的 HEVC/AV1 都保留；各轨道相对画面的起始时间（音画同步）转完后会核对；TS 时间戳中途跳变时按实际内容连续排列，报告里说明源文件标称时长不准。TS 里的 H.264/H.265/AAC 在 MP4 里要换打包方式（起始码 → 长度前缀、去掉 ADTS 头），校验时先把两边统一成同一种形式再逐包比对（方法和实测数据见 `docs/compat-matrix.md`）。录制中断的 FLV/TS 能读多少转多少，最后只写了一半的帧会去掉，提示和 MKV 一样。扩展名是 .mp4 但内容其实是 TS/FLV 的文件，现在会照常转换，不再跳过。
- 新增选项“把每条音轨另存成单独的音频文件”（默认关闭，命令行 `--export-audio`）：在 MP4 旁边的“名字_音轨”文件夹里，每条音轨一个文件（`1-音轨名.m4a` 等，按编码选 .m4a/.mp3/.flac/.opus/.ogg/.wav/.ac3/.eac3/.mka，不重新编码），写入音轨名和语言，逐个和源文件核对；音轨比画面晚或早开始超过 1 帧时，报告里写明差多少秒（差 0.1 秒以上才把结果标成“有提示”）。已经是普通 MP4 的文件（如 OBS 32 默认的混合 MP4）在这个选项打开时不转换、只另存音轨，并写报告。
- 隐私：`转换报告.txt` 和 `源文件信息.json` 里只写文件名，不再写完整路径（完整路径会带出 Windows 用户名，报告常常会和视频一起发给别人）。
- 试解码发现少量数据解不开时，提示里写出大约的时间位置（mm:ss）；源文件中间有损坏数据包的提示也会尽量写出大约位置。
- 自动重试时，进度状态显示“重试中”，单独另存字幕和附件时显示“另存字幕和附件”，不再停留在上一步的文字（例如“整理文件”）。
- 随程序附带的 FFmpeg 换成本项目自己编译的精简版 FFmpeg 8.1.1（GPLv2+，带 x264/x265/dav1d/zlib，不含网络、采集设备和硬件加速），`bin\` 文件夹从 455 MB（gyan.dev 完整版，GPLv3）降到约 59 MB；对应的完整源代码 `ffmpeg-slim-8.1.1-source.zip` 和程序放在同一个发布版本里，编译脚本在 `tools/build_ffmpeg.sh`，说明和书面承诺在 `licenses\FFmpeg-说明.txt`。
- 找 ffmpeg/ffprobe 的顺序统一为：程序旁边的 `bin\` → 环境变量 `MKV2MP4_FFMPEG_DIR` → 系统 PATH。找不到时，图形界面弹窗、命令行在 stderr 说明该把 `ffmpeg.exe` / `ffprobe.exe` 放在哪里，命令行返回码 3。
- 仓库整理：测试素材全部由脚本生成（测试字体改为脚本自己生成的最小 TrueType 文件，PGS 字幕样本也由脚本生成），一次性探索脚本移到 `tests/dev/`，去掉写死的本机路径；图标改为仓库里的 `assets/app.ico`；发布压缩包改用 ASCII 文件名 `Remux2MP4-v<版本>-win64.zip`；新增 README、CHANGELOG、`.gitignore`、`requirements-build.txt`、`tests/README.md` 和导出脚本 `tools/export_publish.py`。

English: new FLV and MPEG-TS input (`.flv`, `.ts`, `.m2ts`, `.mts`) by stream copy, with start-time/sync checks, a normalised packet hash for Annex-B/ADTS streams, timestamp-jump handling and truncated-file recovery; new option to export every audio track as its own file (`--export-audio`, off by default), which also works on files that are already normal MP4s (e.g. OBS 32 Hybrid MP4) by exporting only their audio. Also: reports and the source-info JSON now contain file names only (no absolute paths); decode warnings carry an approximate timestamp; the progress label shows "retrying" / "saving subtitles and attachments" after an automatic retry instead of stale text; ffmpeg/ffprobe discovery is centralised (`bin\` next to the program, then `MKV2MP4_FFMPEG_DIR`, then PATH) with a clear message when they are missing; the bundled FFmpeg is now a self-built slim FFmpeg 8.1.1 (GPLv2+, x264/x265/dav1d/zlib, no network/devices/hwaccels; `bin\` shrinks from the 455 MB gyan.dev full build to about 59 MB), with its complete source `ffmpeg-slim-8.1.1-source.zip` in the same release and the build script in `tools/build_ffmpeg.sh`; an audio start offset below 0.1 s is still reported but no longer marks the file as a warning; repository cleanup (generated test corpus, committed icon, ASCII release zip name, docs).

## 1.0.0

- 第一个版本：MKV/WebM 转 MP4、分片 MP4/MOV 整理成普通 MP4，不重新压缩；保留全部轨道、轨道名、语言、默认/强制标记、章节和标签；MP4 装不下的字幕、字体和附件另存到旁边；转换后逐包比对、试解码并写转换报告；图形界面（拖放、批量）和命令行。

English: first release. MKV/WebM to MP4 and fragmented MP4/MOV to regular MP4 without re-encoding, all tracks and metadata kept, sidecars for what MP4 cannot hold, per-file verification report, GUI and CLI.
