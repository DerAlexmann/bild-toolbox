"""Prueft, wo Einstellungen und Fehlerprotokoll landen.

Der Ordner unterscheidet sich zwischen dem normalen Skriptbetrieb und einer
mit PyInstaller gepackten EXE. Geht das schief, verliert das Programm bei
jedem Start Sprache und Farbschema - ein Fehler, der beim Entwickeln nie
auffaellt, weil dort __file__ immer stimmt.
"""

import os

import pytest


@pytest.fixture
def frischer_ordner(toolbox):
    """Setzt den gemerkten Ordner vor und nach jedem Test zurueck."""
    vorher = toolbox._APP_FOLDER
    toolbox._APP_FOLDER = None
    yield
    toolbox._APP_FOLDER = vorher


def test_writable_erkennt_beschreibbaren_ordner(toolbox, tmp_path):
    assert toolbox._writable(str(tmp_path)) is True


def test_writable_erkennt_fehlenden_ordner(toolbox, tmp_path):
    assert toolbox._writable(str(tmp_path / "gibt-es-nicht")) is False


def test_writable_hinterlaesst_keine_datei(toolbox, tmp_path):
    toolbox._writable(str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_normalbetrieb_nutzt_den_skriptordner(toolbox, frischer_ordner):
    erwartet = os.path.dirname(os.path.abspath(toolbox.__file__))
    assert toolbox.app_folder() == erwartet


def test_gepackte_exe_nutzt_den_exe_ordner(toolbox, frischer_ordner, tmp_path, monkeypatch):
    # PyInstaller setzt sys.frozen und legt __file__ in einen temporaeren
    # Entpackordner. Massgeblich ist dann der Ordner der EXE.
    exe = tmp_path / "Bild-Toolbox.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(toolbox.sys, "frozen", True, raising=False)
    monkeypatch.setattr(toolbox.sys, "executable", str(exe))

    assert toolbox.app_folder() == str(tmp_path)


def test_schreibgeschuetzter_ordner_weicht_ins_benutzerverzeichnis_aus(
    toolbox, frischer_ordner, tmp_path, monkeypatch
):
    exe = tmp_path / "nicht-da" / "Bild-Toolbox.exe"      # Ordner existiert nicht
    monkeypatch.setattr(toolbox.sys, "frozen", True, raising=False)
    monkeypatch.setattr(toolbox.sys, "executable", str(exe))

    assert toolbox.app_folder() == os.path.expanduser("~")


def test_ordner_wird_nur_einmal_ermittelt(toolbox, frischer_ordner, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(toolbox, "_writable", lambda ordner: aufrufe.append(ordner) or True)

    erster = toolbox.app_folder()
    zweiter = toolbox.app_folder()

    assert erster == zweiter
    assert len(aufrufe) == 1, "Der Schreibtest darf nur einmal pro Programmlauf laufen"


def test_config_und_log_liegen_im_selben_ordner(toolbox, frischer_ordner):
    ordner = toolbox.app_folder()
    assert toolbox.config_path() == os.path.join(ordner, toolbox.CONFIG_NAME)
    assert toolbox.CONFIG_NAME.endswith(".json")
    assert toolbox.LOG_NAME.endswith(".log")
