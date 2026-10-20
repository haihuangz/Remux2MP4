import ctypes
import ctypes.wintypes as wt
import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
EXE = os.path.join(os.environ.get("MKV2MP4_DIST_DIR") or os.path.join(ROOT, "dist"), "视频转MP4", "视频转MP4.exe")
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def windows_of(pid):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append((hwnd, buf.value, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(cb, 0)
    return found


def child_pids(pid):
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}').ProcessId"],
                       capture_output=True, encoding="utf-8", errors="replace")
    return [int(x) for x in r.stdout.split() if x.strip().isdigit()]


def shot(hwnd, rect, path):
    user32.ShowWindow(hwnd, 9)
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 3)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.0)
    l, t, r, b = rect
    ps = (
        "Add-Type -AssemblyName System.Drawing;"
        f"$bmp=New-Object System.Drawing.Bitmap({r - l},{b - t});"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        f"$g.CopyFromScreen({l},{t},0,0,$bmp.Size);"
        f"$bmp.Save('{path}',[System.Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$bmp.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def find_window(pid, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for p in [pid] + child_pids(pid):
            w = windows_of(p)
            if w:
                return p, w
        time.sleep(1)
    return None, []


def run(args, png, wait_log=None):
    env = dict(os.environ)
    if wait_log:
        env["MKV2MP4_GUI_TEST_LOG"] = wait_log
        if os.path.exists(wait_log):
            os.remove(wait_log)
    p = subprocess.Popen([EXE] + args, env=env)
    wpid, wins = find_window(p.pid)
    print("launched pid", p.pid, "window pid", wpid, "windows", wins)
    if wait_log:
        t0 = time.time()
        while time.time() - t0 < 120:
            if os.path.exists(wait_log) and "finished:" in open(wait_log, encoding="utf-8").read():
                break
            time.sleep(1)
        time.sleep(1.5)
        print("log:", open(wait_log, encoding="utf-8").read().strip() if os.path.exists(wait_log) else None)
    if wins:
        hwnd, title, rect = max(wins, key=lambda w: (w[2][2] - w[2][0]) * (w[2][3] - w[2][1]))
        shot(hwnd, rect, png)
        print("screenshot", png, title, rect)
    alive = p.poll() is None
    p.kill()
    p.wait(timeout=10)
    print("was alive before close:", alive)


if __name__ == "__main__":
    d = os.path.join(OUT, "gui_src")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    src = os.path.join(d, "OBS 录像 六轨.mkv")
    shutil.copy2(os.path.join(HERE, "media", "obs", "obs_h264_6aac.mkv"), src)
    run([src], os.path.join(OUT, "gui.png"), os.path.join(OUT, "gui_log.txt"))
    print("outputs:", sorted(os.listdir(d)))
    run([], os.path.join(OUT, "gui_noargs.png"))
