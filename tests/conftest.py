"""Gemeinsame Testvorbereitung.

Die Anwendung ist eine einzelne .pyw-Datei mit einem Bindestrich im Namen und
laesst sich deshalb nicht mit ``import`` laden. Hier wird sie einmal pro
Testlauf ueber importlib eingelesen. Beim Import entsteht noch kein Fenster -
tkinter wird zwar importiert, ``tk.Tk()`` ruft aber erst ``main()`` auf. Die
Tests laufen deshalb auch auf einem Rechner ohne Bildschirm.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "Bild-Toolbox.pyw"


@pytest.fixture(scope="session")
def toolbox():
    """Die geladene Bild-Toolbox als Modul."""
    assert SCRIPT.is_file(), f"Skript nicht gefunden: {SCRIPT}"
    spec = importlib.util.spec_from_file_location("bild_toolbox", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bild_toolbox"] = module
    spec.loader.exec_module(module)
    return module
