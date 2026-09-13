"""Gemeinsame Testvorbereitung.

Die Anwendung ist eine einzelne .pyw-Datei mit einem Bindestrich im Namen und
laesst sich deshalb nicht mit ``import`` laden. Hier wird sie einmal pro
Testlauf ueber importlib eingelesen. Beim Import entsteht noch kein Fenster -
tkinter wird zwar importiert, ``tk.Tk()`` ruft aber erst ``main()`` auf. Die
Tests laufen deshalb auch auf einem Rechner ohne Bildschirm.
"""

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "Bild-Toolbox.pyw"


@pytest.fixture(scope="session")
def toolbox():
    """Die geladene Bild-Toolbox als Modul."""
    assert SCRIPT.is_file(), f"Skript nicht gefunden: {SCRIPT}"

    # Der Loader wird ausdruecklich mitgegeben. Python kennt die Endung .pyw
    # nur unter Windows als Quelldatei-Endung; unter Linux und macOS liefert
    # spec_from_file_location() sonst None, und der Testlauf bricht mit einem
    # nichtssagenden AttributeError ab.
    loader = SourceFileLoader("bild_toolbox", str(SCRIPT))
    spec = importlib.util.spec_from_file_location("bild_toolbox", SCRIPT, loader=loader)
    assert spec is not None and spec.loader is not None, (
        f"Konnte fuer {SCRIPT} keine Modulspezifikation erzeugen."
    )

    module = importlib.util.module_from_spec(spec)
    sys.modules["bild_toolbox"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fenster(toolbox, monkeypatch):
    """Baut Hauptfenster ohne Einstellungsdatei und raeumt sie danach weg.

    ``fenster(sprache, schema)`` liefert ``(wurzel, app)``; jede Seite ist
    dabei schon einmal gebaut. Sprache und Farbschema stehen hinterher wieder
    wie vorher. Ohne Bildschirm - etwa auf den Linux-Laeufern der CI - wird
    der Test uebersprungen.
    """
    tk = toolbox.tk
    sprache_vorher, schema_vorher = toolbox._.language, toolbox.CURRENT_THEME
    monkeypatch.setattr(toolbox, "load_config", dict)
    monkeypatch.setattr(toolbox, "save_config", lambda _daten: True)
    offen = []

    def bauen(sprache="de", schema="light"):
        monkeypatch.setattr(toolbox, "startup_language", lambda: sprache)
        monkeypatch.setattr(toolbox, "startup_theme", lambda: schema)
        try:
            wurzel = tk.Tk()
        except tk.TclError as exc:                  # kein Bildschirm vorhanden
            pytest.skip(f"kein Fenster moeglich: {exc}")
        try:
            app = toolbox.ToolboxApp(wurzel)
        except Exception:
            wurzel.destroy()
            raise
        offen.append(app)
        for cls in app.module_classes:              # jede Seite einmal bauen
            app.module(cls.key)
        wurzel.update()
        return wurzel, app

    yield bauen
    # Ueber close() statt destroy(): Das haelt auch die geplanten Nachlaeufer
    # an. Sonst liefen sie im naechsten Fenster ins Leere, und Tcl meldete
    # "invalid command name".
    for app in offen:
        try:
            app.close()
        except tk.TclError:                         # schon im Test geschlossen
            pass
    toolbox._.language = sprache_vorher
    toolbox.apply_theme(schema_vorher)
