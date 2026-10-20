import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import mkv2mp4_core as core

DROP_TEXT = "把 MKV、FLV、TS 或 分片 MP4 文件（或文件夹）拖到这里"
STATUS_TEXT = {"ok": "完成", "warn": "完成（有提示）", "failed": "失败", "skipped": "跳过", "cancelled": "已取消"}
KIND_TEXT = {"mkv": "MKV/WebM", "fmp4": "分片 MP4", "ts": "TS", "flv": "FLV", "plain": "普通 MP4", "skip": "—"}
INPUT_PATTERNS = " ".join("*" + e for e in sorted(core.ALL_EXTS))


def set_dpi_awareness():
    if os.name != "nt":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def install_drop_target(root, on_files):
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32")
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallWindowProcW.restype = LRESULT
        user32.ChangeWindowMessageFilterEx.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.DWORD, ctypes.c_void_p]
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragFinish.argtypes = [ctypes.c_void_p]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        WM_DROPFILES = 0x0233
        GWLP_WNDPROC = -4

        root.update_idletasks()
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        state = {}

        def proc(h, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                try:
                    count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    files = []
                    for i in range(count):
                        n = shell32.DragQueryFileW(wparam, i, None, 0)
                        buf = ctypes.create_unicode_buffer(n + 1)
                        shell32.DragQueryFileW(wparam, i, buf, n + 1)
                        files.append(buf.value)
                    shell32.DragFinish(wparam)
                    on_files(files)
                except Exception:
                    pass
                return 0
            return user32.CallWindowProcW(state["old"], h, msg, wparam, lparam)

        callback = WNDPROC(proc)
        state["old"] = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p))
        if not state["old"]:
            return False
        shell32.DragAcceptFiles(hwnd, True)
        for m in (WM_DROPFILES, 0x004A, 0x0049):
            try:
                user32.ChangeWindowMessageFilterEx(hwnd, m, 1, None)
            except Exception:
                pass
        root._drop_keepalive = (callback, state)
        return True
    except Exception:
        return False


