"""Sprachwechsel ohne Neuaufbau - die Texte.

Bis 1.0.4 riss jeder Sprachwechsel die ganze Oberflaeche ab und baute sie neu
auf. Dabei gingen die Inhalte aller Module verloren, und weil Tk jedes Element
einzeln zeichnet, sah man rund 225 ms lang jeden Zwischenstand. Jetzt merkt
sich set_text() zu jedem Widget, woraus sein Text entstanden ist, und
refresh_texts() tauscht die Texte an Ort und Stelle aus.

Der strengste Test vergleicht eine umgeschaltete Oberflaeche Text fuer Text mit
einer, die gleich in der Zielsprache aufgebaut wurde - ueber alle Seiten.
Vergisst jemand bei einer neuen Beschriftung set_text(), bleibt sie beim
Umschalten in der alten Sprache stehen, und genau das faellt dort auf.

Die Fenstertests brauchen einen Bildschirm. Ohne einen - etwa auf den Linux-
Laeufern der CI - werden sie uebersprungen.
"""

import pytest


@pytest.fixture
def sprache(toolbox):
    """Stellt die Sprache fuer einen Test ein und hinterher zurueck."""
    vorher = toolbox._.language

    def setzen(code):
        toolbox._.language = code

    yield setzen
    toolbox._.language = vorher


@pytest.fixture
def verzeichnis(toolbox):
    """Leeres Textverzeichnis fuer einen Test, danach wieder der alte Stand."""
    vorher = dict(toolbox._TEXTS)
    toolbox._TEXTS.clear()
    yield toolbox._TEXTS
    toolbox._TEXTS.clear()
    toolbox._TEXTS.update(vorher)


# -- ohne Fenster --------------------------------------------------------------


def test_uebersetzter_text_kennt_schluessel_und_werte(toolbox, sprache):
    sprache("de")
    text = toolbox._("Version {version}").format(version="9.9")
    assert text == "Version 9.9"
    assert isinstance(text, str)
    assert text.key == "Version {version}"
    assert text.values == {"version": "9.9"}


def test_again_bildet_den_text_in_der_neuen_sprache(toolbox, sprache):
    sprache("de")
    text = toolbox._("Geladen: {name}").format(name="a.png")
    sprache("en")
    assert text.again() == "Loaded: a.png"


def test_eingesetzte_uebersetzungen_werden_mit_uebersetzt(toolbox, sprache):
    sprache("de")
    text = toolbox._("{done} Datei(en) {action}.").format(
        done=3, action=toolbox._("gelöscht"))
    sprache("en")
    englisch = toolbox.TRANSLATIONS["en"]
    assert text.again() == englisch["{done} Datei(en) {action}."].format(
        done=3, action=englisch["gelöscht"])


def test_verkettung_bleibt_uebersetzbar(toolbox, sprache):
    sprache("de")
    kopf = "\U0001F3E0" + "   " + toolbox._("Start")
    meldung = toolbox._("Abgebrochen - ") + toolbox._("Bereit")
    assert isinstance(kopf, toolbox.Translated)
    sprache("en")
    englisch = kopf.again()
    assert englisch == "\U0001F3E0   Home"
    assert meldung.again() == "Cancelled - Ready"
    sprache("de")
    assert englisch.again() == "\U0001F3E0   Start", "auch der Rueckweg muss gehen"


def test_gewoehnlicher_text_wird_nicht_gemerkt(toolbox, verzeichnis):
    gesetzt = []
    toolbox.remember_text("ort", gesetzt.append, "90 %")
    assert gesetzt == ["90 %"]
    assert verzeichnis == {}


def test_gewoehnlicher_text_ersetzt_einen_gemerkten(toolbox, verzeichnis, sprache):
    """Sonst holte der naechste Sprachwechsel den ueberschriebenen Text zurueck."""
    sprache("de")
    gesetzt = []
    toolbox.remember_text("ort", gesetzt.append, toolbox._("Noch nicht gescannt."))
    toolbox.remember_text("ort", gesetzt.append, "C:/Bilder")
    sprache("en")
    toolbox.refresh_texts()
    assert gesetzt == ["Noch nicht gescannt.", "C:/Bilder"]


