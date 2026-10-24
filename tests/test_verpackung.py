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
SYMBOL = QUELLE.parent / "bild_toolbox.ico"
RELEASE = QUELLE.parent / ".github" / "workflows" / "release.yml"
ANFORDERUNGEN = QUELLE.parent / "requirements.txt"
SYMBOLGROESSEN = {16, 24, 32, 48, 64, 128, 256}

# Image.Resampling, Image.Palette und die uebrigen Enums kamen mit Pillow
# 9.1.0 (01.04.2022); vorher hiessen die Konstanten Image.LANCZOS usw.
ENUMS_SEIT = (9, 1)


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


def test_pillow_untergrenze_passt_zum_quelltext():
    # Eine zu kleine Untergrenze faellt beim Entwickeln nie auf - pip holt
    # immer die neueste passende Version. Bemerken wuerde es nur, wer genau
    # die zugesagte Mindestversion installiert: Das Programm braechte beim
    # ersten Vorschaubild einen AttributeError.
    benutzte_enums = sorted(set(re.findall(
        r"Image\.(Resampling|Palette|Dither|Quantize)\.", QUELLE.read_text(encoding="utf-8"))))
    treffer = re.search(r"^Pillow>=(\d+)\.(\d+)", ANFORDERUNGEN.read_text(encoding="utf-8"),
                        re.MULTILINE)
    assert treffer, "requirements.txt nennt keine Untergrenze fuer Pillow"

    gefordert = (int(treffer[1]), int(treffer[2]))
    if benutzte_enums:
        assert gefordert >= ENUMS_SEIT, (
            f"Der Quelltext benutzt Image.{{{','.join(benutzte_enums)}}}, die es erst ab "
            f"Pillow {ENUMS_SEIT[0]}.{ENUMS_SEIT[1]} gibt - requirements.txt verlangt aber "
            f"nur {gefordert[0]}.{gefordert[1]}.")


def test_programmsymbol_liegt_im_projekt():
    # Ohne die .ico baut der Release-Job keine EXE mit Symbol, und das direkt
    # gestartete Skript bekaeme wieder die Feder von Tk.
    assert SYMBOL.is_file(), (
        f"{SYMBOL.name} fehlt - neu erzeugen mit: python icon_erzeugen.py")


def test_programmsymbol_bringt_alle_groessen_mit():
    # Windows sucht sich je nach Ansicht eine Groesse aus. Fehlt sie, rechnet
    # es selbst herunter, und das Symbol wird in der Taskleiste unsauber.
    from PIL import Image
    with Image.open(SYMBOL) as bild:
        vorhanden = {breite for breite, hoehe in bild.info["sizes"]}
    assert SYMBOLGROESSEN <= vorhanden, f"fehlende Groessen: {SYMBOLGROESSEN - vorhanden}"


def test_symboldatei_heisst_wie_im_quelltext(toolbox):
    assert toolbox.ICON_NAME == SYMBOL.name


def test_release_baut_die_exe_mit_symbol():
    text = RELEASE.read_text(encoding="utf-8")
    assert "--icon bild_toolbox.ico" in text, (
        "Ohne --icon traegt die EXE das Standardsymbol von PyInstaller.")
    assert re.search(r"^\s*cp .*bild_toolbox\.ico", text, re.MULTILINE), (
        "Das Quellpaket braucht die .ico, sonst zeigt das Skript kein Symbol.")


def test_symbol_uebersteht_eine_ablehnung_von_tk(toolbox, monkeypatch):
    # Tk lehnt eine .ico ab, wenn es mit dem Format nichts anfangen kann. Das
    # Programm laeuft dann ohne eigenes Symbol weiter, statt beim Start zu
    # scheitern.
    class Fenster:
        def iconbitmap(self, **_):
            raise toolbox.tk.TclError("kein Symbol")

    monkeypatch.setattr(toolbox.sys, "platform", "win32")
    toolbox.set_window_icon(Fenster())
