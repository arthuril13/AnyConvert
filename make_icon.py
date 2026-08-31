"""Draw the app icon. Run once; build.bat calls it for you."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 512
BG1, BG2 = (79, 140, 255), (120, 90, 240)
FG = (255, 255, 255)


def rounded(size, radius, fill):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=fill)
    return img


def main():
    grad = Image.new("RGB", (SIZE, SIZE))
    px = grad.load()
    for y in range(SIZE):
        t = y / float(SIZE - 1)
        row = tuple(int(BG1[i] + (BG2[i] - BG1[i]) * t) for i in range(3))
        for x in range(SIZE):
            px[x, y] = row

    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(grad, (0, 0), rounded(SIZE, 112, (255, 255, 255, 255)))
    d = ImageDraw.Draw(icon)

    # two sheets of paper with an arrow curving from one to the other
    def sheet(x, y, w, h, fold):
        d.rounded_rectangle([x, y, x + w, y + h], 18, fill=FG)
        d.polygon([(x + w - fold, y), (x + w, y + fold), (x + w - fold, y + fold)],
                  fill=(210, 222, 250))

    sheet(96, 104, 150, 190, 44)
    sheet(266, 218, 150, 190, 44)

    d.line([(150, 330), (150, 372), (300, 372)], fill=FG, width=26, joint="curve")
    d.polygon([(292, 340), (352, 372), (292, 404)], fill=FG)

    out = Path(__file__).with_name("icon.ico")
    icon.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                          (128, 128), (256, 256)])
    icon.resize((256, 256), Image.LANCZOS).save(Path(__file__).with_name("icon.png"))
    print("wrote", out)


if __name__ == "__main__":
    main()