def test_refresh_texts_wechselt_hin_und_zurueck(toolbox, verzeichnis, sprache):
    sprache("de")
    gesetzt = []
    toolbox.remember_text("ort", gesetzt.append, toolbox._("Bereit"))
    sprache("en")
    toolbox.refresh_texts()
    sprache("de")
    toolbox.refresh_texts()
    assert gesetzt == ["Bereit", "Ready", "Bereit"]


def test_funktion_als_text_wird_neu_aufgerufen(toolbox, verzeichnis, sprache):
    sprache("de")
    gesetzt = []
    toolbox.remember_text("bericht", gesetzt.append, lambda: toolbox._("Bereit") + "!")
    sprache("en")
    toolbox.refresh_texts()
    assert gesetzt == ["Bereit!", "Ready!"]


def test_zerstoerte_widgets_fallen_heraus(toolbox, verzeichnis):
    def zerstoert(_text):
        raise toolbox.tk.TclError('invalid command name ".!label"')

    verzeichnis["weg"] = (zerstoert, toolbox._("Bereit"))
    toolbox.refresh_texts()
    assert "weg" not in verzeichnis


# -- mit Fenster ---------------------------------------------------------------


# Die Vorrichtung "fenster" steht in conftest.py - der Farbwechsel nutzt sie auch.


def alle_texte(wurzel):
    """Jeder sichtbare Text der Oberflaeche, in Aufbaureihenfolge."""
    texte = [("Titel", wurzel.title())]

    def zeilen(baum, eintrag):
        for kind in baum.get_children(eintrag):
            texte.append(("Treeview", baum.item(kind, "text")))
            zeilen(baum, kind)

    def sammeln(eltern):
        for kind in eltern.winfo_children():
            klasse = kind.winfo_class()
            # Nur echte Optionen abfragen: Tk akzeptiert Abkuerzungen, und bei
            # ttk-Eingabefeldern waere "text" die fuer "textvariable".
            optionen = kind.keys()
            if klasse == "TCombobox":
                texte.append((klasse, kind.get()))
            elif klasse == "Text":
                texte.append((klasse, kind.get("1.0", "end-1c")))
            elif klasse == "Treeview":
                for spalte in ("#0", *kind["columns"]):
                    texte.append((klasse, kind.heading(spalte, "text")))
                zeilen(kind, "")
            else:
                if "text" in optionen and str(kind.cget("text")):
                    texte.append((klasse, str(kind.cget("text"))))
                if "textvariable" in optionen and str(kind.cget("textvariable")):
                    texte.append((klasse, kind.getvar(str(kind.cget("textvariable")))))
            sammeln(kind)

    sammeln(wurzel)
    return texte


def umschalten(toolbox, wurzel, app, code):
    toolbox._.language = code
    app._refresh_texts()
    wurzel.update()


@pytest.mark.parametrize(("von", "nach"), [("de", "en"), ("en", "de")])
def test_umgeschaltet_gleicht_frisch_aufgebaut(toolbox, fenster, von, nach):
    wurzel, app = fenster(von)
    umschalten(toolbox, wurzel, app, nach)
    umgeschaltet = alle_texte(wurzel)
    app.close()

    wurzel, _app = fenster(nach)
    frisch = alle_texte(wurzel)
    abweichend = [(a, b) for a, b in zip(umgeschaltet, frisch) if a != b]
    assert not abweichend, f"nach dem Umschalten anders als frisch: {abweichend[:5]}"
    assert len(umgeschaltet) == len(frisch)


