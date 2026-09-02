"""Prueft die Sprachtabelle.

Quellsprache ist Deutsch: der deutsche Text im Code ist zugleich der
Schluessel. Diese Tests fangen die beiden Fehler ab, die beim Uebersetzen
tatsaechlich passieren - ein vergessener oder verschriebener Platzhalter
(fuehrt zur Laufzeit zu einem KeyError in ``str.format``) und eine Sprache
ohne Anzeigenamen in der Seitenleiste.
"""

import re

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def placeholders(text):
    return set(PLACEHOLDER.findall(text))


def test_jede_sprache_hat_einen_anzeigenamen(toolbox):
    for code in toolbox.TRANSLATIONS:
        assert code in toolbox.LANGUAGE_NAMES, (
            f"Sprache '{code}' fehlt in LANGUAGE_NAMES"
        )
    assert toolbox.SOURCE_LANGUAGE in toolbox.LANGUAGE_NAMES


def test_platzhalter_bleiben_erhalten(toolbox):
    fehler = []
    for code, table in toolbox.TRANSLATIONS.items():
        for quelle, ziel in table.items():
            fehlend = placeholders(quelle) - placeholders(ziel)
            ueberzaehlig = placeholders(ziel) - placeholders(quelle)
            if fehlend or ueberzaehlig:
                fehler.append(
                    f"[{code}] {quelle!r}: fehlend={sorted(fehlend)} "
                    f"unbekannt={sorted(ueberzaehlig)}"
                )
    assert not fehler, "Platzhalter stimmen nicht ueberein:\n" + "\n".join(fehler)


def test_keine_leeren_uebersetzungen(toolbox):
    for code, table in toolbox.TRANSLATIONS.items():
        for quelle, ziel in table.items():
            assert ziel.strip(), f"[{code}] leere Uebersetzung fuer {quelle!r}"


def test_translator_faellt_auf_die_quellsprache_zurueck(toolbox):
    uebersetzer = toolbox.Translator("en")
    assert uebersetzer("Kein Eintrag in der Tabelle") == "Kein Eintrag in der Tabelle"

    quelle = toolbox.Translator(toolbox.SOURCE_LANGUAGE)
    assert quelle("Start") == "Start"


def test_verfuegbare_sprachen_beginnen_mit_der_quellsprache(toolbox):
    verfuegbar = list(toolbox.Translator().available())
    assert verfuegbar[0] == toolbox.SOURCE_LANGUAGE
    assert set(verfuegbar) >= {toolbox.SOURCE_LANGUAGE, *toolbox.TRANSLATIONS}
