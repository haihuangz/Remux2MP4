# Research: existing tools, MP4 playback compatibility, licensing

Date of research: 2026-10-20. "Fetched" = page read on 2026-10-20. "Known" = from prior knowledge, not re-fetched (gnu.org returned HTTP 429 during this session).

## 0. Local fact check (ffmpeg 8.1.1 gyan full_build on this PC, 2026-10-20)

Probe script: stream-copy a 1 s stereo track from .mka into .mp4.

| Source codec | `-c copy` into MP4 |
|---|---|
| AAC, MP3, AC-3, E-AC-3, Opus, FLAC, ALAC, DTS (dca), PCM s16le/s24le, Vorbis | OK without flags |
| TrueHD | FAIL: "truehd in MP4 support is experimental, add '-strict -2'"; OK with `-strict -2` |
| SubRip (srt) / ASS copy | FAIL (MP4 only takes timed text) |
| SubRip / ASS -> `mov_text` | OK (ASS styling lost, text kept) |

Implications: "ffmpeg accepts it" is not the same as "players play it" (see section 2). PCM goes in as ISO 23003-5 `ipcm`, Vorbis as a non-standard sample entry: technically muxable, poorly playable. Image subtitles (PGS `hdmv_pgs_subtitle`) and attachments (fonts) cannot go into MP4 at all and must be exported as sidecars.

## 1. Existing free tools

| Tool | Free / license | Keeps ALL audio+sub tracks by default? | Streams MP4 can't hold (ASS, PGS, fonts) | Chapters / metadata | Batch | Chinese UI |
|---|---|---|---|---|---|---|
| **LosslessCut** (mifi) | Free on GitHub, GPL-2.0; paid on app stores (auto-update) | All tracks are listed and toggled per track; user must check that incompatible ones are disabled, otherwise the export fails | Export fails on an incompatible track; docs tell the user to disable tracks one by one or switch to MKV/MOV. Has "Extract all tracks" incl. attachments, as a separate manual action | Chapter editor; per-stream disposition/language editing | README: "no mass/batch export yet" | Has community translations (Chinese among them per the app; not stated on README) |
| **Shutter Encoder** "Rewrap" | Free, GPL-3 | Audio 1-16 mapping; "Preserve subtitles" only if container supports them; docs don't say all tracks kept by default | Rewrap "only works if the output container supports the source codec". Separate "Extract" function for streams | "Preserve metadata" option; chapters not documented | File list accepts many files | Chinese added in v15.4 |
| **HandBrake** | Free, GPL-2 | No: re-encodes video always; audio/subtitle selection by language rules; Auto Passthru with fallback re-encode | PGS can't go to MP4; can burn only ONE subtitle track; user report of only 1 subtitle track surviving into MP4 | Chapters kept; metadata partial | Yes (queue) | Yes |
| **MKVToolNix** | Free, GPL-2 | n/a | Cannot write MP4 at all; developer: "MP4 output will never happen" | - | - | Yes |
| **Avidemux** | Free, GPL-2 | Forum reports: only first audio track survived in older versions | "No support for subtitle tracks" (forum moderator); copy mode drops unsupported streams | Weak | Via scripting | Partial |
| ffmpeg CLI | Free, LGPL/GPL | No: default picks 1 video + 1 audio + 1 sub; needs `-map 0` and per-codec handling | Errors out on ASS/PGS/attachments unless mapped away / converted | `-map_chapters`, `-map_metadata` (default on for global) | Shell loops | No (CLI) |
| Format Factory, various "free converters" | Freeware, often bundled ads | Typically one audio track, re-encode | Usually drop | Usually drop | Yes | Yes |

### Gap a small dedicated tool fills
1. **Zero-config, true remux by default**: `-map 0` equivalent, no re-encode of video, every audio track, languages, titles, default/forced flags, chapters, global + per-stream tags.
2. **Automatic per-stream decision** instead of failing: compatible stream -> copy; text subs -> `mov_text` + original saved as sidecar (.ass/.srt with language in name) so styling isn't lost; PGS/VobSub -> sidecar (.sup/.sub) because MP4 cannot hold them; fonts/attachments -> sidecar folder; audio that MP4 holds but players won't play (TrueHD, DTS, PCM, Vorbis, maybe FLAC/Opus) -> keep original AND optionally add a compatible AAC/AC-3 copy (user choice, default documented).
3. **Batch, drag-drop, Chinese UI**: none of LosslessCut (no batch), MKVToolNix (no MP4), HandBrake (re-encodes) cover this for non-technical users.
4. **Verification report**: after conversion, ffprobe both files and list each source stream -> where it went (in MP4 / sidecar / converted), duration check, so the user can trust nothing was silently dropped. No existing GUI tool does this.
5. Never touches the source; write to temp name then rename.

