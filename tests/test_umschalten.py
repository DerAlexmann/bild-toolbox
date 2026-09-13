"""Umschalten von Sprache und Farbschema ohne Neuaufbau.

Bis 1.0.4 riefen set_language() und set_theme() _rebuild() auf: Die ganze
Oberflaeche wurde abgerissen und neu gebaut. Man sah dabei rund eine
Viertelsekunde lang jeden Zwischenstand, und die Inhalte aller Module gingen
verloren - wer nach einer langen Dublettensuche auf "Dunkel" klickte, war das
Ergebnis los.

Jetzt tauschen beide Wechsel Texte bzw. Farben an Ort und Stelle aus (siehe
test_sprachwechsel.py und test_farbwechsel.py), und unter Windows ruht
waehrenddessen das Zeichnen. Die Fenstertests brauchen einen Bildschirm
(Vorrichtung "fenster" in conftest.py) und werden ohne einen uebersprungen.
"""

import sys

import pytest

WECHSEL = [("set_language", "en"), ("set_theme", "dark")]
AUFFRISCHER = [("set_language", "en", "refresh_texts"),
               ("set_theme", "dark", "refresh_colors")]


def test_neuaufbau_gibt_es_nicht_mehr(toolbox):
    assert not hasattr(toolbox.ToolboxApp, "_rebuild")


def module_fuellen(app):
    """Module wie mitten in der Arbeit - die Werte direkt gesetzt."""
    vergleich = app.module("compare")
    umwandeln = app.module("convert")
    dubletten = app.module("duplicates")
    vergleich.paths["left"] = "C:/links.png"
    umwandeln.files = ["C:/eins.png", "C:/zwei.png"]
    umwandeln.refresh_list()
    dubletten.folder.set("C:/Bilder")
    dubletten.groups = [("abc", [{"path": "C:/nirgends/a.png"},
                                 {"path": "C:/nirgends/b.png"}])]
    dubletten.render_groups()
    return vergleich, umwandeln, dubletten


@pytest.mark.parametrize(("methode", "wert"), WECHSEL)
def test_modulinhalte_ueberstehen_den_wechsel(fenster, methode, wert):
    wurzel, app = fenster()
    vergleich, umwandeln, dubletten = module_fuellen(app)
    seiten = dict(app.pages)

    getattr(app, methode)(wert)
    wurzel.update()

    assert app.pages == seiten, "die Module wurden neu angelegt"
    assert vergleich.paths["left"] == "C:/links.png"
    assert umwandeln.files == ["C:/eins.png", "C:/zwei.png"]
    assert umwandeln.listbox.get(0, "end") == ("eins.png", "zwei.png")
    assert dubletten.folder.get() == "C:/Bilder"
    assert len(dubletten.groups) == 1
    assert len(dubletten.tree.get_children()) == 1


@pytest.mark.parametrize(("methode", "wert"), WECHSEL)
def test_wechsel_bleibt_auf_der_aktuellen_seite(toolbox, fenster, methode, wert):
    wurzel, app = fenster()
    app.show("stats")
    getattr(app, methode)(wert)
    wurzel.update()
    assert app.current == "stats"
    assert app.nav_buttons["stats"].active
    titel = toolbox._(toolbox.StatisticsModule.title)
    assert app.header_title.cget("text").endswith(titel)


def test_sprachwechsel_behaelt_die_letzte_statusmeldung(toolbox, fenster):
    """Die Mindestgroesse wird nach einem Sprachwechsel neu vermessen und
    wechselt dafuer kurz auf die Startseite. Das darf die Statuszeile nicht
    auf "Bereit" zuruecksetzen - die Meldung soll nur die Sprache wechseln."""
    wurzel, app = fenster()
    app.show("stats")
    app.set_status(toolbox._("Analyse fertig: {count} Bilder.").format(count=7))
    app.set_language("en")
    wurzel.update()
    englisch = toolbox.TRANSLATIONS["en"]["Analyse fertig: {count} Bilder."]
    assert app.status_var.get() == englisch.format(count=7)


