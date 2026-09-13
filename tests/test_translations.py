"""Prueft die Sprachtabelle.

Quellsprache ist Deutsch: der deutsche Text im Code ist zugleich der
Schluessel. Diese Tests fangen die Fehler ab, die beim Uebersetzen
tatsaechlich passieren - ein vergessener oder verschriebener Platzhalter
(fuehrt zur Laufzeit zu einem KeyError in ``str.format``), eine Sprache ohne
Anzeigenamen in der Seitenleiste, ein neuer Text ohne Uebersetzung und ein
Eintrag, zu dem es im Code keinen Text (mehr) gibt.
"""

import ast
import re
from pathlib import Path

import pytest

QUELLE = Path(__file__).resolve().parent.parent / "Bild-Toolbox.pyw"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def placeholders(text):
    return set(PLACEHOLDER.findall(text))


def schluessel_im_quelltext():
    """Alle _("...")-Aufrufe mit fester Zeichenkette einsammeln."""
    baum = ast.parse(QUELLE.read_text(encoding="utf-8"))
    gefunden = []
    for knoten in ast.walk(baum):
        if (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name)
                and knoten.func.id == "_" and knoten.args):
            argument = knoten.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                gefunden.append(argument.value)
    return gefunden


def alle_schluessel(toolbox):
    """Feste Schluessel plus die, die erst zur Laufzeit nachgeschlagen werden.

    Titel, Untertitel, Beschreibung und Gruppe der Module stehen als
    Klassenattribute im Code und werden erst mit _(cls.title) usw. uebersetzt.
    """
    dynamisch = [toolbox.RenameModule.PLACEHOLDERS, toolbox.GroupResultModule.tree_heading]
    for cls in toolbox.ToolboxApp.module_classes:
        dynamisch += [cls.title, cls.subtitle, cls.description, cls.group,
                      getattr(cls, "tree_heading", "")]
    return list(dict.fromkeys(schluessel_im_quelltext() + [t for t in dynamisch if t]))


def test_es_gibt_ueberhaupt_texte(toolbox):
    assert len(alle_schluessel(toolbox)) > 200


@pytest.mark.parametrize("sprache", ["en"])
def test_jeder_schluessel_ist_uebersetzt(toolbox, sprache):
    tabelle = toolbox.TRANSLATIONS[sprache]
    fehlend = [k for k in alle_schluessel(toolbox) if k not in tabelle]
    assert not fehlend, f"ohne Uebersetzung in '{sprache}': {fehlend[:5]}"


@pytest.mark.parametrize("sprache", ["en"])
def test_keine_verwaisten_eintraege(toolbox, sprache):
    """Ein Eintrag ohne passenden Schluessel ist fast immer ein Tippfehler."""
    bekannt = set(alle_schluessel(toolbox))
    ueberzaehlig = [k for k in toolbox.TRANSLATIONS[sprache] if k not in bekannt]
    assert not ueberzaehlig, f"ohne Entsprechung im Code: {ueberzaehlig[:5]}"


def test_translator_liefert_in_jeder_sprache_text(toolbox):
    vorher = toolbox._.language
    try:
        for sprache in [toolbox.SOURCE_LANGUAGE, *toolbox.TRANSLATIONS]:
            toolbox._.language = sprache
            for schluessel in alle_schluessel(toolbox):
                assert toolbox._(schluessel).strip(), (sprache, schluessel)
    finally:
        toolbox._.language = vorher


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
