"""Archives. 7-Zip does the reading when present; Python handles the rest."""

import re
import gzip
import bz2
import lzma
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

import engine
from engine import rule, run, Tools, ConvertError

# 7-Zip opens all of these. Without it we fall back to the Python formats.
READ_7Z = ("zip 7z rar rar5 tar gz tgz bz2 tbz tbz2 xz txz lzma lz4 zst tzst "
           "cab arj lzh lha z cpio rpm deb msi chm wim swm esd xar pkg "
           "jar war apk xpi crx nupkg epub odt ods odp docx xlsx pptx "
           "targz tarbz2 tarxz zipx alz ace uue gzip")

READ_PY = "zip tar gz tgz bz2 tbz xz txz targz tarbz2 tarxz jar apk epub docx xlsx pptx"

WRITE = "zip 7z tar targz tarbz2 tarxz gz bz2 xz wim"
WRITE_PY = "zip tar targz tarbz2 tarxz gz bz2 xz"

SOLID = {"gz", "bz2", "xz", "lzma", "zst", "lz4"}      # compress one file, no container

_TAR_MODE = {"tar": "w", "targz": "w:gz", "tarbz2": "w:bz2", "tarxz": "w:xz",
             "tgz": "w:gz", "tbz": "w:bz2", "txz": "w:xz"}


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------

def _sevenzip_extract(src, dest):
    """
    Unpack with 7-Zip, tolerating the exit code it returns for entries it would
    not write. A macOS DMG is full of symlinks pointing outside the image, and
    7-Zip refuses those on Windows and then exits non-zero - but everything else
    came out fine, so only an empty result counts as a real failure.
    """
    code, out = engine.run_soft(
        [Tools.sevenzip, "x", "-y", "-bd", "-o" + str(dest), str(src)], timeout=7200)
    if code == 0:
        return
    if not any(Path(dest).iterdir()):
        tail = "\n".join(out.strip().splitlines()[-12:])
        raise ConvertError(tail or "7-Zip could not open that file (exit %d)" % code)
    m = re.search(r"Sub items Errors:\s*(\d+)", out)
    engine.note("7-Zip skipped %s entr%s it could not write on Windows "
                "(usually macOS symlinks)."
                % (m.group(1) if m else "some", "y" if m and m.group(1) == "1" else "ies"))


def extract_any(src, dest):
    """Unpack src into dest (created if needed). Returns dest."""
    src, dest = Path(src), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    ext = src.name.lower()

    if Tools.sevenzip:
        _sevenzip_extract(src, dest)
        # .tar.gz and friends unwrap one layer at a time
        for _ in range(2):
            inner = [p for p in dest.iterdir() if p.is_file()
                     and p.suffix.lower() in (".tar", ".hfs", ".hfsx", ".cpio", ".wim")]
            if len(inner) != 1 or len(list(dest.iterdir())) != 1:
                break
            tmp = Path(tempfile.mkdtemp(prefix="anyconv_in_"))
            shutil.move(str(inner[0]), str(tmp / inner[0].name))
            _sevenzip_extract(tmp / inner[0].name, dest)
            shutil.rmtree(tmp, ignore_errors=True)
        return dest

    if zipfile.is_zipfile(str(src)):
        with zipfile.ZipFile(str(src)) as z:
            _safe_extract_zip(z, dest)
        return dest
    if tarfile.is_tarfile(str(src)):
        with tarfile.open(str(src)) as t:
            t.extractall(str(dest), filter="data")
        return dest
    for suffix, opener in ((".gz", gzip.open), (".bz2", bz2.open), (".xz", lzma.open)):
        if ext.endswith(suffix):
            with opener(str(src), "rb") as f, open(dest / src.stem, "wb") as o:
                shutil.copyfileobj(f, o)
            return dest
    raise ConvertError("cannot open %s without 7-Zip (see the Tools tab)" % src.suffix)


def _safe_extract_zip(z, dest):
    dest = Path(dest).resolve()
    for info in z.infolist():
        target = (dest / info.filename).resolve()
        if not str(target).startswith(str(dest)):
            raise ConvertError("archive contains an unsafe path: %s" % info.filename)
    z.extractall(str(dest))


def list_archive(src):
    """Names inside an archive, for the preview panel."""
    if Tools.sevenzip:
        out = run([Tools.sevenzip, "l", "-ba", "-y", str(src)], timeout=300)
        return [l[53:].strip() for l in out.splitlines() if len(l) > 53]
    if zipfile.is_zipfile(str(src)):
        with zipfile.ZipFile(str(src)) as z:
            return z.namelist()
    if tarfile.is_tarfile(str(src)):
        with tarfile.open(str(src)) as t:
            return t.getnames()
    return []


# --------------------------------------------------------------------------
# create
# --------------------------------------------------------------------------

def make_archive(source, out, fmt):
    """Pack a file or a directory tree into out, using format fmt."""
    source, out = Path(source), Path(out)
    files = ([source] if source.is_file()
             else sorted(p for p in source.rglob("*") if p.is_file()))
    if not files:
        raise ConvertError("nothing to pack")

    if fmt in SOLID:
        if len(files) > 1:
            raise ConvertError(".%s holds a single file - pick .tar.%s or .zip"
                               % (fmt, fmt))
        opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}.get(fmt)
        if opener:
            with open(files[0], "rb") as f, opener(str(out), "wb") as o:
                shutil.copyfileobj(f, o)
            return
    if fmt in _TAR_MODE:
        with tarfile.open(str(out), _TAR_MODE[fmt]) as t:
            for f in files:
                t.add(str(f), arcname=str(f.relative_to(source.parent if source.is_file()
                                                        else source)))
        return
    if fmt == "zip":
        with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in files:
                z.write(str(f), arcname=str(f.relative_to(source.parent if source.is_file()
                                                          else source)))
        return
    if not Tools.sevenzip:
        raise ConvertError("writing .%s needs 7-Zip (see the Tools tab)" % fmt)
    out.unlink(missing_ok=True)
    root = source if source.is_dir() else source.parent
    items = ["*"] if source.is_dir() else [source.name]
    run([Tools.sevenzip, "a", "-y", "-t" + fmt, str(out)] + items,
        timeout=3600, cwd=str(root))


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def _repack(src, out, dst):
    tmp = Path(tempfile.mkdtemp(prefix="anyconv_ar_"))
    try:
        extract_any(src, tmp)
        entries = list(tmp.iterdir())
        if dst in SOLID and len(entries) == 1 and entries[0].is_file():
            make_archive(entries[0], out, dst)
        else:
            make_archive(tmp, out, dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


rule(READ_7Z, WRITE, need=("sevenzip",), cost=6, label="repack (7-Zip)",
     chainable=False)(_repack)
rule(READ_PY, WRITE_PY, cost=9, label="repack", chainable=False)(_repack)


@rule("*", "zip 7z targz", cost=20, label="compress", chainable=False)
def wrap_single(src, out, dst):
    """Any single file into an archive of its own."""
    make_archive(Path(src), out, dst)
