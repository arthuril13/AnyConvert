"""Disk images: DMG, ISO, IMG and the virtual-machine formats."""

import re
import shutil
import tempfile
from pathlib import Path

from engine import rule, run, note, Tools, ConvertError
from converters.archives import extract_any, make_archive

DISK_READ = "dmg iso img bin cue nrg mdf udf toast vhd vhdx vmdk qcow2 qcow vdi raw hfs hfsx"
VM_FMT = "vhd vhdx vmdk qcow2 qcow vdi raw img"


# --------------------------------------------------------------------------
# building an ISO9660 image out of a folder
# --------------------------------------------------------------------------

# Settings picked by building images and mounting them on Windows. Interchange
# level 4 (ISO 9660:1999) with long names and no ";1" version suffix is what
# Explorer reads; level 4 images whose names contain spaces mount as an empty
# disc, which is why names get sanitised below.
#
# Joliet and Rock Ridge are extra name trees for other systems to read. Both
# are worth having, but pycdlib under-reserves space for the Joliet tree on
# large images and then refuses to write ("assigned an extent beyond the ISO").
# Measured on a real 2.1 GB macOS DMG, 66k entries: both Joliet attempts fail
# in about 25 seconds each, and the plain level-4 image writes fine. Windows
# reads names off the ISO tree at level 4 either way, so dropping them costs
# little. Ordered best-first; the first one that writes wins.
ISO_ATTEMPTS = (
    dict(interchange_level=4, joliet=3, rock_ridge="1.09"),
    dict(interchange_level=4, joliet=3),
    dict(interchange_level=4),
)

# Windows reads the names below straight off the ISO tree rather than the
# Joliet one, and ISO 9660 has no room for spaces, so they become underscores.
_ISO_SAFE = re.compile(r"[^A-Za-z0-9_.\-]")


def _iso_name(name, used):
    """A name ISO 9660 accepts, kept unique inside its own directory."""
    cand = _ISO_SAFE.sub("_", name)[:96] or "_"
    base, n = cand, 1
    while cand in used:
        cand = "%s_%d" % (base[:90], n)
        n += 1
    used.add(cand)
    return cand


def _walk(folder):
    """
    Breadth-first walk yielding (kind, path), parents before children.

    Disk images are full of things Windows cannot follow - macOS symlinks that
    point outside the image, resource forks, junctions - and touching one of
    them raises. Anything we cannot read comes back as "skip" so one odd entry
    cannot sink the whole conversion.
    """
    from collections import deque

    queue, skipped = deque([folder]), []
    while queue:
        current = queue.popleft()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            skipped.append(current)
            continue
        for entry in entries:
            try:
                if entry.is_symlink() and not entry.exists():
                    skipped.append(entry)            # dangling link
                elif entry.is_dir():
                    yield "dir", entry
                    queue.append(entry)
                elif entry.is_file():
                    yield "file", entry
                else:
                    skipped.append(entry)            # device node, socket, ...
            except OSError:
                skipped.append(entry)
    for s in skipped:
        yield "skip", s


def _write_iso(folder, out, label, settings):
    """One attempt. Returns (added, skipped, renamed)."""
    import pycdlib

    iso = pycdlib.PyCdlib()
    iso.new(vol_ident=label, **settings)
    # pycdlib rejects joliet_path / rr_name outright when the image has no such
    # tree, so only pass what these settings actually asked for.
    rock_ridge = settings.get("rock_ridge")
    joliet = settings.get("joliet")
    names, used = {}, {}
    added = skipped = renamed = 0
    try:
        for kind, item in _walk(folder):
            if kind == "skip":
                skipped += 1
                continue
            rel = item.relative_to(folder)
            iso_parts, node = [], Path(".")
            for part in rel.parts:
                node = node / part
                key = str(node)
                if key not in names:
                    names[key] = _iso_name(part, used.setdefault(str(node.parent), set()))
                    if names[key] != part:
                        renamed += 1
                iso_parts.append(names[key])
            iso_path = "/" + "/".join(iso_parts)
            extra = {}
            if joliet:
                extra["joliet_path"] = "/" + "/".join(rel.parts)
            if rock_ridge:
                extra["rr_name"] = item.name
            try:
                if kind == "dir":
                    iso.add_directory(iso_path, **extra)
                else:
                    iso.add_file(str(item), iso_path, **extra)
                added += 1
            except Exception:
                skipped += 1                          # unreadable or refused by ISO
        if not added:
            raise ConvertError("nothing in there could go into an ISO")
        iso.write(str(out))
    finally:
        iso.close()
    return added, skipped, renamed