def test_wechsel_wird_gespeichert_und_angezeigt(toolbox, fenster, monkeypatch):
    wurzel, app = fenster()
    gespeichert = {}
    monkeypatch.setattr(toolbox, "save_config",
                        lambda daten: gespeichert.update(daten) or True)
    app.set_language("en")
    app.set_theme("dark")
    wurzel.update()
    assert gespeichert == {"language": "en", "theme": "dark"}
    assert app.language_box.get() == toolbox.LANGUAGE_NAMES["en"]
    assert app.dark_var.get() is True


def test_seitenleiste_behaelt_ihre_breite(fenster):
    """_natural_size() schaltet pack_propagate der Seitenleiste kurz ein, um
    ihre Hoehe zu messen. Seit 1.0.2 behielt sie danach die Breite ihres
    Inhalts - je nach Sprache 236 oder 249 statt 250 px -, und nach einem
    Sprachwechsel fiel die Mindestbreite des Fensters bis zu 13 px zu gross aus."""
    wurzel, app = fenster()
    breite = int(app.sidebar.cget("width"))
    assert app.sidebar.winfo_width() == breite
    app.set_language("en")
    wurzel.update()
    assert app.sidebar.winfo_reqwidth() == breite
    assert app.sidebar.winfo_width() == breite


def test_mindestgroesse_folgt_der_sprache(toolbox, fenster):
    wurzel, app = fenster()
    app.set_language("en")
    wurzel.update()
    erwartet = toolbox.window_placement(app._natural_size(), toolbox.work_area(wurzel))[4:]
    assert tuple(wurzel.minsize()) == tuple(erwartet)


def test_waehrend_eines_vorgangs_bleibt_der_wechsel_gesperrt(toolbox, fenster, monkeypatch):
    """Bewusst beibehalten: Waehrend ein Scan laeuft, wird nicht umgeschaltet."""
    wurzel, app = fenster()
    hinweise = []
    monkeypatch.setattr(toolbox.messagebox, "showinfo", lambda *a, **_k: hinweise.append(a))
    dubletten = app.module("duplicates")
    dubletten.busy = True
    try:
        app.set_language("en")
        app.set_theme("dark")
    finally:
        dubletten.busy = False
    assert (toolbox._.language, toolbox.CURRENT_THEME) == ("de", "light")
    assert len(hinweise) == 2
    assert app.language_box.get() == toolbox.LANGUAGE_NAMES["de"]
    assert app.dark_var.get() is False


# -- angehaltenes Zeichnen (nur Windows) ---------------------------------------

nur_windows = pytest.mark.skipif(sys.platform != "win32",
                                 reason="WM_SETREDRAW gibt es nur unter Windows")


def sichtbar(wurzel):
    """WM_SETREDRAW(FALSE) nimmt dem Fenster das WS_VISIBLE - daran ist es zu erkennen."""
    import ctypes
    return bool(ctypes.windll.user32.IsWindowVisible(wurzel.winfo_id()))


@nur_windows
@pytest.mark.parametrize(("methode", "wert", "auffrischer"), AUFFRISCHER)
def test_waehrend_des_wechsels_ruht_das_zeichnen(toolbox, fenster, monkeypatch,
                                                 methode, wert, auffrischer):
    wurzel, app = fenster()
    echt, beobachtet = getattr(toolbox, auffrischer), []

    def spion(*args):
        beobachtet.append(sichtbar(wurzel))
        echt(*args)

    monkeypatch.setattr(toolbox, auffrischer, spion)
    getattr(app, methode)(wert)
    wurzel.update()
    assert beobachtet == [False], "beim Austausch muss das Zeichnen ruhen"
    assert sichtbar(wurzel), "danach muss wieder gezeichnet werden"


@nur_windows
@pytest.mark.parametrize(("methode", "wert", "auffrischer"), AUFFRISCHER)
def test_zeichnen_laeuft_auch_nach_einem_fehler_weiter(toolbox, fenster, monkeypatch,
                                                      methode, wert, auffrischer):
    """Sonst bliebe das Fenster nach einer Ausnahme dauerhaft eingefroren."""
    wurzel, app = fenster()

    def kaputt(*_args):
        raise RuntimeError("absichtlich")

    monkeypatch.setattr(toolbox, auffrischer, kaputt)
    with pytest.raises(RuntimeError):
        getattr(app, methode)(wert)
    assert sichtbar(wurzel)
