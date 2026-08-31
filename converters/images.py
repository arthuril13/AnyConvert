"""Image conversion, driven by whatever formats this Pillow build actually has."""

from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

from engine import rule, ConvertError

try:                                    # iPhone photos
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

Image.init()
Image.MAX_IMAGE_PIXELS = None

_reg = Image.registered_extensions()

# Kept out of the menus: handled better elsewhere in the app, scientific
# formats nobody converts to, and duplicate spellings of a format that is
# already listed (.jpe and .jfif are just .jpg, .dib is .bmp, and so on).
_SKIP_READ = {"pdf", "eps", "ps"}
_ALIASES = {"jpe", "jfif", "jpc", "j2c", "jpf", "jpx", "dib", "icb", "vda",
            "vst", "rgb", "rgba", "bw", "apng", "avifs", "pgm", "pbm", "pnm",
            "heics", "heifs", "hif", "heif"}
_ODDBALLS = {"eps", "ps", "mpo", "palm", "xvthumb", "bufr", "grib", "h5", "hdf",
             "fits", "fit", "wmf", "emf", "blp", "msp", "pfm", "im", "spi",
             "mic", "sgi", "flc", "fli", "gbr", "gd", "pcd", "wal", "ftex"}
# "pdf" is excluded here because the direct-only rule below owns it
_SKIP_WRITE = _ALIASES | _ODDBALLS | {"pdf"}

READ = sorted({e.lstrip(".") for e, f in _reg.items() if f in Image.OPEN} - _SKIP_READ)
WRITE = sorted({e.lstrip(".") for e, f in _reg.items() if f in Image.SAVE} - _SKIP_WRITE)


FLATTEN = {"jpg", "jpeg", "jpe", "jfif", "bmp", "dib", "pcx", "ppm", "pgm",
           "pbm", "pnm", "jp2", "j2k", "pdf", "dds", "tga"}
ANIMATED = {"gif", "webp", "png", "apng", "tiff", "tif"}


def _fmt(ext):
    return _reg.get("." + ext, ext.upper())


def _flatten(im, bg=(255, 255, 255)):
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, bg)
        flat.paste(im, mask=im.split()[-1])
        return flat
    if im.mode not in ("RGB", "L"):
        return im.convert("RGB")
    return im


def _save_kwargs(dst, im):
    kw = {}
    if dst in ("jpg", "jpeg", "jpe", "jfif"):
        kw.update(quality=92, optimize=True, progressive=True)
    elif dst == "webp":
        kw.update(quality=90, method=4)
    elif dst == "png":
        kw.update(optimize=True)
    elif dst in ("tif", "tiff"):
        kw.update(compression="tiff_lzw")
    elif dst == "pdf":
        kw.update(resolution=float(im.info.get("dpi", (150, 150))[0] or 150))
    return kw


# PDF output is registered separately and marked direct-only: an image wrapped
# in a PDF has no text in it, so chaining on to .txt would just make an empty file.
@rule(READ, "pdf", cost=6, label="image to pdf", chainable=False)
@rule(READ, WRITE, cost=5, label="image")
def image_convert(src, out, dst):
    im = Image.open(src)
    n_frames = getattr(im, "n_frames", 1)

    # exif_transpose hands back a flat copy, so only rotate stills - running it
    # on an animation would silently drop every frame after the first.
    if n_frames == 1:
        try:
            im = ImageOps.exif_transpose(im) or im
        except Exception:
            pass

    if dst == "ico":
        im = _flatten(im) if im.mode == "P" else im.convert("RGBA")
        side = max(im.size)
        sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(side, 16)]
        im.save(out, "ICO", sizes=sizes or [(32, 32)])
        return

    # Keep animation when both sides can carry it.
    if n_frames > 1 and dst in ANIMATED:
        frames = [f.copy() for f in ImageSequence.Iterator(im)]
        if dst in ("jpg", "jpeg"):
            frames = [_flatten(f) for f in frames]
        first, rest = frames[0], frames[1:]
        kw = _save_kwargs(dst, im)
        kw.update(save_all=True, append_images=rest,
                  duration=im.info.get("duration", 100),
                  loop=im.info.get("loop", 0))
        if dst == "webp":
            first = first.convert("RGBA")
            kw["append_images"] = [f.convert("RGBA") for f in rest]
        try:
            first.save(out, _fmt(dst), **kw)
            return
        except Exception:
            pass  # fall through to a still image

    if dst in FLATTEN:
        im = _flatten(im)
    elif im.mode == "CMYK" and dst in ("png", "webp"):
        im = im.convert("RGB")
    elif im.mode in ("I;16", "I", "F") and dst not in ("tif", "tiff", "png"):
        im = im.convert("L")

    try:
        im.save(out, _fmt(dst), **_save_kwargs(dst, im))
    except (OSError, ValueError) as e:
        im.convert("RGB").save(out, _fmt(dst))
        if not Path(out).exists():
            raise ConvertError(str(e))


# ---------------------------------------------------------------- SVG input

try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPDF, renderPM

    @rule("svg", "pdf", cost=5, label="svg to pdf")
    def svg_to_pdf(src, out, dst):
        drawing = svg2rlg(str(src))
        if drawing is None:
            raise ConvertError("could not read that SVG")
        renderPDF.drawToFile(drawing, str(out))

    @rule("svg", "png jpg jpeg gif tif tiff bmp", cost=6, label="svg raster")
    def svg_to_raster(src, out, dst):
        drawing = svg2rlg(str(src))
        if drawing is None:
            raise ConvertError("could not read that SVG")
        scale = 2.0                                   # render at 2x for sharpness
        drawing.scale(scale, scale)
        drawing.width *= scale
        drawing.height *= scale
        fmt = {"jpg": "JPG", "jpeg": "JPG"}.get(dst, dst.upper())
        renderPM.drawToFile(drawing, str(out), fmt=fmt)

except Exception:                                     # svglib not installed
    pass
