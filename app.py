"""
AnyConvert - a desktop file converter.

Drop files in, pick a format, hit Convert. The engine works out the route,
including two-step ones such as docx -> markdown -> pdf.
"""

import os
import queue
import shutil
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import engine
from engine import Tools, ConvertError
from converters import archives

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

APP_NAME = "AnyConvert"
VERSION = "1.0.0"
COPYRIGHT = "Copyright (C) 2026 Arthur Lubarsky"
HOMEPAGE = "https://github.com/arthuril13/AnyConvert"
EXTRACT = "extract files (folder)"

# Shown at the top of the format list so the usual suspects are one click away.
POPULAR = ["pdf", "png", "jpg", "webp", "gif", "ico", "svg", "mp4", "mp3", "wav",
           "flac", "docx", "txt", "md", "html", "csv", "xlsx", "json", "zip", "7z",
           "iso", "epub"]

BG = "#16171b"
PANEL = "#1e2027"
FIELD = "#2a2d36"
LINE = "#343845"
FG = "#e6e7ea"
MUTED = "#9aa0ab"
ACCENT = "#4f8cff"
OK = "#4ec98f"
BAD = "#ff6b6b"


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


class App:
    def __init__(self, root):
        self.root = root
        self.files = []
        self.q = queue.Queue()
        self.worker = None
        self.cancel = threading.Event()

        root.title(APP_NAME)
        # Geometry is in real pixels but the fonts follow the display scaling,
        # so grow the window by the same factor or the log falls off the bottom.
        f = max(1.0, root.winfo_fpixels("1i") / 96.0)
        root.geometry("%dx%d" % (int(940 * f), int(700 * f)))
        root.minsize(int(720 * f), int(560 * f))
        root.configure(bg=BG)
        self._icon()
        self._style()
        root.after(10, self._dark_titlebar)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=12, pady=12)
        self.tab_convert = ttk.Frame(nb, padding=14)
        self.tab_tools = ttk.Frame(nb, padding=14)
        nb.add(self.tab_convert, text="  Convert  ")
        nb.add(self.tab_tools, text="  Tools  ")

        self._build_convert(self.tab_convert)
        self._build_tools(self.tab_tools)

        if HAS_DND:
            root.drop_target_register(DND_FILES)
            root.dnd_bind("<<Drop>>", self.on_drop)

        for path in sys.argv[1:]:
            self.add_paths([path])

        self.root.after(80, self._pump)

    # ------------------------------------------------------------------ chrome

    def _icon(self):
        ico = engine.APP_DIR / "icon.ico"
        if ico.is_file():
            try:
                self.root.iconbitmap(str(ico))
            except Exception:
                pass

    def _dark_titlebar(self):
        """Match the Windows title bar to the dark window underneath it."""
        if os.name != "nt":
            return
        import ctypes
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            on = ctypes.c_int(1)
            for attribute in (20, 19):      # 20 on current Windows, 19 pre-20H1
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attribute, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                    break
        except Exception:
            pass

    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=PANEL, foreground=FG, fieldbackground=FIELD,
                    bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL,
                    font=("Segoe UI", 10))
        s.configure("TFrame", background=PANEL)
        s.configure("TLabel", background=PANEL, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Link.TLabel", foreground=ACCENT)
        s.configure("Head.TLabel", font=("Segoe UI Semibold", 12))
        s.configure("Ok.TLabel", foreground=OK)
        s.configure("Bad.TLabel", foreground=BAD)
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=BG, foreground=MUTED,
                    padding=(16, 8), borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", PANEL)],
              foreground=[("selected", FG)])
        s.configure("TButton", background=FIELD, foreground=FG, borderwidth=0,
                    padding=(12, 7), focuscolor=PANEL)
        s.map("TButton", background=[("active", LINE), ("disabled", PANEL)],
              foreground=[("disabled", MUTED)])
        s.configure("Go.TButton", background=ACCENT, foreground="#ffffff",
                    font=("Segoe UI Semibold", 11), padding=(24, 10))
        s.map("Go.TButton", background=[("active", "#6ba0ff"), ("disabled", LINE)])
        s.configure("TCombobox", arrowcolor=FG, padding=6)
        s.map("TCombobox", fieldbackground=[("readonly", FIELD)],
              background=[("readonly", FIELD)], foreground=[("readonly", FG)])
        s.configure("TEntry", padding=6, insertcolor=FG)
        s.configure("Treeview", background=FIELD, fieldbackground=FIELD,
                    foreground=FG, rowheight=26, borderwidth=0)
        s.configure("Treeview.Heading", background=PANEL, foreground=MUTED,
                    relief="flat", padding=(8, 6))
        s.map("Treeview", background=[("selected", ACCENT)],
              foreground=[("selected", "#ffffff")])
        s.configure("TProgressbar", background=ACCENT, troughcolor=FIELD,
                    borderwidth=0, thickness=6)
        s.configure("TCheckbutton", background=PANEL, foreground=MUTED,
                    indicatorcolor=FIELD, indicatorrelief="flat", focuscolor=PANEL)
        s.map("TCheckbutton", background=[("active", PANEL)],
              indicatorcolor=[("selected", ACCENT), ("active", LINE)],
              foreground=[("active", FG)])
        s.configure("Vertical.TScrollbar", background=LINE, troughcolor=PANEL,
                    bordercolor=PANEL, arrowcolor=MUTED, borderwidth=0)
        s.map("Vertical.TScrollbar", background=[("active", MUTED)])

    # ----------------------------------------------------------- convert tab

    def _build_convert(self, parent):
        hint = ("Drop files anywhere on this window" if HAS_DND
                else "Add files to get started")
        ttk.Label(parent, text=hint, style="Muted.TLabel").pack(anchor="w")

        listwrap = ttk.Frame(parent)
        listwrap.pack(fill="both", expand=True, pady=(8, 10))

        cols = ("name", "type", "size", "path")
        self.tree = ttk.Treeview(listwrap, columns=cols, show="headings", height=9)
        for c, txt, w, anchor in (("name", "File", 300, "w"), ("type", "From", 70, "w"),
                                  ("size", "Size", 80, "e"), ("path", "Folder", 330, "w")):
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor=anchor, stretch=(c in ("name", "path")))
        sb = ttk.Scrollbar(listwrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Delete>", lambda e: self.remove_selected())

        bar = ttk.Frame(parent)
        bar.pack(fill="x")
        ttk.Button(bar, text="Add files", command=self.pick_files).pack(side="left")
        ttk.Button(bar, text="Add folder", command=self.pick_folder).pack(side="left", padx=6)
        ttk.Button(bar, text="Remove", command=self.remove_selected).pack(side="left")
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="left", padx=6)
        self.count = ttk.Label(bar, text="no files", style="Muted.TLabel")
        self.count.pack(side="right")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=12)

        opts = ttk.Frame(parent)
        opts.pack(fill="x")
        opts.columnconfigure(1, weight=1)

        ttk.Label(opts, text="Convert to").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.fmt = ttk.Combobox(opts, state="normal", width=26)
        self.fmt.grid(row=0, column=1, sticky="w")
        self.fmt.bind("<<ComboboxSelected>>", lambda e: self.show_route())
        self.fmt.bind("<KeyRelease>", lambda e: self.show_route())
        self.route = ttk.Label(opts, text="", style="Muted.TLabel")
        self.route.grid(row=0, column=2, sticky="w", padx=14)

        ttk.Label(opts, text="Save to").grid(row=1, column=0, sticky="w",
                                             padx=(0, 10), pady=(10, 0))
        dest = ttk.Frame(opts)
        dest.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(10, 0))
        dest.columnconfigure(0, weight=1)
        self.outdir = tk.StringVar(value="")
        self.out_entry = ttk.Entry(dest, textvariable=self.outdir)
        self.out_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(dest, text="Browse", command=self.pick_out).grid(row=0, column=1, padx=6)
        self.same = tk.BooleanVar(value=True)
        ttk.Checkbutton(dest, text="same folder as the file", variable=self.same,
                        command=self._toggle_out).grid(row=0, column=2)
        self._toggle_out()

        go = ttk.Frame(parent)
        go.pack(fill="x", pady=(16, 8))
        self.btn = ttk.Button(go, text="Convert", style="Go.TButton", command=self.start)
        self.btn.pack(side="left")
        self.status = ttk.Label(go, text="", style="Muted.TLabel")
        self.status.pack(side="left", padx=14)
        self.open_btn = ttk.Button(go, text="Open output folder", command=self.open_out)
        self.open_btn.pack(side="right")

        self.bar = ttk.Progressbar(parent, mode="determinate", maximum=1000)
        self.bar.pack(fill="x", pady=(0, 8))

        logwrap = ttk.Frame(parent)
        logwrap.pack(fill="both", expand=True)
        self.log = tk.Text(logwrap, height=7, bg=FIELD, fg=MUTED, bd=0,
                           font=("Consolas", 9), wrap="word", padx=10, pady=8,
                           insertbackground=FG)
        lsb = ttk.Scrollbar(logwrap, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        self.log.tag_configure("ok", foreground=OK)
        self.log.tag_configure("bad", foreground=BAD)
        self.log.tag_configure("head", foreground=FG)

        self.write("%s ready. %d converters loaded, %d available with the tools "
                   "you have installed."
                   % (APP_NAME, len(engine.RULES),
                      sum(1 for r in engine.RULES if r.available())))
        if not HAS_DND:
            self.write("Drag and drop is off (tkinterdnd2 not installed) - "
                       "use Add files.")

    # -------------------------------------------------------------- tools tab

    def _build_tools(self, parent):
        ttk.Label(parent, text="Helper programs", style="Head.TLabel").pack(anchor="w")
        ttk.Label(parent, style="Muted.TLabel", wraplength=820, justify="left",
                  text="AnyConvert handles images, documents, data files and fonts on "
                       "its own. These extras unlock the rest. Install one, then press "
                       "Rescan - no restart needed.").pack(anchor="w", pady=(4, 14))

        self.toolrows = ttk.Frame(parent)
        self.toolrows.pack(fill="x")

        row = ttk.Frame(parent)
        row.pack(fill="x", pady=16)
        ttk.Button(row, text="Rescan", command=self.rescan).pack(side="left")
        ttk.Button(row, text="Copy install commands",
                   command=self.copy_commands).pack(side="left", padx=8)
        ttk.Button(row, text="What can it convert?",
                   command=self.show_formats).pack(side="left")

        # AGPL asks that the program itself carry the notice, not just the repo
        about = ttk.Frame(parent)
        about.pack(side="bottom", fill="x", pady=(20, 0))
        ttk.Label(about, style="Muted.TLabel", justify="left",
                  text="%s %s   %s\nFree software under the GNU AGPL v3, with "
                       "no warranty of any kind. Source code:"
                       % (APP_NAME, VERSION, COPYRIGHT)).pack(anchor="w")
        link = ttk.Label(about, text=HOMEPAGE, style="Link.TLabel", cursor="hand2")
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda e: webbrowser.open(HOMEPAGE))

        self.refresh_tools()

    def refresh_tools(self):
        for w in self.toolrows.winfo_children():
            w.destroy()
        self.toolrows.columnconfigure(3, weight=1)
        for i, (key, label, why, cmd, ok) in enumerate(Tools.status()):
            ttk.Label(self.toolrows, text="installed" if ok else "missing",
                      style="Ok.TLabel" if ok else "Bad.TLabel", width=10).grid(
                          row=i, column=0, sticky="w", pady=4)
            ttk.Label(self.toolrows, text=label, width=14).grid(row=i, column=1, sticky="w")
            ttk.Label(self.toolrows, text=why, style="Muted.TLabel", width=26).grid(
                row=i, column=2, sticky="w")
            path = getattr(Tools, key) or cmd
            ttk.Label(self.toolrows, text=path, style="Muted.TLabel",
                      font=("Consolas", 9)).grid(row=i, column=3, sticky="w", padx=8)

    def rescan(self):
        Tools.scan()
        self.refresh_tools()
        self.update_formats()
        self.write("Rescanned. %d of %d converters available."
                   % (sum(1 for r in engine.RULES if r.available()), len(engine.RULES)))

    def copy_commands(self):
        cmds = [cmd for k, l, w, cmd, ok in Tools.status()
                if not ok and cmd.startswith("winget")]
        if not cmds:
            messagebox.showinfo(APP_NAME, "Everything is already installed.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(cmds))
        messagebox.showinfo(APP_NAME,
                            "Copied %d command(s).\n\nPaste them into PowerShell:\n\n%s"
                            % (len(cmds), "\n".join(cmds)))

    def show_formats(self):
        src = engine._norm(self.files[0]) if self.files else None
        win = tk.Toplevel(self.root)
        win.title("Supported formats")
        win.configure(bg=PANEL)
        win.geometry("620x520")
        txt = tk.Text(win, bg=FIELD, fg=FG, bd=0, font=("Consolas", 9),
                      wrap="word", padx=12, pady=12)
        txt.pack(fill="both", expand=True, padx=12, pady=12)
        if src:
            targets = engine.targets_for(src)
            txt.insert("end", "From .%s you can make:\n\n%s\n\n%s\n\n"
                       % (src, "  ".join("." + t for t in targets), "-" * 60))
        txt.insert("end", "Every converter currently loaded:\n\n")
        for r in sorted(engine.RULES, key=lambda r: r.label):
            mark = "  " if r.available() else "x "
            srcs = " ".join(sorted(r.srcs))
            dsts = " ".join(sorted(r.dsts))
            txt.insert("end", "%s%-18s %s\n     -> %s\n\n" % (mark, r.label, srcs[:300], dsts[:300]))
        txt.insert("end", "\nLines marked x need a helper program from the Tools tab.\n")
        txt.configure(state="disabled")

    # ----------------------------------------------------------------- files

    def on_drop(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))

    def pick_files(self):
        paths = filedialog.askopenfilenames(title="Pick files to convert")
        self.add_paths(paths)

    def pick_folder(self):
        d = filedialog.askdirectory(title="Pick a folder")
        if d:
            self.add_paths([str(p) for p in sorted(Path(d).iterdir()) if p.is_file()])

    def pick_out(self):
        d = filedialog.askdirectory(title="Where should the results go?")
        if d:
            self.outdir.set(d)
            self.same.set(False)
            self._toggle_out()

    def _toggle_out(self):
        self.out_entry.configure(state="disabled" if self.same.get() else "normal")

    def add_paths(self, paths):
        added = 0
        for p in paths:
            p = Path(str(p).strip('"'))
            if p.is_dir():
                for f in sorted(p.iterdir()):
                    if f.is_file():
                        added += self._add_one(f)
            elif p.is_file():
                added += self._add_one(p)
        if added:
            self.update_formats()
        self._count()

    def _add_one(self, p):
        p = p.resolve()
        if p in self.files:
            return 0
        self.files.append(p)
        try:
            size = human(p.stat().st_size)
        except OSError:
            size = "?"
        self.tree.insert("", "end", iid=str(p),
                         values=(p.name, engine._norm(p.name) or "-", size, str(p.parent)))
        return 1

    def remove_selected(self):
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.files = [f for f in self.files if str(f) != iid]
        self.update_formats()
        self._count()

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self.files.clear()
        self.update_formats()
        self._count()

    def _count(self):
        n = len(self.files)
        self.count.configure(text="no files" if not n else
                             "%d file%s" % (n, "" if n == 1 else "s"))

    # --------------------------------------------------------------- formats

    def update_formats(self):
        if not self.files:
            self.fmt["values"] = []
            self.route.configure(text="")
            return
        sets = [set(engine.targets_for(engine._norm(f.name))) for f in self.files]
        common = set.intersection(*sets) if sets else set()
        if not common:
            common = set().union(*sets)
        extractable = any(engine._norm(f.name) in
                          engine._exts(archives.READ_7Z + " " + archives.READ_PY)
                          for f in self.files)
        head = [e for e in POPULAR if e in common]
        rest = sorted(common - set(head))
        values = head + (["-" * 18] if head and rest else []) + rest
        if extractable:
            values = [EXTRACT] + values
        self.fmt["values"] = values
        if self.fmt.get() not in values:
            self.fmt.set(values[0] if values else "")
        self.show_route()

    def show_route(self):
        target = self.fmt.get().strip().lstrip(".")
        if not self.files or not target or target.startswith("---"):
            self.route.configure(text="")
            return
        if target == EXTRACT:
            self.route.configure(text="unpacks each archive into its own folder")
            return
        src = engine._norm(self.files[0].name)
        route = engine.describe(src, target)
        if route:
            hops = route.count("->")
            self.route.configure(
                text=route + ("" if hops < 2 else "   (two steps)"))
        else:
            need = engine.why_unavailable(src, target)
            self.route.configure(
                text="needs " + ", ".join(Tools.LABELS[t][0] for t in need)
                if need else "no route from .%s" % src)

    # --------------------------------------------------------------- convert

    def start(self):
        if self.worker and self.worker.is_alive():
            self.cancel.set()
            self.status.configure(text="stopping...")
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "Add some files first.")
            return
        target = self.fmt.get().strip().lstrip(".")
        if not target or target.startswith("---"):
            messagebox.showinfo(APP_NAME, "Pick a format to convert to.")
            return
        outdir = None if self.same.get() else self.outdir.get().strip()
        if outdir and not Path(outdir).is_dir():
            messagebox.showerror(APP_NAME, "That output folder does not exist.")
            return

        self.cancel.clear()
        self.btn.configure(text="Stop")
        self.bar["value"] = 0
        self.write("")
        self.write("Converting %d file(s) to %s" % (len(self.files), target), "head")
        self.worker = threading.Thread(target=self._work,
                                       args=(list(self.files), target, outdir),
                                       daemon=True)
        self.worker.start()

    def _work(self, files, target, outdir):
        done = failed = 0
        for i, src in enumerate(files):
            if self.cancel.is_set():
                self.q.put(("log", "Stopped.", "bad"))
                break
            base = i / float(len(files))
            span = 1.0 / len(files)
            self.q.put(("status", "%s  (%d of %d)" % (src.name, i + 1, len(files))))
            try:
                if target == EXTRACT:
                    dest = Path(outdir or src.parent) / src.stem
                    if dest.exists():           # do not merge into an old unpack
                        dest = engine._unique(dest)
                    archives.extract_any(src, dest)
                    n = sum(1 for _ in dest.rglob("*"))
                    self.q.put(("log", "%s  ->  %s\\  (%d items)"
                                % (src.name, dest.name, n), "ok"))
                    for note in engine.take_notes():
                        self.q.put(("log", "        " + note))
                else:
                    out = (Path(outdir) / (src.stem + "." + engine._ext_suffix(target))
                           if outdir else None)
                    result = engine.convert(
                        src, target, out_path=out,
                        progress=lambda m, f: self.q.put(("prog", base + f * span, m)))
                    self.q.put(("log", "%s  ->  %s  (%s)"
                                % (src.name, result.name, human(result.stat().st_size)),
                                "ok"))
                    for n in engine.take_notes():
                        self.q.put(("log", "        " + n))
                    self.last_out = result.parent
                done += 1
            except ConvertError as e:
                failed += 1
                self.q.put(("log", "%s  ->  failed: %s" % (src.name, e), "bad"))
            except Exception as e:
                failed += 1
                self.q.put(("log", "%s  ->  error: %s: %s"
                            % (src.name, type(e).__name__, e), "bad"))
                self.q.put(("log", traceback.format_exc(limit=3).strip(), "bad"))
            self.q.put(("prog", (i + 1) / float(len(files)), ""))
        self.q.put(("finish", done, failed))

    def _pump(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.write(msg[1], msg[2] if len(msg) > 2 else None)
                elif kind == "status":
                    self.status.configure(text=msg[1])
                elif kind == "prog":
                    self.bar["value"] = max(0, min(1000, int(msg[1] * 1000)))
                elif kind == "finish":
                    done, failed = msg[1], msg[2]
                    self.btn.configure(text="Convert")
                    self.status.configure(
                        text="%d done%s" % (done, ", %d failed" % failed if failed else ""))
                    self.write("Finished: %d converted, %d failed." % (done, failed),
                               "bad" if failed else "ok")
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def open_out(self):
        target = getattr(self, "last_out", None)
        if not target:
            target = (Path(self.outdir.get()) if not self.same.get() and self.outdir.get()
                      else (self.files[0].parent if self.files else Path.home()))
        try:
            os.startfile(str(target))
        except Exception:
            webbrowser.open(str(target))

    def write(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")


def crisp():
    """Tell Windows we handle scaling ourselves, otherwise Tk renders blurry."""
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def verify():
    """
    AnyConvert.exe --verify

    Runs a few conversions in a temp folder and writes verify-report.txt beside
    the exe. Useful for checking a fresh copy, or a machine you just installed
    the helper tools on.
    """
    import tempfile
    from PIL import Image, ImageDraw

    work = Path(tempfile.mkdtemp(prefix="anyconvert_verify_"))
    lines = ["%s verification" % APP_NAME, ""]
    for key, label, why, cmd, ok in Tools.status():
        lines.append("  %-9s %-13s %s" % ("found" if ok else "missing", label,
                                          getattr(Tools, key) or ""))
    lines += ["", "  %d converters loaded, %d available"
              % (len(engine.RULES), sum(1 for r in engine.RULES if r.available())), ""]

    im = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([10, 10, 190, 110], fill=(255, 100, 60, 230))
    (work / "sample.png").parent.mkdir(exist_ok=True)
    im.save(work / "sample.png")
    (work / "sample.md").write_text("# Title\n\nSome text.\n\n- a\n- b\n", encoding="utf-8")
    (work / "sample.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    cases = [("sample.png", "jpg"), ("sample.png", "webp"), ("sample.png", "ico"),
             ("sample.png", "pdf"), ("sample.md", "html"), ("sample.md", "pdf"),
             ("sample.md", "docx"), ("sample.csv", "xlsx"), ("sample.csv", "json"),
             ("sample.png", "zip"), ("sample.png", "iso")]
    if Tools.ffmpeg:
        engine.run([Tools.ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=1", str(work / "sample.wav")])
        cases += [("sample.wav", "mp3"), ("sample.wav", "flac")]

    good = bad = 0
    for name, target in cases:
        try:
            out = engine.convert(work / name, target, overwrite=True)
            lines.append("  ok     %-14s -> %-5s %8d bytes"
                         % (name, target, out.stat().st_size))
            good += 1
        except Exception as e:
            lines.append("  FAILED %-14s -> %-5s %s" % (name, target, e))
            bad += 1

    lines += ["", "  %d passed, %d failed" % (good, bad)]
    report = "\n".join(lines) + "\n"
    dest = engine.APP_DIR / "verify-report.txt"
    try:
        dest.write_text(report, encoding="utf-8")
    except OSError:
        dest = Path.cwd() / "verify-report.txt"
        dest.write_text(report, encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(report)
    return 0 if bad == 0 else 1


def main():
    if "--verify" in sys.argv:
        sys.exit(verify())
    crisp()
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    try:                                    # scale fonts to match the display
        scale = root.winfo_fpixels("1i") / 72.0
        root.tk.call("tk", "scaling", scale)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