def build_iso(folder, out, label=None):
    """Make a mountable ISO out of a directory tree."""
    folder = Path(folder)
    label = re.sub(r"[^A-Z0-9_]", "_", (label or folder.name).upper())[:32] or "ANYCONVERT"

    last = None
    for i, settings in enumerate(ISO_ATTEMPTS):
        try:
            added, skipped, renamed = _write_iso(folder, out, label, settings)
            break
        except ConvertError:
            Path(out).unlink(missing_ok=True)
            raise
        except Exception as e:
            last = e
            Path(out).unlink(missing_ok=True)
    else:
        raise ConvertError(
            "could not build an ISO from that content (%s).\n"
            "Converting to .zip or .7z instead will always work. For a DMG, "
            "dmg2img.exe next to this app makes a raw copy with no size limit."
            % last)

    if i:
        note("Built as a plain ISO 9660 image - the tree was too big for the "
             "extra Joliet and Rock Ridge name trees. Windows and macOS read it "
             "the same way; some Linux tools will show the shortened names.")
    if skipped:
        note("%d item(s) left out of the ISO - symlinks and anything Windows "
             "could not read. Use .zip or .7z to keep them." % skipped)
    if renamed:
        note("%d name(s) adjusted: ISO 9660 has no spaces, so they became "
             "underscores." % renamed)


# --------------------------------------------------------------------------
# DMG
# --------------------------------------------------------------------------

@rule("dmg", "iso", cost=5, label="dmg to iso")
def dmg_to_iso(src, out, dst):
    """
    Two routes. dmg2img makes a byte-for-byte raw image, which is what a real
    DMG-to-ISO does. Without it we unpack the DMG with 7-Zip and build a fresh
    ISO9660 from the files, which mounts and burns fine on Windows.
    """
    if Tools.dmg2img:
        run([Tools.dmg2img, "-i", str(src), "-o", str(out)], timeout=3600)
        if Path(out).exists() and Path(out).stat().st_size > 0:
            return
    if not Tools.sevenzip:
        raise ConvertError("DMG needs 7-Zip, or dmg2img.exe next to this app "
                           "(see the Tools tab)")
    tmp = Path(tempfile.mkdtemp(prefix="anyconv_dmg_"))
    try:
        extract_any(src, tmp)
        entries = [p for p in tmp.iterdir()]
        if not entries:
            raise ConvertError("that DMG unpacked to nothing - it may be encrypted")
        # 7-Zip usually leaves one folder named after the volume
        root = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp
        build_iso(root, out, label=Path(src).stem)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@rule("dmg iso img hfs hfsx udf", "zip 7z targz", need=("sevenzip",), cost=6,
      label="image to archive", chainable=False)
def image_to_archive(src, out, dst):
    tmp = Path(tempfile.mkdtemp(prefix="anyconv_img_"))
    try:
        extract_any(src, tmp)
        make_archive(tmp, out, dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@rule("zip 7z tar targz rar dmg", "iso", need=("sevenzip",), cost=7, label="to iso")
def archive_to_iso(src, out, dst):
    tmp = Path(tempfile.mkdtemp(prefix="anyconv_toiso_"))
    try:
        extract_any(src, tmp)
        build_iso(tmp, out, label=Path(src).stem)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@rule("*", "iso", cost=21, label="file to iso", chainable=False)
def file_to_iso(src, out, dst):
    """Wrap one file in a burnable ISO."""
    tmp = Path(tempfile.mkdtemp(prefix="anyconv_one_"))
    try:
        shutil.copy2(str(src), str(tmp / Path(src).name))
        build_iso(tmp, out, label=Path(src).stem)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# raw / virtual machine images
# --------------------------------------------------------------------------

@rule(VM_FMT + " iso dmg", VM_FMT, need=("qemu_img",), cost=5, label="disk image")
def qemu_convert(src, out, dst):
    fmt = {"img": "raw", "qcow": "qcow2", "vhd": "vpc", "vhdx": "vhdx"}.get(dst, dst)
    run([Tools.qemu_img, "convert", "-p", "-O", fmt, str(src), str(out)], timeout=7200)


@rule("img bin raw", "iso", cost=12, label="raw to iso")
def raw_to_iso(src, out, dst):
    """A raw ISO9660 dump only needs renaming; anything else gets rebuilt."""
    with open(src, "rb") as f:
        f.seek(32769)
        if f.read(5) == b"CD001":
            shutil.copyfile(str(src), str(out))
            return
    if not Tools.sevenzip:
        raise ConvertError("that .img is not ISO9660 - needs 7-Zip to rebuild it")
    archive_to_iso(src, out, dst)


@rule("iso", "img", cost=12, label="iso to img")
def iso_to_raw(src, out, dst):
    shutil.copyfile(str(src), str(out))
