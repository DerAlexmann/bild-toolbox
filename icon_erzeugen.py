"""Erzeugt das Programmsymbol bild_toolbox.ico.

Gezeichnet werden zwei uebereinanderliegende Bilder in Weiss auf einer
abgerundeten Flaeche im Akzentblau des Farbschemas - ein Stapel Bilder, wie
ihn jedes Modul der Toolbox bearbeitet. Das vordere traegt das seit jeher
uebliche Sinnbild fuer ein Foto: Sonne und Berge. Die .ico enthaelt alle
ueblichen Groessen, vom Reiter der Taskleiste bis zur grossen Kachel im
Explorer.

Aufruf:  python icon_erzeugen.py
Benoetigt:  pip install Pillow
"""

from __future__ import annotations

import os

from PIL import Image, ImageChops, ImageDraw

ZIEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bild_toolbox.ico")
KANTE = 1024                                  # Vorlage, wird heruntergerechnet
GROESSEN = [16, 24, 32, 48, 64, 128, 256]

BLAU = (47, 125, 225, 255)                    # ACCENT des hellen Schemas
WEISS = (255, 255, 255, 255)
HELLBLAU = (198, 218, 245, 255)               # das hintere Blatt


def _kasten(x0, y0, x1, y1):
    """Rechteck in Anteilen der Kantenlaenge in Pixel umrechnen."""
    return (KANTE * x0, KANTE * y0, KANTE * x1, KANTE * y1)


def zeichnen() -> Image.Image:
    bild = Image.new("RGBA", (KANTE, KANTE), (0, 0, 0, 0))
    stift = ImageDraw.Draw(bild)

    rand = KANTE // 16
    stift.rounded_rectangle((rand, rand, KANTE - rand, KANTE - rand),
                            radius=KANTE // 5, fill=BLAU)

    ecke = KANTE // 16
    luft = KANTE // 40                        # blauer Spalt zwischen den Blaettern

    # Hinteres Blatt, nur als Streifen oben links sichtbar
    stift.rounded_rectangle(_kasten(0.22, 0.25, 0.69, 0.62), radius=ecke,
                            fill=HELLBLAU)

    # Vorderes Blatt, vom blauen Spalt abgesetzt
    vorn = _kasten(0.29, 0.355, 0.76, 0.725)
    stift.rounded_rectangle((vorn[0] - luft, vorn[1] - luft,
                             vorn[2] + luft, vorn[3] + luft),
                            radius=ecke + luft, fill=BLAU)
    stift.rounded_rectangle(vorn, radius=ecke, fill=WEISS)

    # Sonne und Berge, am Rand des vorderen Blattes beschnitten
    x0, y0, x1, y1 = vorn
    breite, hoehe = x1 - x0, y1 - y0
    motiv = Image.new("RGBA", (KANTE, KANTE), (0, 0, 0, 0))
    pinsel = ImageDraw.Draw(motiv)
    r = breite * 0.10
    sonne = (x0 + breite * 0.23, y0 + hoehe * 0.29)
    pinsel.ellipse((sonne[0] - r, sonne[1] - r, sonne[0] + r, sonne[1] + r), fill=BLAU)
    pinsel.polygon([(x0 + breite * 0.44, y0 + hoehe * 0.30),
                    (x0 + breite * 0.95, y1), (x0 - breite * 0.07, y1)], fill=BLAU)
    pinsel.polygon([(x0 + breite * 0.16, y0 + hoehe * 0.62),
                    (x0 + breite * 0.56, y1), (x0 - breite * 0.24, y1)], fill=BLAU)

    maske = Image.new("L", (KANTE, KANTE), 0)
    ImageDraw.Draw(maske).rounded_rectangle(vorn, radius=ecke, fill=255)
    motiv.putalpha(ImageChops.multiply(motiv.getchannel("A"), maske))
    bild.alpha_composite(motiv)
    return bild


def main() -> None:
    vorlage = zeichnen()
    vorlage.save(ZIEL, sizes=[(n, n) for n in GROESSEN])
    print("geschrieben:", ZIEL)


if __name__ == "__main__":
    main()
