"""Startgroesse und gemerkte Lage des Hauptfensters.

Die Rechnung steckt in reinen Funktionen und laeuft ohne Bildschirm. Ob das
Fenster dann wirklich so erscheint, laesst sich in der CI nicht pruefen - dort
gibt es keinen Bildschirm. Ein Quelltext-Test sichert deshalb zusaetzlich ab,
dass keine feste Startgroesse zurueckkehrt.
"""

from pathlib import Path

import pytest

QUELLE = Path(__file__).resolve().parent.parent / "Bild-Toolbox.pyw"

FLAECHE = (0, 0, 1920, 1040)          # Full HD abzueglich Taskleiste
BEDARF = (1192, 696)                  # gemessen mit allen Modulen der Version 1.0


def gespeichert(x, y, breite, hoehe, maximiert=False):
    return {"x": x, "y": y, "width": breite, "height": hoehe, "maximized": maximiert}


def ueberall(_x, _y):
    return True


def nirgends(_x, _y):
    return False


# ------------------------------------------------------------ Startlage

def test_erster_start_in_kleinster_groesse_mittig(toolbox):
    breite, hoehe, x, y, min_breite, min_hoehe = toolbox.window_placement(BEDARF, FLAECHE)
    rahmen_b, rahmen_h = toolbox.WINDOW_FRAME

    assert (breite, hoehe) == BEDARF
    assert (min_breite, min_hoehe) == BEDARF
    # Links und rechts, oben und unten bleibt gleich viel Platz
    assert abs(x - (1920 - (x + breite + rahmen_b))) <= 1
    assert abs(y - (1040 - (y + hoehe + rahmen_h))) <= 1


def test_mittig_auch_bei_taskleiste_oben(toolbox):
    _b, hoehe, _x, y, *_rest = toolbox.window_placement(BEDARF, (0, 48, 1920, 1032))
    assert y >= 48
    assert y + hoehe + toolbox.WINDOW_FRAME[1] <= 48 + 1032


def test_kleiner_bildschirm_begrenzt_groesse(toolbox):
    flaeche = (0, 0, 1024, 728)
    breite, hoehe, x, y, min_breite, min_hoehe = toolbox.window_placement(BEDARF, flaeche)
    rahmen_b, rahmen_h = toolbox.WINDOW_FRAME

    assert breite + rahmen_b <= 1024 and hoehe + rahmen_h <= 728
    # Die Mindestgroesse darf das Fenster nicht ueber den Bildschirm hinaus zwingen
    assert (min_breite, min_hoehe) == (breite, hoehe)
    assert x >= 0 and y >= 0


# ------------------------------------------------------ gemerkte Lage

def test_gemerkte_lage_wird_uebernommen(toolbox):
    lage = gespeichert(300, 120, 1400, 900)
    ergebnis = toolbox.window_placement(BEDARF, FLAECHE, lage, ueberall)
    assert ergebnis[:4] == (1400, 900, 300, 120)


def test_gemerkte_lage_auf_groesserem_zweitem_bildschirm_bleibt(toolbox):
    # Links vom Hauptbildschirm, groesser als dieser - das hat der Nutzer so gewollt
    lage = gespeichert(-2560, 0, 2400, 1300)
    ergebnis = toolbox.window_placement(BEDARF, FLAECHE, lage, ueberall)
    assert ergebnis[:4] == (2400, 1300, -2560, 0)


def test_lage_auf_abgestecktem_bildschirm_wird_zentriert(toolbox):
    lage = gespeichert(-2560, 0, 1300, 800)
    breite, hoehe, x, y, *_rest = toolbox.window_placement(BEDARF, FLAECHE, lage, nirgends)
    assert (breite, hoehe) == (1300, 800), "Die gemerkte Groesse bleibt erhalten."
    assert 0 <= x and x + breite <= 1920
    assert 0 <= y and y + hoehe <= 1040


