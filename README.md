# AnyConvert

Any file into any other file. Images, video, audio, documents, archives, fonts,
even DMG to ISO. No upload sites, no watermarks, no "go Premium to continue" —
one portable Windows app that runs entirely on your own machine.

Drop a file in, pick a format, done.

## Download

### [⬇ Download AnyConvert.exe](https://github.com/arthuril13/AnyConvert/releases/latest)

One file, about 62 MB. No installer, no setup, no admin rights. Save it
anywhere and double-click it.

Windows may show a blue "Windows protected your PC" box the first time, because
the app is not code-signed (a certificate costs a few hundred pounds a year).
Click **More info** then **Run anyway**. If you would rather not trust a binary
from a stranger, [build it yourself](#building-it-yourself) — it is one command.

Nothing is ever uploaded. Your files never leave your computer.

---

## What it converts

| Group | In | Out |
|---|---|---|
| Images | png jpg heic webp gif bmp tiff ico tga avif jp2 dds qoi svg xbm + more | png jpg webp gif bmp tiff ico avif heic jp2 pcx ppm tga qoi pdf |
| Video | mp4 mkv avi mov webm flv wmv mpg ts 3gp m2ts vob rm mxf + more | mp4 mkv avi mov webm flv wmv mpg ts ogv 3gp gif + a still frame |
| Audio | mp3 wav flac ogg opus m4a aac wma aiff amr ape dts + more | mp3 wav flac ogg opus m4a aac ac3 wma aiff mp2 au amr |
| Documents | pdf docx txt md html rtf epub mobi fb2 xps cbz | pdf docx txt md html + png/jpg of each page |
| Data | csv tsv xlsx json yaml xml toml jsonl | csv tsv xlsx json yaml xml toml html md pdf |
| Archives | zip 7z rar tar gz bz2 xz cab iso dmg wim arj deb rpm msi + more | zip 7z tar tar.gz tar.bz2 tar.xz gz bz2 xz wim |
| Disk images | dmg iso img vhd vhdx vmdk qcow2 vdi | iso img vhd vhdx vmdk qcow2 vdi |
| Fonts | ttf otf woff woff2 ttc | ttf otf woff woff2 |

Anything can also become a **.zip**, **.7z** or a burnable **.iso**.

### Two-step routes

If there is no direct converter, it finds a path. `.docx` to `.pdf` with no
Office installed goes through Markdown so headings and lists survive. The route
is shown next to the format box before you press Convert, so you always know
what it is about to do.

---

## Using it

**The app** — run `AnyConvert.exe`. Drag files onto the window, or use Add
files. Pick a format, press Convert. Results land next to the originals unless
you untick "same folder as the file".

The format list only ever shows conversions that will actually run on this
machine. If something needs a helper program, the Tools tab says which one.

**The command line** — the same engine, for batches and scripts:

```bash
python convert.py photo.heic png
```

```bash
python convert.py *.docx pdf --out C:\Users\me\Desktop
```

```bash
python convert.py --list mp4
```

**Checking an install** — this writes `verify-report.txt` next to the exe:

```bash
AnyConvert.exe --verify
```

---

## Helper programs

AnyConvert does images, documents, data files, fonts and ISO writing on its own.
These unlock the rest. Install one and press **Rescan** — no restart.

| Program | Unlocks | Install |
|---|---|---|
| FFmpeg | all audio and video | `winget install Gyan.FFmpeg` |
| 7-Zip | archives, ISO, DMG, RAR | `winget install 7zip.7zip` |
| LibreOffice | doc xls ppt odt, and much better docx to pdf | `winget install TheDocumentFoundation.LibreOffice` |
| Calibre | epub mobi azw3 | `winget install calibre.calibre` |
| qemu-img | vhd vmdk qcow2 vdi | `winget install SoftwareFreedomConservancy.QEMU` |
| dmg2img | byte-exact DMG to ISO | drop `dmg2img.exe` next to the app |

The Tools tab has a **Copy install commands** button that puts the ones you are
missing on the clipboard.

---

## DMG to ISO, specifically

Two routes, picked automatically:

1. **With `dmg2img.exe` present** — a raw byte-for-byte conversion, the same
   thing the usual command-line tools do.
2. **Without it** — 7-Zip unpacks the DMG and a fresh ISO 9660 image is built
   from the files.

Route 2 was tested on a real 884 MB `BaseSystem.dmg` from a macOS Sequoia
recovery image — 2.1 GB unpacked, 49,076 files across 12,705 folders. It
produced a 3.13 GB ISO in 9 minutes 19 seconds, which mounts in Windows
Explorer with the tree intact, and files read back byte-identical (SHA-256
checked on several).

Worth knowing about route 2:

- **Filenames lose spaces.** Windows reads names off the ISO tree, and ISO 9660
  has no space character, so `Volume Name Icon` becomes `Volume_Name_Icon`.
- **macOS symlinks are dropped** — 2,407 of them in the test above. Windows
  cannot store them in an ISO. The app tells you how many were left out.
  Convert to `.zip` or `.7z` to keep everything as it was.
- **The result is not bootable.** ISO 9660 is not HFS+, so a macOS installer
  image comes out as readable files, not something you can boot from. Use
  `dmg2img` if you need a byte-exact copy.
- **Encrypted DMGs will not open.** Nothing on Windows reads those without the
  password.

### Why the ISO settings look so specific

They were chosen by building each combination pycdlib offers and mounting the
result on Windows, not by reading the spec:

- Interchange **level 4** with long names and no `;1` version suffix is what
  Explorer actually reads. Level 1 and 3 images mount as an empty disc.
- **UDF** images from pycdlib are unreadable — 7-Zip refuses them outright.
- Spaces in level-4 names also make the disc mount empty, hence the underscores.
- **Joliet** is the first choice, but pycdlib under-reserves space for its
  directory tree on large images and fails at write time with *"assigned an
  extent beyond the ISO"*. The macOS image above hits this. So the code tries
  Joliet + Rock Ridge, then Joliet alone, then a plain level-4 image, and takes
  the first that writes — telling you in the log when it had to drop down.

---

## Source code

Everything is here — there is no hidden part. You need Python 3.10 or newer.

```bash
git clone https://github.com/arthuril13/AnyConvert.git
```

```bash
cd AnyConvert
```

```bash
pip install -r requirements.txt
```

Run it straight from source, no build step:

```bash
python app.py
```

## Building it yourself

To produce your own `AnyConvert.exe`:

```bash
build.bat
```

That installs the dependencies, draws the icon, runs the test suite, and only
then builds `dist\AnyConvert.exe` (about 62 MB, since Python and every library
are packed inside it). If any test fails it stops rather than shipping a
broken build.

---

## Testing

```bash
python selftest.py
```

Builds sample files of every kind, runs 60+ conversions, converts several of the
results a second time, then checks the output actually holds up — that a
transparent PNG really got flattened for JPEG, that an animated GIF is still
animated after becoming a WebP, that a quoted comma in a CSV survives the trip
to JSON, that an ISO really contains its nested files.

---

## How it is put together

```
app.py                    the window
convert.py                command line front end
engine.py                 tool detection, rule registry, route finding
converters/images.py      Pillow
converters/media.py       FFmpeg
converters/documents.py   PyMuPDF, python-docx, ReportLab, LibreOffice, Calibre
converters/data.py        csv, openpyxl, yaml, xmltodict
converters/archives.py    7-Zip, zipfile, tarfile
converters/diskimages.py  pycdlib, dmg2img, qemu-img
converters/fonts.py       fontTools
selftest.py               the test suite
make_icon.py              draws icon.ico
```

Every converter registers itself with a decorator:

```python
@rule("png jpg webp", "pdf", cost=6, label="image to pdf", chainable=False)
def image_to_pdf(src, out, dst):
    ...
```

`engine` puts those into a graph and finds the cheapest route between any two
extensions. `need=("ffmpeg",)` hides a rule while its tool is missing, which is
what keeps the format list honest. `chainable=False` marks an endpoint, so the
app never offers something silly like PNG to TXT by way of a PDF with no text
in it.

Adding a format is one decorated function.

---

## Licence

AGPL-3.0. See [LICENSE](LICENSE).

The reason it is AGPL and not something more permissive: PDF and ebook handling
uses **PyMuPDF**, which is AGPL-3.0 or a paid Artifex licence. Shipping it
inside the exe means the whole app takes the same licence.

You are free to use, change and share this. If you distribute a modified
version, or run it as a network service, you have to share your source too.

The other libraries are permissive and impose nothing: Pillow, pillow-heif,
ReportLab and svglib (BSD), python-docx, openpyxl, PyYAML and fontTools (MIT),
pycdlib (LGPL-2.1).

FFmpeg, 7-Zip, LibreOffice, Calibre and qemu-img are **not bundled** — the app
looks for them on your machine and uses them if they are there. Nothing of
theirs ends up in the exe, so their licences do not reach into this project.

Copyright (C) 2026 Arthur Lubarsky

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version. It is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
for more details.
