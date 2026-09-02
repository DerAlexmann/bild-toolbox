"""Prueft die Modulliste der Anwendung.

Die Kacheln auf der Startseite, die Eintraege unter "Info & Hilfe" und die
Tastenkuerzel Strg+1 bis Strg+9 lesen alle aus ``ToolboxApp.module_classes``.
Ein doppelter oder leerer Schluessel wuerde die Navigation still zerlegen.
"""

import pytest


def module_liste(toolbox):
    return toolbox.ToolboxApp.module_classes


def test_schluessel_sind_eindeutig_und_gesetzt(toolbox):
    schluessel = [cls.key for cls in module_liste(toolbox)]
    assert all(schluessel), "Ein Modul hat keinen key"
    assert len(schluessel) == len(set(schluessel)), f"Doppelte keys: {schluessel}"


def test_startseite_ist_das_erste_modul(toolbox):
    assert module_liste(toolbox)[0].key == "home"


def test_jedes_modul_hat_titel_untertitel_und_icon(toolbox):
    for cls in module_liste(toolbox):
        assert cls.title.strip(), f"{cls.__name__} hat keinen Titel"
        assert cls.icon.strip(), f"{cls.__name__} hat kein Icon"
        assert cls.subtitle.strip(), f"{cls.__name__} hat keinen Untertitel"


def test_arbeitsmodule_haben_eine_beschreibung(toolbox):
    # Start und Info zeigen selbst die Beschreibungen der anderen an.
    for cls in module_liste(toolbox):
        if cls.key in ("home", "info"):
            continue
        assert cls.description.strip(), f"{cls.__name__} hat keine description"


def test_alle_module_sind_per_tastenkuerzel_erreichbar(toolbox):
    # _bind_keys() belegt Strg+1 bis Strg+9 mit module_classes[:9].
    assert len(module_liste(toolbox)) <= 10, (
        "Ab dem zehnten Arbeitsmodul ist ein Modul nicht mehr per Strg+Zahl erreichbar - "
        "_bind_keys() anpassen oder die Reihenfolge pruefen."
    )


def test_abhaengigkeitstabelle_ist_vollstaendig(toolbox):
    tabelle = toolbox.ToolboxApp.dependency_table()
    namen = [name for name, _installiert, _zweck, _befehl in tabelle]
    assert "Pillow" in namen
    for name, installiert, zweck, befehl in tabelle:
        assert isinstance(installiert, bool), f"{name}: Status ist kein bool"
        assert zweck.strip(), f"{name}: keine Beschreibung"
        assert befehl.startswith("pip install "), f"{name}: kein Installationsbefehl"


@pytest.mark.parametrize("endung", [".jpg", ".png", ".webp", ".gif", ".tiff"])
def test_gaengige_bildendungen_werden_erkannt(toolbox, endung):
    assert endung in toolbox.IMAGE_EXTENSIONS


def test_bildendungen_sind_klein_und_mit_punkt(toolbox):
    for endung in toolbox.IMAGE_EXTENSIONS + toolbox.EXE_EXTENSIONS:
        assert endung.startswith("."), endung
        assert endung == endung.lower(), endung
