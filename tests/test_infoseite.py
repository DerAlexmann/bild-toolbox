"""Die Seite "Info & Hilfe" rollt, statt ihren Text abzuschneiden.

In der kleinsten Fenstergroesse ist die Seite hoeher als der Platz, den sie
bekommt. Frueher wurde dann der Text unter "Ueber dieses Programm" unten
abgeschnitten. Die Oberflaeche selbst laesst sich in der CI nicht bauen - dort
gibt es keinen Bildschirm. Geprueft werden deshalb die Konstruktion im
Quelltext und die Rechnung des Mausrads mit einem nachgestellten Ereignis.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

QUELLE = Path(__file__).resolve().parent.parent / "Bild-Toolbox.pyw"


@pytest.fixture(scope="module")
def quelltext():
    return QUELLE.read_text(encoding="utf-8")


def abschnitt(text, start, ende):
    beginn = text.index(start)
    return text[beginn:text.index(ende, beginn + 1)]


def test_infoseite_liegt_in_einem_rollbereich(quelltext):
    info = abschnitt(quelltext, "class InfoModule", "\nclass ")
    assert "ScrollArea(self.body" in info
    assert "make_card(self.body" not in info, (
        "Die Karten der Info-Seite muessen in area.inner liegen - direkt in "
        "self.body rollen sie nicht mit und werden wieder abgeschnitten."
    )
    assert "area.bind_wheel()" in info, (
        "Ohne bind_wheel() rollt das Mausrad nur ueber dem Rollbalken."
    )


def test_rollbereich_fuellt_mindestens_die_sichtbare_hoehe(quelltext):
    # Sonst waere die Ueber-Karte bei grossem Fenster nur so hoch wie ihr Text
    layout = abschnitt(quelltext, "    def _layout(", "\n    def ")
    assert "max(needed, visible)" in layout


# ------------------------------------------------------------ Mausrad

class Leinwand:
    def __init__(self):
        self.gerollt = []

    def yview_scroll(self, anzahl, einheit):
        self.gerollt.append((anzahl, einheit))


def bereich(balken_sichtbar=True):
    return SimpleNamespace(
        canvas=Leinwand(),
        scrollbar=SimpleNamespace(winfo_manager=lambda: "pack" if balken_sichtbar else ""),
    )


@pytest.mark.parametrize("num, delta, erwartet", [
    ("??", -120, 3),       # Windows, eine Raste nach unten
    ("??", 240, -6),       # Windows, zwei Rasten nach oben
    ("??", -1, 3),         # macOS meldet kleine Werte
    (5, 0, 3),             # Linux, nach unten
    (4, 0, -3),            # Linux, nach oben
])
def test_mausrad_rollt_in_die_richtige_richtung(toolbox, num, delta, erwartet):
    ziel = bereich()
    ergebnis = toolbox.ScrollArea._on_wheel(ziel, SimpleNamespace(num=num, delta=delta))
    assert ziel.canvas.gerollt == [(erwartet, "units")]
    assert ergebnis == "break"


def test_mausrad_ohne_rollbalken_tut_nichts(toolbox):
    ziel = bereich(balken_sichtbar=False)
    ergebnis = toolbox.ScrollArea._on_wheel(ziel, SimpleNamespace(num="??", delta=-120))
    assert ziel.canvas.gerollt == []
    assert ergebnis is None