class App:
    def __init__(self, root, initial_files):
        self.root = root
        self.q = queue.Queue()
        self.items = {}
        self.worker = None
        self.converter = None
        self.cancel_event = threading.Event()
        self.last_output_dir = None
        self.scanning = 0
        self.closing = False
        self.out_dir = tk.StringVar(value="")
        self.out_mode = tk.StringVar(value="same")
        self.companion = tk.BooleanVar(value=True)
        self.sidecars = tk.BooleanVar(value=True)
        self.faststart = tk.BooleanVar(value=core.Options().faststart)
        self.export_audio = tk.BooleanVar(value=core.Options().export_audio)
        self._build()
        self.drop_ok = install_drop_target(root, lambda files: self.q.put(("add", files)))
        if not self.drop_ok:
            self.drop_hint.configure(text="（当前无法拖放，请用下面的按钮添加文件）")
        self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        if initial_files:
            self.add_paths(initial_files, then_start=True)

    def _build(self):
        root = self.root
        root.title(f"{core.APP_NAME} {core.VERSION}")
        base = tkfont.nametofont("TkDefaultFont")
        family = "Microsoft YaHei UI" if os.name == "nt" else base.actual("family")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=family, size=10)
            except tk.TclError:
                pass
        big = tkfont.Font(family=family, size=15, weight="bold")
        small = tkfont.Font(family=family, size=9)
        style = ttk.Style()
        try:
            style.theme_use("vista" if os.name == "nt" else "clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=int(tkfont.Font(family=family, size=10).metrics("linespace") * 1.6))
        style.configure("Accent.TButton", font=(family, 10, "bold"))

        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)

        drop = tk.Frame(outer, bg="#eef4fb", highlightbackground="#7aa7d8", highlightthickness=2, cursor="hand2")
        drop.pack(fill="x")
        self.drop_label = tk.Label(drop, text=DROP_TEXT, font=big, bg="#eef4fb", fg="#1f4e79", pady=16)
        self.drop_label.pack(fill="x")
        self.drop_hint = tk.Label(drop, text="也可以点这里或下面的按钮添加。原文件不会被修改、移动或删除。",
                                  font=small, bg="#eef4fb", fg="#4a6a8a", pady=0)
        self.drop_hint.pack(fill="x", pady=(0, 12))
        for w in (drop, self.drop_label, self.drop_hint):
            w.bind("<Button-1>", lambda e: self.add_files())

        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(10, 6))
        ttk.Button(bar, text="添加文件", command=self.add_files).pack(side="left")
        ttk.Button(bar, text="添加文件夹", command=self.add_folder).pack(side="left", padx=(6, 0))
        self.btn_clear = ttk.Button(bar, text="清空", command=self.clear)
        self.btn_clear.pack(side="left", padx=(6, 0))
        self.btn_open = ttk.Button(bar, text="打开输出文件夹", command=self.open_output)
        self.btn_open.pack(side="right")
        self.btn_cancel = ttk.Button(bar, text="取消", command=self.cancel, state="disabled")
        self.btn_cancel.pack(side="right", padx=(0, 6))
        self.btn_start = ttk.Button(bar, text="开始转换", style="Accent.TButton", command=self.start)
        self.btn_start.pack(side="right", padx=(0, 6))

        paned = ttk.PanedWindow(outer, orient="vertical")
        paned.pack(fill="both", expand=True)

        table_frame = ttk.Frame(paned)
        cols = ("name", "kind", "size", "status", "progress")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=8, selectmode="extended")
        for c, text, w, anchor in (("name", "文件", 380, "w"), ("kind", "类型", 90, "center"),
                                   ("size", "大小", 90, "e"), ("status", "状态", 260, "w"),
                                   ("progress", "进度", 70, "e")):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor, stretch=(c in ("name", "status")))
        sb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self.open_report)
        self.tree.bind("<Delete>", self.remove_selected)
        self.tree.tag_configure("failed", foreground="#b00020")
        self.tree.tag_configure("warn", foreground="#9a6700")
        self.tree.tag_configure("ok", foreground="#1a7f37")
        self.tree.tag_configure("skipped", foreground="#666666")
        paned.add(table_frame, weight=3)

        lower = ttk.Frame(paned)
        paned.add(lower, weight=2)

        opts = ttk.LabelFrame(lower, text="选项", padding=(10, 6))
        opts.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(opts)
        row.pack(fill="x")
        ttk.Radiobutton(row, text="输出到原文件夹", value="same", variable=self.out_mode,
                        command=self._mode_changed).pack(side="left")
        ttk.Radiobutton(row, text="选择输出文件夹：", value="custom", variable=self.out_mode,
                        command=self._mode_changed).pack(side="left", padx=(16, 0))
        self.btn_browse = ttk.Button(row, text="浏览…", command=self.choose_out_dir)
        self.btn_browse.pack(side="left")
        self.out_label = ttk.Label(row, textvariable=self.out_dir, foreground="#555555")
        self.out_label.pack(side="left", padx=(8, 0), fill="x", expand=True)

        ttk.Checkbutton(opts, text="为冷门音轨额外添加兼容音轨（原音轨照样保留）", variable=self.companion).pack(anchor="w", pady=(6, 0))
        ttk.Label(opts, text="DTS / TrueHD / PCM / Vorbis 这类音轨很多播放器和剪辑软件放不出声，会在它后面加一条大家都能放的副本。",
                  font=small, foreground="#666666").pack(anchor="w", padx=(22, 0))
        ttk.Checkbutton(opts, text="字幕/字体另存到旁边", variable=self.sidecars).pack(anchor="w", pady=(4, 0))
        ttk.Label(opts, text="MP4 装不下图形字幕、ASS 特效样式和字体，勾选后会存成同名文件放在 MP4 旁边，这样才能一样不丢。",
                  font=small, foreground="#666666").pack(anchor="w", padx=(22, 0))
        ttk.Checkbutton(opts, text="优化网页播放（文件末尾信息移到开头，大文件会多花一点时间）",
                        variable=self.faststart).pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(opts, text="把每条音轨另存成单独的音频文件（剪映等只认第一条音轨时用）",
                        variable=self.export_audio).pack(anchor="w", pady=(4, 0))
        ttk.Label(opts, text="存到 MP4 旁边的“名字_音轨”文件夹，不重新编码。已经是普通 MP4 的文件（如 OBS 混合 MP4）不转换，只另存音轨。",
                  font=small, foreground="#666666").pack(anchor="w", padx=(22, 0))
        self._mode_changed()

        prog_row = ttk.Frame(lower)
        prog_row.pack(fill="x", pady=(8, 4))
        self.status = ttk.Label(prog_row, text="准备就绪。")
        self.status.pack(side="left")
        self.pbar = ttk.Progressbar(prog_row, mode="determinate", maximum=1000, length=260)
        self.pbar.pack(side="right")

        self.log = ScrolledText(lower, height=9, wrap="word", font=(family, 9), state="disabled",
                                relief="solid", borderwidth=1)
        self.log.pack(fill="both", expand=True)
        self._log(f"{core.APP_NAME} {core.VERSION}：MKV/WebM/FLV/TS 转 MP4，分片 MP4/MOV 转普通 MP4。所有轨道原样保留，不重新压缩画面。")
        missing = core.missing_tools()
        if missing:
            msg = core.missing_tools_message(missing)
            self._log("！" + msg)
            root.after(300, lambda: messagebox.showerror(core.APP_NAME, msg))

    def _mode_changed(self):
        custom = self.out_mode.get() == "custom"
        self.btn_browse.configure(state="normal" if custom else "disabled")
        if custom and not self.out_dir.get():
            self.choose_out_dir()
            if not self.out_dir.get():
                self.out_mode.set("same")
                self.btn_browse.configure(state="disabled")

    def choose_out_dir(self):
        d = filedialog.askdirectory(title="选择输出文件夹")
        if d:
            self.out_dir.set(os.path.normpath(d))
            self.out_mode.set("custom")

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="选择要转换的文件",
            filetypes=[("MKV / FLV / TS / 分片 MP4", INPUT_PATTERNS), ("所有文件", "*.*")])
        if files:
            self.add_paths(files)

    def add_folder(self):
        d = filedialog.askdirectory(title="选择文件夹（会包含子文件夹）")
        if d:
            self.add_paths([d])

    def add_paths(self, paths, then_start=False):
        paths = list(paths)
        self.scanning += 1
        self.status.configure(text="正在查找文件…")
        self._refresh_buttons()

        def scan():
            rows = []
            try:
                for f in core.collect_inputs(paths, recursive=True):
                    try:
                        kind, msg = core.classify(f)
                    except Exception:
                        kind, msg = "skip", "无法读取文件，已跳过"
                    try:
                        size = core.fmt_size(os.path.getsize(f))
                    except OSError:
                        size = "?"
                    rows.append((f, kind, msg, size))
            finally:
                self.q.put(("rows", paths, rows, then_start))

        threading.Thread(target=scan, daemon=True).start()

    def _add_rows(self, paths, rows):
        existing = {os.path.normcase(p["path"]) for p in self.items.values()}
        added = 0
        files = [r[0] for r in rows]
        for f, kind, msg, size in rows:
            if os.path.normcase(f) in existing:
                continue
            existing.add(os.path.normcase(f))
            skip = kind in ("skip", "plain")
            status = msg if skip else "等待"
            iid = self.tree.insert("", "end", values=(os.path.basename(f), KIND_TEXT[kind], size, status, ""),
                                   tags=("skipped",) if skip else ())
            self.items[iid] = {"path": f, "kind": kind, "state": "skipped" if skip else "pending",
                               "result": None}
            added += 1
        ignored = [p for p in paths if os.path.isfile(p) and os.path.splitext(p)[1].lower() not in core.ALL_EXTS]
        for p in ignored:
            self._log(f"跳过 {os.path.basename(p)}：不支持的文件类型")
        if paths and not files:
            self._log("没有找到可以处理的文件（支持 " + " ".join(sorted(core.ALL_EXTS)) + "）")
        if added:
            self._log(f"已添加 {added} 个文件。")
        self.scanning -= 1
        if not self.worker and not self.scanning:
            self.status.configure(text="准备就绪。")
        self._refresh_buttons()

    def remove_selected(self, _event=None):
        if self.worker:
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.items.pop(iid, None)

    def clear(self):
        if self.worker:
            return
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        self.pbar["value"] = 0
        self.status.configure(text="准备就绪。")

    def options(self):
        out = self.out_dir.get() if self.out_mode.get() == "custom" and self.out_dir.get() else None
        return core.Options(out_dir=out, companion=self.companion.get(), sidecars=self.sidecars.get(),
                            faststart=self.faststart.get(), export_audio=self.export_audio.get())

    def start(self):
        if self.worker:
            return
        opts = self.options()
        todo = [iid for iid, it in self.items.items() if it["state"] in ("pending", "cancelled")
                or (opts.export_audio and it["kind"] == "plain" and it["state"] == "skipped" and it["result"] is None)]
        if not todo:
            if not self.items:
                messagebox.showinfo(core.APP_NAME, "请先把文件拖进来，或点“添加文件”。")
            else:
                messagebox.showinfo(core.APP_NAME, "列表里没有需要转换的文件。")
            return
        if opts.out_dir and not os.path.isdir(opts.out_dir):
            messagebox.showerror(core.APP_NAME, "输出文件夹不存在，请重新选择。")
            return
        self.cancel_event = threading.Event()
        jobs = [(iid, self.items[iid]["path"]) for iid in todo]
        for iid, _ in jobs:
            self.items[iid]["state"] = "queued"
            self.tree.set(iid, "status", "排队中")
            self.tree.set(iid, "progress", "")
        self.worker = threading.Thread(target=self._work, args=(jobs, opts), daemon=True)
        self.worker.start()
        self._refresh_buttons()

    def _work(self, jobs, opts):
        done = 0
        for n, (iid, path) in enumerate(jobs, 1):
            if self.cancel_event.is_set():
                self.q.put(("result", iid, None))
                continue
            self.q.put(("begin", iid, n, len(jobs)))
            conv = core.Converter(opts,
                                  log=lambda m: self.q.put(("log", "  " + m)),
                                  progress=lambda f, s, iid=iid: self.q.put(("progress", iid, f, s)),
                                  cancel_event=self.cancel_event)
            self.converter = conv
            r = conv.convert(path)
            self.converter = None
            self.q.put(("result", iid, r))
            done += 1
        self.q.put(("finished",))

    def cancel(self):
        if self.worker:
            self.cancel_event.set()
            conv = self.converter
            if conv:
                conv.cancel()
            self.status.configure(text="正在取消…")

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "add":
            if self.closing:
                return
            self.add_paths(msg[1])
            if test_log_path():
                write_test_log("drop:" + "|".join(msg[1]))
        elif kind == "rows":
            _, paths, rows, then_start = msg
            self._add_rows(paths, rows)
            if then_start and not self.closing:
                self.root.after(200, self.start)
        elif kind == "log":
            self._log(msg[1])
        elif kind == "begin":
            _, iid, n, total = msg
            self.items[iid]["state"] = "running"
            self.tree.set(iid, "status", "转换中")
            self.tree.see(iid)
            self.status.configure(text=f"正在处理第 {n}/{total} 个：{os.path.basename(self.items[iid]['path'])}")
            self._log(f"▶ {self.items[iid]['path']}")
        elif kind == "progress":
            _, iid, frac, stage = msg
            if iid in self.items and self.items[iid]["state"] == "running":
                self.tree.set(iid, "progress", f"{int(frac * 100)}%")
                self.tree.set(iid, "status", stage)
                self.pbar["value"] = int(frac * 1000)
        elif kind == "result":
            _, iid, r = msg
            if iid not in self.items:
                return
            it = self.items[iid]
            if r is None:
                it["state"] = "cancelled"
                self.tree.set(iid, "status", "已取消")
                return
            it["result"] = r
            it["state"] = r.status
            text = STATUS_TEXT.get(r.status, r.status)
            if r.message:
                text += "：" + r.message
            self.tree.set(iid, "status", text)
            self.tree.set(iid, "progress", "100%" if r.status in ("ok", "warn") else "")
            self.tree.item(iid, tags=(r.status,))
            if r.output and os.path.exists(r.output):
                self.last_output_dir = os.path.dirname(r.output)
            elif r.audio_dir and os.path.isdir(r.audio_dir):
                self.last_output_dir = os.path.dirname(r.audio_dir)
            for line in core.result_summary(r).splitlines():
                self._log(line)
        elif kind == "finished":
            self.worker = None
            if self.closing:
                self.root.destroy()
                return
            states = [it["state"] for it in self.items.values()]
            ok = sum(s in ("ok", "warn") for s in states)
            bad = sum(s == "failed" for s in states)
            self.status.configure(text=f"全部处理完：成功 {ok} 个" + (f"，失败 {bad} 个" if bad else "") + "。双击列表里的文件可以看转换报告。")
            self.pbar["value"] = 1000 if ok and not bad else self.pbar["value"]
            self._log("—— 全部处理完 ——")
            self._refresh_buttons()
            if test_log_path():
                write_test_log("ffmpeg:" + str(core.locate_tool("ffmpeg")))
                write_test_log("finished:" + ",".join(states))

    def _refresh_buttons(self):
        running = self.worker is not None
        busy = running or self.scanning > 0
        self.btn_start.configure(state="disabled" if busy or self.closing else "normal")
        self.btn_cancel.configure(state="normal" if running and not self.closing else "disabled")
        self.btn_clear.configure(state="disabled" if busy else "normal")

    def on_close(self):
        if self.closing:
            return
        if self.worker:
            if not messagebox.askyesno(core.APP_NAME, "还在转换中。确定要退出吗？\n没转换完的文件会被删除，源文件不受影响。"):
                return
            self.closing = True
            self.cancel()
            self.status.configure(text="正在清理没转换完的文件，清理完会自动关闭…")
            self._log("正在取消并清理，请稍候…")
            self._refresh_buttons()
            return
        self.root.destroy()

    def open_output(self):
        target = self.last_output_dir
        if not target:
            sel = self.tree.selection() or tuple(self.items.keys())
            for iid in sel:
                it = self.items.get(iid)
                if it:
                    target = self.options().out_dir or os.path.dirname(it["path"])
                    break
        if not target and self.out_mode.get() == "custom":
            target = self.out_dir.get()
        if target and os.path.isdir(target):
            open_path(target)
        else:
            messagebox.showinfo(core.APP_NAME, "还没有输出文件。")

    def open_report(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        r = self.items.get(sel[0], {}).get("result")
        if r and r.report_path and os.path.exists(r.report_path):
            open_path(r.report_path)
        elif r and r.message:
            detail = ("\n\n技术细节（给懂电脑的人看）：\n" + r.tech[-1500:]) if r.tech else ""
            messagebox.showinfo(core.APP_NAME, r.message + detail)


def open_path(path):
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def test_log_path():
    return os.environ.get("MKV2MP4_GUI_TEST_LOG")


def write_test_log(line):
    try:
        with open(test_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main():
    set_dpi_awareness()
    root = tk.Tk()
    root.geometry("1000x760")
    root.minsize(760, 600)
    try:
        icon = os.path.join(core.app_dir(), "app.ico")
        if os.path.exists(icon):
            root.iconbitmap(icon)
    except tk.TclError:
        pass
    args = [a for a in sys.argv[1:] if os.path.exists(a)]
    App(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