## 2. Playback compatibility of codecs inside MP4

Legend: Y = plays, N = doesn't, ? = version/device-dependent.

| Audio in MP4 | Win11 Media Player / Films&TV (Media Foundation) | PotPlayer | VLC / mpv | macOS QuickTime / iOS | Android (platform + Media3) | Browsers | Smart TVs |
|---|---|---|---|---|---|---|---|
| AAC | Y | Y | Y | Y | Y | Y all | Y |
| MP3 | Y | Y | Y | Y | Y (MP4 since Android 10) | Y all | Y mostly |
| AC-3 | ? removed from Windows 11 24H2 clean installs (OEM/upgrade may keep) | Y | Y | Y (Apple multichannel list) | ? device (Dolby licence) | Safari/Edge only, Chrome/Firefox N | Y mostly |
| E-AC-3 | ? same as AC-3 | Y | Y | Y | ? device | Safari/Edge ?, Chrome/Firefox N | Y mostly |
| Opus | ? (not listed by Microsoft) | Y | Y | iOS 17+ only (Apple engineer) | Y decode since 5.0 | Chrome/Edge/Firefox Y, Safari ? | ? |
| FLAC | Y (built-in) | Y | Y | Y (since iOS 11 / High Sierra) | Y in MP4 since Android 10 (stereo <=48 kHz listed) | Chrome/Edge/Firefox Y, Safari Y | ? |
| ALAC | Y (built-in) | Y | Y | Y | ? (not listed) | Safari only | ? |
| DTS | N (not shipped) | Y | Y | N | ? device | N | ? (many recent TVs dropped DTS) |
| TrueHD | N | Y (mostly) | Y (ffmpeg-based) | N | N | N | N (ffmpeg-user 2020: "no hardware" plays TrueHD-in-MP4) |
| PCM (ipcm) | N/? | ? | Y with recent libavformat | ? | N (WAV only listed) | N | N |
| Vorbis | N (needs Web Media Ext., and only Ogg) | Y | Y | N | Y in MP4 since Android 10 | N (MDN: WebM/Ogg only) | N |

Practical rule for the tool: AAC/MP3/AC-3/E-AC-3/FLAC/ALAC/Opus = keep as is (copy). DTS/TrueHD/PCM/Vorbis = keep the original track (preservation) and add a compatible AAC (or AC-3 for >2 ch) companion track, marked default, so "plays everywhere" and "nothing lost" both hold. Warn in report that Windows 11 24H2 Media Player may be silent on AC-3/E-AC-3 without the Dolby extension.

