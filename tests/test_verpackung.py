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
LIZENZHINWEISE = QUELLE.parent / "DRITTANBIETER-LIZENZEN.md"

# Alle requirements-Dateien, deren Pakete in der EXE landen - auch eine
# kuenftige dritte. requirements-dev.txt bleibt aussen vor: ruff und pytest
# werden nie mitgeliefert.
MITGELIEFERT = [pfad for pfad in sorted(QUELLE.parent.glob("requirements*.txt"))
                if pfad.name != "requirements-dev.txt"]
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


def _paketnamen(datei):
    """Paketnamen aus einer requirements-Datei - ohne Kommentare und Versionen."""
    namen = []
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        zeile = zeile.split("#")[0].strip()
        if not zeile:
            continue
        if zeile.startswith("-"):
            # "-r andere.txt" verweist auf eine Liste, die diese Pruefung nicht
            # sieht. Lieber laut abbrechen als Pakete stillschweigend uebergehen.
            raise AssertionError(
                f"{datei.name} benutzt die Option {zeile!r} - diese Pruefung "
                "liest nur flache Paketlisten und muesste erweitert werden.")
        namen.append(re.split(r"[<>=!~\[;\s]", zeile, maxsplit=1)[0])
    assert namen, f"{datei.name} enthaelt kein einziges Paket"
    return namen


def _tabellenzeilen(text, name):
    """Zeilen der Lizenztabelle, die mit **name** beginnen - deutsch und englisch."""
    gesucht = re.escape(name.replace("_", "-"))
    return re.findall(rf"^\|\s*\*\*{gesucht}\*\*.*$", text,
                      re.MULTILINE | re.IGNORECASE)


@pytest.mark.parametrize("datei", MITGELIEFERT, ids=lambda pfad: pfad.name)
def test_lizenzhinweise_nennen_jede_abhaengigkeit(datei):
    # Die EXE liefert diese Pakete mit aus. Fehlt eines in den Hinweisen,
    # verteilt das Release Fremdcode ohne Lizenzangabe. Geprueft wird die
    # Tabellenzeile und nicht das blosse Vorkommen des Namens: "Pillow" steckt
    # auch in "pillow-heif" und in jedem Link dorthin - der Test waere blind.
    text = LIZENZHINWEISE.read_text(encoding="utf-8")
    for name in _paketnamen(datei):
        zeilen = _tabellenzeilen(text, name)
        assert len(zeilen) >= 2, (
            f"{name} braucht in {LIZENZHINWEISE.name} eine Tabellenzeile in "
            f"beiden Sprachen (gefunden: {len(zeilen)}) - mit Lizenz und Quelle, "
            "bei Binaerpaketen auch deren eingebaute Bibliotheken.")


@pytest.mark.parametrize(
    ("name", "lizenz"),
    [("libheif", "LGPLv3"), ("libde265", "LGPLv3"), ("x265", "GPLv2")],
)
def test_lizenzhinweise_nennen_die_gpl_teile(name, lizenz):
    # Diese drei Bibliotheken bringen LGPLv3 und GPLv2 in die EXE. Sie
    # namentlich mit ihrer Lizenz zu nennen ist der Kern der Pflicht - dass die
    # Namen irgendwo im Fliesstext auftauchen, genuegt dafuer nicht.
    text = LIZENZHINWEISE.read_text(encoding="utf-8")
    passend = [zeile for zeile in _tabellenzeilen(text, name) if lizenz in zeile]
    assert len(passend) >= 2, (
        f"{name} braucht in beiden Sprachen eine Tabellenzeile, die {lizenz} "
        f"nennt (gefunden: {len(passend)}).")


def _ohne_kommentare(text):
    """YAML ohne Kommentarzeilen, Fortsetzungszeilen zusammengefuegt."""
    text = re.sub(r"(?m)^\s*#.*$", "", text)
    return text.replace("\\\n", " ")


def test_lizenzhinweise_liegen_dem_release_bei():
    # Im Repository zu stehen genuegt nicht: Wer nur die EXE herunterlaedt,
    # muss die Lizenzen trotzdem bekommen. Ein Kommentar zaehlt nicht als
    # Beleg, deshalb fliegen Kommentarzeilen vorher heraus.
    yaml = _ohne_kommentare(RELEASE.read_text(encoding="utf-8"))
    assert re.search(r"^\s*cp .*DRITTANBIETER-LIZENZEN\.md", yaml, re.MULTILINE), (
        "Die Hinweise fehlen im Quellpaket.")
    assert "Copy-Item DRITTANBIETER-LIZENZEN.md" in yaml, (
        "Die Hinweise werden nicht neben die EXE gelegt.")
    assert "dist/DRITTANBIETER-LIZENZEN.md" in yaml, (
        "Die Hinweise werden nicht mit der EXE hochgeladen.")
    assert "artefakte/windows-exe/DRITTANBIETER-LIZENZEN.md" in yaml, (
        "Die Hinweise haengen nicht am Release.")


def test_release_scheitert_wenn_eine_datei_fehlt():
    # Beide Actions sind von Haus aus nachsichtig: upload-artifact warnt nur
    # ("warn" ist die Vorgabe), und action-gh-release laesst Pfade durchgehen,
    # die nichts treffen. Ohne diese zwei Zeilen entstuende ein Release ohne
    # Pruefsumme oder ohne Lizenzhinweise, ohne dass etwas rot wird.
    yaml = _ohne_kommentare(RELEASE.read_text(encoding="utf-8"))
    assert len(re.findall(r"if-no-files-found:\s*error", yaml)) == 2, (
        "Beide Upload-Schritte brauchen if-no-files-found: error.")
    assert re.search(r"fail_on_unmatched_files:\s*true", yaml), (
        "Der Release-Schritt braucht fail_on_unmatched_files: true.")
