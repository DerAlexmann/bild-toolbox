"""Farbwechsel ohne Neuaufbau.

Bis 1.0.4 riss auch der Wechsel zwischen hellem und dunklem Schema die ganze
Oberflaeche ab und baute sie neu auf - mit denselben Folgen wie beim
Sprachwechsel: rund 250 ms Zwischenstaende auf dem Bildschirm und verlorene
Modulinhalte.

Jetzt kennt jeder Palettenwert seine Rolle (Color: "CARD", "TEXT" ...), und
die Widget-Klassen der Bild-Toolbox merken sich beim Einfaerben, welche Rolle
in welcher Option steckt. refresh_colors() faerbt damit alles nach.

Eine Rueckwaertssuche vom Farbwert zur Rolle kam nicht in Frage: In THEMES
sind mehrere Rollen im einen Schema gleich und im anderen verschieden - hell
ist "#ffffff" zugleich CARD und ON_ACCENT, dunkel nicht.

Wie beim Sprachwechsel vergleicht der strengste Test eine umgefaerbte
Oberflaeche Option fuer Option mit einer, die gleich im Zielschema gebaut
wurde. Die Fenstertests brauchen einen Bildschirm (Vorrichtung "fenster" in
conftest.py) und werden ohne einen uebersprungen.
"""

import pytest

FARBOPTIONEN = ("background", "foreground", "activebackground", "activeforeground",
                "disabledforeground", "highlightbackground", "highlightcolor",
                "selectcolor", "selectbackground", "selectforeground",
                "insertbackground", "troughcolor")

FELD = ("fieldbackground", "foreground", "background", "bordercolor", "lightcolor",
        "darkcolor", "arrowcolor", "insertcolor")
STILE = {
    "TEntry": FELD,
    "TCombobox": FELD,
    "TSpinbox": FELD,
    "TProgressbar": ("background", "troughcolor", "bordercolor", "lightcolor", "darkcolor"),
    "TScrollbar": ("background", "troughcolor", "bordercolor", "arrowcolor"),
    "Treeview": ("background", "fieldbackground", "foreground", "bordercolor"),
    "Treeview.Heading": ("background", "foreground"),
    "TScale": ("background", "troughcolor", "bordercolor", "lightcolor", "darkcolor"),
}


# -- ohne Fenster --------------------------------------------------------------


def test_palettenwerte_kennen_ihre_rolle(toolbox):
    vorher = toolbox.CURRENT_THEME
    try:
        toolbox.apply_theme("dark")
        assert toolbox.CARD == toolbox.THEMES["dark"]["CARD"]
        assert isinstance(toolbox.CARD, str)
        assert toolbox.CARD.role == "CARD"
        assert toolbox.OK.role == "OK"
    finally:
        toolbox.apply_theme(vorher)


# -- mit Fenster ---------------------------------------------------------------


def alle_widgets(wurzel):
    """Alle Widgets unter der Wurzel, in Aufbaureihenfolge."""
    widgets = [wurzel]
    for kind in wurzel.winfo_children():
        widgets += alle_widgets(kind)
    return widgets


def klapplisten_anlegen(wurzel):
    """Legt die Klapplisten aller Auswahlfelder an, als waeren sie schon aufgeklappt worden.

    Tk baut sie erst beim ersten Aufklappen - mit den Farben, die dann in der
    Optionsdatenbank stehen. Eine schon angelegte muss der Farbwechsel selbst
    nachfaerben.
    """
    for widget in alle_widgets(wurzel):
        if widget.winfo_class() == "TCombobox":
            widget.tk.call("ttk::combobox::PopdownWindow", widget)


def alle_farben(toolbox, wurzel):
    """Jede Farbe der Oberflaeche: Widget-Optionen, Klapplisten, Baum-Tags, ttk-Stile."""
    farben = []
    for widget in alle_widgets(wurzel):
        klasse = widget.winfo_class()
        # Nur echte Optionen abfragen: Tk akzeptiert Abkuerzungen.
        optionen = widget.keys()
        farben += [(klasse, option, str(widget.cget(option)))
                   for option in FARBOPTIONEN if option in optionen]
        if klasse == "Treeview":
            farben.append((klasse, "keep", str(widget.tag_configure("keep", "foreground"))))
        elif klasse == "TCombobox":
            liste = f"{widget}.popdown.f.l"
            if int(widget.tk.call("winfo", "exists", liste)):
                farben += [("Klappliste", option, str(widget.tk.call(liste, "cget", option)))
                           for option in ("-background", "-foreground",
                                          "-selectbackground", "-selectforeground")]
    stil = toolbox.ttk.Style(wurzel)
    for name, optionen in STILE.items():
        farben += [(name, option, str(stil.lookup(name, option))) for option in optionen]
        farben.append((name, "map", str(stil.map(name))))
    return farben


