"""
AnyConvert engine - format detection, converter registry and chaining.

A "rule" knows how to turn one set of extensions into another. Rules form a
graph; if there is no direct rule for src -> dst we look for a short chain
(e.g. docx -> html -> pdf). Rules that need an external tool are hidden while
that tool is missing, so the UI only offers conversions that can actually run.
"""

import os
import re
import sys
import csv
import json
import shutil
import zipfile
import tarfile
import tempfile
import subprocess
from pathlib import Path
from collections import deque

IS_FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if IS_FROZEN else Path(__file__).resolve().parent
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


# --------------------------------------------------------------------------
# external tools
# --------------------------------------------------------------------------

def _find(names, candidates=()):
    """First hit on PATH, then the first literal path that exists."""
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None


def _script_dirs():
    dirs = [Path(sys.executable).parent / "Scripts"]
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    if base.is_dir():
        dirs += [p / "Scripts" for p in base.iterdir() if p.is_dir()]
    return dirs


def _find_ffmpeg(name="ffmpeg"):
    p = _find([name])
    if p:
        return p
    for d in _script_dirs():
        c = d / (name + ".exe")
        if c.is_file():
            return str(c)
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return None


class Tools:
    """Detected helper binaries. Re-scannable so the UI can refresh after installs."""

    ffmpeg = ffprobe = sevenzip = soffice = dmg2img = qemu_img = calibre = None

    LABELS = {
        "ffmpeg":   ("FFmpeg", "audio and video", "winget install Gyan.FFmpeg"),
        "sevenzip": ("7-Zip", "archives, ISO, DMG", "winget install 7zip.7zip"),
        "soffice":  ("LibreOffice", "Office docs, best quality", "winget install TheDocumentFoundation.LibreOffice"),
        "dmg2img":  ("dmg2img", "raw DMG to ISO (optional)", "put dmg2img.exe next to this app"),
        "qemu_img": ("qemu-img", "VHD / VMDK / QCOW2", "winget install SoftwareFreedomConservancy.QEMU"),
        "calibre":  ("Calibre", "EPUB / MOBI / AZW3", "winget install calibre.calibre"),
    }

    @classmethod
    def scan(cls):
        cls.ffmpeg = _find_ffmpeg("ffmpeg")
        cls.ffprobe = _find_ffmpeg("ffprobe")
        cls.sevenzip = _find(["7z", "7za"], [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
            str(APP_DIR / "7z.exe"),
        ])
        cls.soffice = _find(["soffice"], [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ])
        cls.dmg2img = _find(["dmg2img"], [str(APP_DIR / "dmg2img.exe")])
        cls.qemu_img = _find(["qemu-img"], [
            r"C:\Program Files\qemu\qemu-img.exe",
            str(APP_DIR / "qemu-img.exe"),
        ])
        cls.calibre = _find(["ebook-convert"], [
            r"C:\Program Files\Calibre2\ebook-convert.exe",
            r"C:\Program Files (x86)\Calibre2\ebook-convert.exe",
        ])

    @classmethod
    def has(cls, key):
        return bool(getattr(cls, key, None))

    @classmethod
    def status(cls):
        return [(k, lbl, why, cmd, cls.has(k)) for k, (lbl, why, cmd) in cls.LABELS.items()]


Tools.scan()


class ConvertError(Exception):
    pass


# Converters use note() to report things worth telling the user that are not
# failures - files skipped, names changed. convert() clears them on the way in,
# and the caller collects them afterwards with take_notes().
_local = __import__("threading").local()


def note(message):
    if getattr(_local, "notes", None) is None:
        _local.notes = []
    _local.notes.append(message)


def take_notes():
    notes = getattr(_local, "notes", None) or []
    _local.notes = []
    return notes


def run_soft(cmd, timeout=3600, cwd=None):
    """Run a helper binary and hand back (exit code, output) without raising."""
    cmd = [str(c) for c in cmd]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       creationflags=NO_WINDOW, timeout=timeout, cwd=cwd)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def run(cmd, timeout=3600, cwd=None):
    """Run a helper binary, raising with its own error text on failure."""
    code, text = run_soft(cmd, timeout, cwd)
    if code != 0:
        tail = "\n".join(text.strip().splitlines()[-12:])
        raise ConvertError(tail or "%s failed (exit %d)" % (Path(cmd[0]).name, code))
    return text


# --------------------------------------------------------------------------
# rule registry
# --------------------------------------------------------------------------

def _exts(spec):
    if isinstance(spec, str):
        spec = spec.split()
    return frozenset(e.lower().lstrip(".") for e in spec)


class Rule:
    def __init__(self, fn, srcs, dsts, need, cost, label, chainable):
        self.fn, self.srcs, self.dsts = fn, srcs, dsts
        self.need, self.cost, self.label, self.chainable = need, cost, label, chainable

    def available(self):
        return all(Tools.has(t) for t in self.need)

    def missing(self):
        return [t for t in self.need if not Tools.has(t)]


RULES = []


def rule(srcs, dsts, need=(), cost=10, label="", chainable=True):
    """Register a converter. cost breaks ties, lower wins."""
    def deco(fn):
        RULES.append(Rule(fn, _exts(srcs), _exts(dsts), tuple(need), cost,
                          label or fn.__name__, chainable))
        return fn
    return deco


