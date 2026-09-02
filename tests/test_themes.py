"""Prueft die Farbschemata.

``apply_theme()`` schreibt die Werte einer Palette per ``globals().update()``
in die Modulvariablen. Fehlt in einer Palette ein Name, faellt das erst beim
Umschalten zur Laufzeit auf - und dann mitten in der Oberflaeche.
"""

import re

FARBWERT = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_alle_paletten_haben_dieselben_namen(toolbox):
    paletten = toolbox.THEMES
    assert paletten, "THEMES ist leer"

    referenz_name, referenz = next(iter(paletten.items()))
    for name, palette in paletten.items():
        fehlend = set(referenz) - set(palette)
        ueberzaehlig = set(palette) - set(referenz)
        assert not fehlend, f"'{name}' fehlt gegenueber '{referenz_name}': {sorted(fehlend)}"
        assert not ueberzaehlig, f"'{name}' hat zusaetzlich: {sorted(ueberzaehlig)}"


def test_farbwerte_sind_hex_codes(toolbox):
    for name, palette in toolbox.THEMES.items():
        for schluessel, wert in palette.items():
            assert FARBWERT.match(wert), f"'{name}.{schluessel}' ist kein Hex-Farbwert: {wert!r}"


def test_standardschema_existiert(toolbox):
    assert toolbox.DEFAULT_THEME in toolbox.THEMES


def test_apply_theme_setzt_die_modulvariablen(toolbox):
    vorher = toolbox.CURRENT_THEME
    try:
        for name, palette in toolbox.THEMES.items():
            toolbox.apply_theme(name)
            assert toolbox.CURRENT_THEME == name
            for schluessel, wert in palette.items():
                assert getattr(toolbox, schluessel) == wert

        # Ein unbekannter Name darf nicht zu halb gesetzten Farben fuehren
        toolbox.apply_theme("gibt-es-nicht")
        assert toolbox.CURRENT_THEME == toolbox.DEFAULT_THEME
    finally:
        toolbox.apply_theme(vorher)