def test_zu_klein_gemerktes_fenster_waechst_auf_den_bedarf(toolbox):
    # So sieht es aus, wenn ein Update weitere Module in die Navigation bringt
    lage = gespeichert(100, 100, 900, 500)
    ergebnis = toolbox.window_placement(BEDARF, FLAECHE, lage, ueberall)
    assert ergebnis[:2] == BEDARF


def test_probepunkt_liegt_in_der_titelleiste(toolbox):
    gefragt = []

    def merken(x, y):
        gefragt.append((x, y))
        return True

    toolbox.window_placement(BEDARF, FLAECHE, gespeichert(300, 120, 1400, 900), merken)
    (x, y), = gefragt
    assert 300 < x < 300 + 1400, "Probepunkt muss innerhalb der Fensterbreite liegen."
    assert 120 <= y < 120 + toolbox.WINDOW_FRAME[1], "Probepunkt muss in der Titelleiste liegen."


# ---------------------------------------------------- Einstellungsdatei

def test_gueltige_lage_wird_gelesen(toolbox):
    daten = {"theme": "dark", "window": gespeichert(10, 20, 1300, 800, True)}
    assert toolbox.window_from_config(daten) == gespeichert(10, 20, 1300, 800, True)


def test_maximiert_fehlt_heisst_nicht_maximiert(toolbox):
    daten = {"window": {"x": 10, "y": 20, "width": 1300, "height": 800}}
    assert toolbox.window_from_config(daten)["maximized"] is False


@pytest.mark.parametrize("daten", [
    {},
    {"window": "kaputt"},
    {"window": {"x": 10, "y": 20}},
    {"window": {"x": "links", "y": 20, "width": 1300, "height": 800}},
    {"window": {"x": 10, "y": 20, "width": 0, "height": 800}},
    {"window": {"x": 10, "y": 20, "width": 1300, "height": None}},
    ["keine", "Tabelle"],
    None,
])
def test_unbrauchbare_lage_wird_ignoriert(toolbox, daten):
    assert toolbox.window_from_config(daten) is None


def test_nur_echtes_true_gilt_als_maximiert(toolbox):
    daten = {"window": dict(gespeichert(10, 20, 1300, 800), maximized="ja")}
    assert toolbox.window_from_config(daten)["maximized"] is False


# ------------------------------------------------------ Tk-Geometrie

@pytest.mark.parametrize("text, erwartet", [
    ("1192x696+364+172", gespeichert(364, 172, 1192, 696)),
    ("1400x900+-1500+-20", gespeichert(-1500, -20, 1400, 900)),
])
def test_geometrie_wird_zerlegt(toolbox, text, erwartet):
    erwartet = {k: v for k, v in erwartet.items() if k != "maximized"}
    assert toolbox.parse_geometry(text) == erwartet


@pytest.mark.parametrize("text", ["", None, "1192x696", "Fenster", "1192x696-10+5"])
def test_unbekannte_geometrie_ergibt_none(toolbox, text):
    assert toolbox.parse_geometry(text) is None


# ------------------------------------------------------------ Quelltext

@pytest.fixture(scope="module")
def hauptfenster_quelltext():
    text = QUELLE.read_text(encoding="utf-8")
    return text[text.index("class ToolboxApp"):]


def test_keine_feste_startgroesse(hauptfenster_quelltext):
    assert 'geometry("1400x900")' not in hauptfenster_quelltext, (
        "Die feste Startgroesse ist durch die gemessene ersetzt - sie liess "
        "eine grosse Luecke zwischen Navigation und Sprachauswahl."
    )
    assert "self._place_window()" in hauptfenster_quelltext


def test_lage_wird_beim_schliessen_gemerkt(hauptfenster_quelltext):
    close = hauptfenster_quelltext[hauptfenster_quelltext.index("def close("):]
    close = close[:close.index("\n    def ", 1)]
    assert "self._remember_window()" in close
    assert close.index("self._remember_window()") < close.index("self.root.destroy()"), (
        "Die Lage muss gelesen werden, solange das Fenster noch existiert."
    )