| `mov_text` (tx3g) subtitles | Shown? |
|---|---|
| VLC, mpv, PotPlayer, MPC-HC/BE | Y (selectable tracks; styling minimal) |
| macOS QuickTime / iOS / Apple TV | Y (old ffmpeg ticket #1845 about QuickTime not showing ffmpeg mov_text, marked fixed) |
| Windows Media Player app / Films&TV | ? usually shows embedded tx3g, not reliably for multiple tracks — test |
| Android Media3/ExoPlayer apps | Y (Media3 has a Tx3g decoder); stock gallery players vary |
| Chrome / Firefox `<video>` | N (in-band MP4 text tracks ignored) |
| Safari | Y |
| Smart TVs | ? brand-dependent; many prefer external .srt next to the file |

Hence: always also save each text subtitle as a sidecar `.srt`/`.ass` named `<video>.<lang>.<ext>` — this is what TVs and most players auto-load.

## 3. Licensing

### gyan.dev build
- gyan.dev: "All builds are 64-bit, static and licensed as GPLv3"; each build links its exact source commit; README.txt in the package lists the full configure line and external library versions. Site content itself is CC BY-NC-ND (does not govern the binaries). Fetched https://www.gyan.dev/ffmpeg/builds/ (2026-10-20).
- FFmpeg legal page: GPL parts make "the GPL apply to all of FFmpeg"; checklist (written for LGPL) asks to distribute matching source, configure line, credit FFmpeg. Fetched https://ffmpeg.org/legal.html (2026-10-20).

### Obligations when shipping ffmpeg.exe/ffprobe.exe with our tool (GPLv3 section 4/6)
1. Include the full GPLv3 text (`licenses/ffmpeg/COPYING.GPLv3`) and gyan's README.txt (configure line + library versions).
2. Provide Corresponding Source for the exact binaries. Options per GPLv3 s.6: (a) ship the source with the download, (b) a written offer valid >= 3 years, or (d) "equivalent access" from a designated place, which may be a third-party server as long as we ensure it stays available. Simplest robust choice: put the ffmpeg 8.1.1 source tarball (ffmpeg.org release) plus gyan's build README, and the source archives of the bundled external libs if feasible, next to our release download; at minimum link the exact gyan release commit and ffmpeg 8.1.1 tag and add a written offer. Note: the "full_build" statically links many third-party libraries (x264, x265, etc.); strict Corresponding Source covers them too — consider the smaller "essentials" build to reduce that burden (verify it has all needed muxers/encoders: aac, ac3, mov_text, libmp3lame not needed).
3. Credit "FFmpeg" in About/README; don't claim ownership; no extra restrictions.
4. Known (GNU GPL FAQ, https://www.gnu.org/licenses/gpl-faq.html#MereAggregation, not re-fetched 2026-10-20 due to 429): programs that communicate via exec/pipes/command-line arguments are normally separate programs; distributing them together is "mere aggregation" and the GPL does not extend to our program. Also https://www.gnu.org/licenses/gpl-faq.html#SourceAndBinaryOnDifferentSites: source may be on a different server if clearly referenced and kept available.

### Our own Python code
- Calls ffmpeg/ffprobe via `subprocess` as separate executables -> our code may use any license (MIT recommended for "everyone can use"). Keep ffmpeg.exe/ffprobe.exe as separate visible files in a `ffmpeg/` folder (not packed inside our onefile exe) so the aggregate boundary is obvious and users can swap ffmpeg.
- PyInstaller: its bootloader license (GPL with exception) allows any license for the bundled app. Python itself: PSF licence, include notice.
- Third-party Chinese UI font: use system fonts (Microsoft YaHei) only; don't redistribute fonts.

## Sources (accessed 2026-10-20)
- LosslessCut README: https://github.com/mifi/lossless-cut (GPL-2.0, "no mass/batch export yet", extract all tracks, chapter editor)
- LosslessCut troubleshooting (disable tracks / switch to MKV): https://git.morozoff.pro/aiden/lossless-cut/src/tag/v3.54.0/issues.md
- Shutter Encoder docs: https://www.shutterencoder.com/documentation ; licence/Chinese: https://www.shutterencoder.com/en/ , changelog via https://www.neowin.net/software/shutter-encoder-154/
- HandBrake audio/subtitle defaults: https://handbrake.fr/docs/en/1.10.0/advanced/audio-subtitle-defaults.html ; forum report: https://forum.handbrake.fr/viewtopic.php?p=185320
- MKVToolNix no MP4 output: https://help.mkvtoolnix.download/t/add-option-for-mp4-output/122
- Avidemux subtitles/audio: https://avidemux.org/smif/index.php/topic,20112.0.html , https://avidemux.org/smif/index.php/topic,10502.0.html
- Microsoft Media Player codecs (AC-3 removed in 24H2): https://support.microsoft.com/en-au/windows/codecs-in-media-player-d5c2cdcd-83a2-4805-abb0-c6888138e456
- WMP12 file types: https://support.microsoft.com/en-us/kb/316992
- Android formats: https://developer.android.com/media/platform/supported-formats
- MDN audio codecs: https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Audio_codecs
- Apple Opus in MP4 iOS 17+: https://developer.apple.com/forums/thread/759210
- TrueHD in MP4: https://ffmpeg.org/pipermail/ffmpeg-user/2020-May/048724.html , https://trac.ffmpeg.org/ticket/7256
- mov_text in QuickTime: https://trac.ffmpeg.org/ticket/1845 ; mov_text players: https://ffmpeg.org/pipermail/ffmpeg-user/2015-March/025862.html
- gyan.dev builds: https://www.gyan.dev/ffmpeg/builds/ ; FFmpeg legal: https://ffmpeg.org/legal.html
- GNU GPL FAQ: https://www.gnu.org/licenses/gpl-faq.html