def test_englische_oberflaeche_zeigt_keine_deutschen_quelltexte(toolbox, fenster):
    """Faengt Texte ab, die am Uebersetzer vorbei gesetzt werden.

    So hiessen die Durchsuchen-Knoepfe aus path_row() bis 1.0.4 auch in der
    englischen Oberflaeche "Durchsuchen ...", und ueber den Bildern im Vergleich
    stand "LINKES BILD".
    """
    wurzel, _app = fenster("en")
    deutsch = {quelle for quelle, ziel in toolbox.TRANSLATIONS["en"].items() if quelle != ziel}
    reste = [(klasse, text) for klasse, text in alle_texte(wurzel) if text in deutsch]
    assert not reste, f"deutsch geblieben: {reste[:5]}"


def test_sprachwechsel_behaelt_die_widgets(toolbox, fenster):
    wurzel, app = fenster("de")
    seiten = {key: (seite, modul) for key, (seite, modul) in app.pages.items()}
    umschalten(toolbox, wurzel, app, "en")
    assert app.pages == seiten
    assert all(seite.winfo_exists() for seite, _modul in seiten.values())


def test_ergebnisse_folgen_dem_sprachwechsel(toolbox, fenster):
    wurzel, app = fenster("de")
    dubletten = app.module("duplicates")
    dubletten.groups = [("abc", [{"path": "C:/nirgends/a.png"},
                                 {"path": "C:/nirgends/b.png"}])]
    dubletten.render_groups()
    umwandeln = app.module("convert")
    umwandeln.files = ["C:/eins.png", "C:/zwei.png"]
    umwandeln.refresh_list()
    app.set_status(toolbox._("{count} Icons geladen.").format(count=4))

    umschalten(toolbox, wurzel, app, "en")
    englisch = toolbox.TRANSLATIONS["en"]
    baum = dubletten.tree
    gruppe = baum.get_children()[0]
    assert baum.item(gruppe, "text") == englisch[
        "GRUPPE {no}  -  {name}  ({count} Dateien)"].format(no=1, name="abc", count=2)
    assert baum.item(baum.get_children(gruppe)[0], "text") == " a.png  " + englisch["[behalten]"]
    assert baum.item(baum.get_children(gruppe)[1], "text") == " b.png"
    assert dubletten.summary.cget("text") == englisch[
        "{groups} Gruppen - {files} Datei(en) über die jeweils erste hinaus. "
        "Rechtsklick für Optionen."].format(groups=1, files=1)
    assert umwandeln.summary.cget("text") == englisch[
        "{count} Datei(en) bereit für die Konvertierung."].format(count=2)
    assert app.status_var.get() == englisch["{count} Icons geladen."].format(count=4)


def test_bildvergleich_bleibt_nach_dem_tauschen_uebersetzbar(toolbox, fenster, tmp_path):
    image = pytest.importorskip("PIL.Image")
    bild = tmp_path / "a.png"
    image.new("RGB", (4, 3)).save(bild)

    wurzel, app = fenster("de")
    vergleich = app.module("compare")
    vergleich.load("left", str(bild))
    vergleich.swap()
    umschalten(toolbox, wurzel, app, "en")

    englisch = toolbox.TRANSLATIONS["en"]
    assert vergleich.infos["right"].cget("text").startswith("File: a.png\n")
    assert vergleich.infos["left"].cget("text") == englisch["Keine Datei geladen"]
    assert vergleich.labels["left"].cget("text") == englisch["Kein Bild geladen"]


def test_statistikbericht_entsteht_in_der_neuen_sprache(toolbox, fenster):
    wurzel, app = fenster("de")
    statistik = app.module("stats")
    statistik._done("C:/Bilder", {
        "files": 2, "bytes": 2048, "pixels": 24,
        "formats": {"PNG": 2}, "resolutions": {"4x3": 2},
        "largest": ("a.png", 1024), "smallest": ("b.png", 1024),
        "widest": ("a.png", 4), "tallest": ("a.png", 3)})

    umschalten(toolbox, wurzel, app, "en")
    englisch = toolbox.TRANSLATIONS["en"]
    bericht = statistik.text.get("1.0", "end-1c")
    assert bericht.startswith(englisch["ORDNER-ANALYSE"])
    assert englisch["Analyse abgeschlossen."] in bericht
    assert "ORDNER-ANALYSE" not in bericht
