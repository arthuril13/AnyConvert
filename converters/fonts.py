"""Fonts: TTF, OTF, WOFF and WOFF2, via fontTools."""

from pathlib import Path

from engine import rule, ConvertError

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None

if TTFont:
    IN = "ttf otf woff woff2 ttc"
    OUT = "ttf otf woff woff2"

    @rule(IN, OUT, cost=5, label="font")
    def font_convert(src, out, dst):
        try:
            font = TTFont(str(src), fontNumber=0)
        except Exception as e:
            raise ConvertError("could not read that font: %s" % e)

        if dst == "woff2":
            try:
                import brotli  # noqa: F401
            except ImportError:
                raise ConvertError("woff2 needs the brotli package")

        font.flavor = {"woff": "woff", "woff2": "woff2"}.get(dst)
        is_cff = "CFF " in font or "CFF2" in font
        if dst == "ttf" and is_cff:
            raise ConvertError("that font has CFF outlines - save it as .otf instead")
        if dst == "otf" and not is_cff:
            raise ConvertError("that font has TrueType outlines - save it as .ttf instead")
        font.save(str(out))
        font.close()