def _norm(path_or_ext):
    """Extension of a name, collapsing tar.gz and friends to one token."""
    e = str(path_or_ext).lower()
    if "." in e:
        low = e.replace("\\", "/").split("/")[-1]
        for multi in ("tar.gz", "tar.bz2", "tar.xz"):
            if low.endswith("." + multi) or low == multi:
                return multi.replace(".", "")
        e = low.rsplit(".", 1)[-1]
    return e.lstrip(".")


def _ext_suffix(e):
    return {"targz": "tar.gz", "tarbz2": "tar.bz2", "tarxz": "tar.xz"}.get(e, e)


# --------------------------------------------------------------------------
# graph search
# --------------------------------------------------------------------------

def _edges(src, for_chain):
    out = {}
    for r in RULES:
        if not (src in r.srcs or "*" in r.srcs) or not r.available():
            continue
        if for_chain and not r.chainable:
            continue
        for d in r.dsts:
            if d == src:
                continue
            if d not in out or r.cost < out[d].cost:
                out[d] = r
    return out


def find_path(src, dst, max_steps=3):
    """Cheapest rule chain from src to dst, or None."""
    src, dst = _norm(src), _norm(dst)
    if src == dst:
        return []
    direct = [r for r in RULES
              if (src in r.srcs or "*" in r.srcs) and dst in r.dsts and r.available()]
    if direct:
        return [(min(direct, key=lambda r: r.cost), src, dst)]

    seen = {src}
    queue = deque([(src, [])])
    while queue:
        node, path = queue.popleft()
        if len(path) >= max_steps:
            continue
        for nxt, r in _edges(node, for_chain=True).items():
            if nxt in seen:
                continue
            step = path + [(r, node, nxt)]
            if nxt == dst:
                return step
            seen.add(nxt)
            queue.append((nxt, step))
    return None


def targets_for(src, max_steps=2):
    """Every extension reachable from src, for the UI dropdown."""
    src = _norm(src)
    reach, seen = set(), {src}
    frontier = deque([(src, 0)])
    while frontier:
        node, depth = frontier.popleft()
        for nxt, r in _edges(node, for_chain=True).items():
            reach.add(nxt)
            if nxt not in seen and depth + 1 < max_steps:
                seen.add(nxt)
                frontier.append((nxt, depth + 1))
    for r in RULES:                        # direct-only rules, e.g. any -> zip
        if (src in r.srcs or "*" in r.srcs) and r.available() and not r.chainable:
            reach |= r.dsts
    reach.discard(src)
    return sorted(reach)


def why_unavailable(src, dst):
    """Tools that would unlock src -> dst, if a rule is blocked only on tools."""
    src, dst = _norm(src), _norm(dst)
    for r in RULES:
        if (src in r.srcs or "*" in r.srcs) and dst in r.dsts and r.missing():
            return r.missing()
    return []


def describe(src, dst):
    """Human readable route, for the log."""
    chain = find_path(src, dst)
    if not chain:
        return None
    return " -> ".join([chain[0][1]] + [b for _, _, b in chain])


def convert(src, dst_ext, out_path=None, progress=None, overwrite=False):
    """Convert one file. Returns the output Path."""
    src = Path(src)
    if not src.is_file():
        raise ConvertError("no such file: %s" % src)
    dst_ext = _norm(dst_ext)
    chain = find_path(src.name, dst_ext)
    if chain is None:
        need = why_unavailable(src.name, dst_ext)
        if need:
            names = ", ".join(Tools.LABELS[t][0] for t in need)
            raise ConvertError("%s to %s needs %s (see the Tools tab)"
                               % (_norm(src.name), dst_ext, names))
        raise ConvertError("no converter for %s to %s" % (_norm(src.name), dst_ext))
    if not chain:
        raise ConvertError("source is already .%s" % dst_ext)

    out = Path(out_path) if out_path else src.with_name(src.stem + "." + _ext_suffix(dst_ext))
    if out.resolve() == src.resolve():
        out = out.with_name(out.stem + "_converted" + out.suffix)
    if out.exists() and not overwrite:
        out = _unique(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    take_notes()
    tmpdir = Path(tempfile.mkdtemp(prefix="anyconv_"))
    try:
        cur = src
        for i, (r, a, b) in enumerate(chain):
            last = i == len(chain) - 1
            step_out = out if last else tmpdir / ("step%d.%s" % (i, _ext_suffix(b)))
            if progress:
                progress("%s to %s%s" % (a, b, "" if last else " (intermediate)"),
                         i / float(len(chain)))
            r.fn(Path(cur), Path(step_out), b)
            if not Path(step_out).exists():
                raise ConvertError("step %s to %s produced no file" % (a, b))
            cur = Path(step_out)
        if progress:
            progress("done", 1.0)
        return out
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _unique(p):
    p = Path(p)
    stem, suf, n = p.stem, p.suffix, 2
    while p.exists():
        p = p.with_name("%s (%d)%s" % (stem, n, suf))
        n += 1
    return p


def _tmpdir():
    return Path(tempfile.mkdtemp(prefix="anyconv_step_"))


# converters register themselves on import
from converters import images, media, documents, data, archives, diskimages, fonts  # noqa: E402,F401
