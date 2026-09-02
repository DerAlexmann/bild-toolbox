"""Schuetzt die Eigenschaften, die erst beim Packen mit PyInstaller wichtig werden.

Diese Tests pruefen den Quelltext, nicht das Verhalten - der Fehler, um den es
geht, zeigt sich naemlich nur in der fertigen EXE und nie beim Entwickeln:
PyInstaller wertet beim Packen ausschliesslich die sichtbaren import-Zeilen aus.
Ein ueber __import__("pillow_heif") geladenes Modul landet nicht im Paket, und
die EXE meldete dann, HEIC/HEIF werde nicht unterstuetzt, obwohl dasselbe
Skript direkt ausgefuehrt einwandfrei damit umgehen konnte.
"""

import re
from pathlib import Path

import pytest

QUELLE = Path(__file__).resolve().parent.parent / "Bild-Toolbox.pyw"


@pytest.fixture(scope="module")
def quelltext():
    return QUELLE.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("paket", "muster"),
    [
        ("pillow_heif", r"^\s*import pillow_heif\b"),
        ("send2trash", r"^\s*from send2trash import\b"),
        ("icoextract", r"^\s*from icoextract import\b"),
        ("PIL", r"^\s*from PIL import\b"),
    ],
)
def test_optionale_pakete_werden_statisch_importiert(quelltext, paket, muster):
    assert re.search(muster, quelltext, re.MULTILINE), (
        f"'{paket}' muss mit einer gewoehnlichen import-Zeile geladen werden, "
        f"sonst nimmt PyInstaller es nicht mit ins Paket."
    )


def test_kein_dynamischer_import_von_zusatzmodulen(quelltext):
    # Kommentare ausklammern - dort darf __import__ als Erklaerung vorkommen.
    code = [zeile for zeile in quelltext.splitlines()
            if not zeile.lstrip().startswith("#")]
    treffer = [zeile.strip() for zeile in code if re.search(r"__import__\s*\(", zeile)]
    assert not treffer, (
        "__import__() ist fuer PyInstaller unsichtbar. Zusatzmodule bitte mit "
        "einer gewoehnlichen import-Zeile in einem try/except laden. "
        f"Gefunden: {treffer}"
    )


def test_heif_erkennung_haengt_am_import(toolbox):
    # Ist pillow-heif in dieser Umgebung vorhanden, muss die Toolbox es auch
    # melden - sonst stimmt die Anzeige unter "Info & Hilfe" nicht.
    try:
        import pillow_heif  # noqa: F401
    except ImportError:
        pytest.skip("pillow-heif ist in dieser Umgebung nicht installiert")
    assert toolbox.HAS_HEIF is True
    assert toolbox.pillow_heif is not None


def test_register_ueberlebt_fehlendes_paket(toolbox, monkeypatch):
    # Ohne pillow-heif darf nichts abstuerzen, _register meldet einfach False.
    monkeypatch.setattr(toolbox, "pillow_heif", None)
    assert toolbox._register("register_heif_opener") is False
    assert toolbox._register("gibt_es_nicht") is False