def umfaerben(toolbox, wurzel, app, schema):
    toolbox.apply_theme(schema)
    app._refresh_colors()
    wurzel.update()


@pytest.mark.parametrize(("von", "nach"), [("light", "dark"), ("dark", "light")])
def test_umgefaerbt_gleicht_frisch_aufgebaut(toolbox, fenster, von, nach):
    wurzel, app = fenster(schema=von)
    klapplisten_anlegen(wurzel)
    umfaerben(toolbox, wurzel, app, nach)
    umgefaerbt = alle_farben(toolbox, wurzel)
    app.close()

    wurzel, _app = fenster(schema=nach)
    klapplisten_anlegen(wurzel)
    frisch = alle_farben(toolbox, wurzel)
    abweichend = [(a, b) for a, b in zip(umgefaerbt, frisch) if a != b]
    assert not abweichend, f"nach dem Umfaerben anders als frisch: {abweichend[:5]}"
    assert len(umgefaerbt) == len(frisch)


def test_alle_tk_widgets_merken_sich_ihre_farben(toolbox, fenster):
    """Ein gewoehnliches tk.Label & Co. bliebe beim Farbwechsel in der alten Farbe."""
    wurzel, _app = fenster()
    fremd = [f"{w.winfo_class()} {w}" for w in alle_widgets(wurzel)[1:]
             if not isinstance(w, (toolbox.Themed, toolbox.ttk.Widget))]
    assert not fremd, f"ohne Farbgedaechtnis: {fremd[:5]}"


def test_farbwechsel_behaelt_widgets_und_inhalte(toolbox, fenster):
    wurzel, app = fenster()
    umwandeln = app.module("convert")
    umwandeln.files = ["C:/eins.png", "C:/zwei.png"]
    umwandeln.refresh_list()
    dubletten = app.module("duplicates")
    dubletten.folder.set("C:/Bilder")
    seiten = dict(app.pages)

    umfaerben(toolbox, wurzel, app, "dark")
    assert app.pages == seiten
    assert umwandeln.files == ["C:/eins.png", "C:/zwei.png"]
    assert umwandeln.listbox.get(0, "end") == ("eins.png", "zwei.png")
    assert dubletten.folder.get() == "C:/Bilder"


def test_fremder_farbwert_behaelt_seine_farbe(toolbox, fenster):
    """Nur Palettenfarben wechseln mit; ein eigener Farbwert bleibt stehen."""
    wurzel, _app = fenster()
    etikett = toolbox.Label(wurzel, bg=toolbox.CARD, fg=toolbox.TEXT)
    etikett.configure(fg="#123456")
    toolbox.apply_theme("dark")
    toolbox.refresh_colors(wurzel)
    assert etikett.cget("bg") == toolbox.THEMES["dark"]["CARD"]
    assert etikett.cget("fg") == "#123456"


def test_laufzeitfarben_folgen_dem_farbwechsel(toolbox, fenster, tmp_path):
    image = pytest.importorskip("PIL.Image")
    bild = tmp_path / "a.png"
    image.new("RGB", (4, 3)).save(bild)

    wurzel, app = fenster()
    vergleich = app.module("compare")
    vergleich.load("left", str(bild))                # Info in TEXT
    vergleich.swap()                                 # links jetzt leer, in MUTED
    icons = app.module("icons")
    icons.source.set(str(bild))
    icons.load_preview()                             # Zusammenfassung in OK

    umfaerben(toolbox, wurzel, app, "dark")
    dunkel = toolbox.THEMES["dark"]
    assert vergleich.infos["right"].cget("fg") == dunkel["TEXT"]
    assert vergleich.infos["left"].cget("fg") == dunkel["MUTED"]
    assert icons.summary.cget("fg") == dunkel["OK"]


def test_knoepfe_nutzen_nach_dem_wechsel_die_neuen_hoverfarben(toolbox, fenster):
    wurzel, app = fenster()
    knopf = app.module("convert").run_btn            # kind="primary"
    umfaerben(toolbox, wurzel, app, "dark")
    dunkel = toolbox.THEMES["dark"]
    knopf._on_enter(None)
    assert knopf.cget("bg") == dunkel["ACCENT_DARK"]
    knopf._on_leave(None)
    assert knopf.cget("bg") == dunkel["ACCENT"]
