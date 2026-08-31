"""
Command line front end.

    python convert.py photo.heic png
    python convert.py *.docx pdf --out C:\\Users\\me\\Desktop
    python convert.py --list mp4
"""

import argparse
import glob
import sys
from pathlib import Path

import engine
from engine import Tools, ConvertError


def main():
    ap = argparse.ArgumentParser(
        prog="convert", description="Convert files between formats.",
        epilog="the last argument is the target format: convert.py photo.heic png")
    # One list, format last. Two separate positionals would be ambiguous to
    # argparse - it hands everything to the first one and leaves the second None.
    ap.add_argument("args", nargs="*", metavar="FILE",
                    help="files to convert (wildcards allowed), then the target format")
    ap.add_argument("--out", "-o", help="output folder (default: next to the source)")
    ap.add_argument("--list", "-l", metavar="EXT",
                    help="show what EXT can be converted into, then exit")
    ap.add_argument("--tools", action="store_true", help="show helper program status")
    args = ap.parse_args()

    if args.tools:
        for key, label, why, cmd, ok in Tools.status():
            print("%-9s %-14s %s" % ("ok" if ok else "MISSING", label,
                                     getattr(Tools, key) or cmd))
        return 0

    if args.list:
        ext = args.list.lstrip(".")
        targets = engine.targets_for(ext)
        print(".%s can become:\n" % ext)
        print("  " + "  ".join("." + engine._ext_suffix(t) for t in targets)
              if targets else "  (nothing)")
        return 0

    if len(args.args) < 2:
        ap.print_help()
        return 2

    *patterns, target = args.args
    target = target.lstrip(".")

    paths = []
    for pattern in patterns:
        hits = [Path(p) for p in glob.glob(pattern)] or [Path(pattern)]
        paths += [p for p in hits if p.is_file()]
    if not paths:
        print("no matching files")
        return 1

    failed = 0
    for src in paths:
        out = (Path(args.out) / (src.stem + "." + engine._ext_suffix(target))
               if args.out else None)
        try:
            result = engine.convert(src, target, out_path=out)
            print("%s -> %s" % (src.name, result))
            for n in engine.take_notes():
                print("   note: %s" % n)
        except ConvertError as e:
            failed += 1
            print("%s FAILED: %s" % (src.name, e), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
