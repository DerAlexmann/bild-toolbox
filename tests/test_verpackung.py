"""Schuetzt die Eigenschaften, die erst beim Packen mit PyInstaller wichtig werden.

Diese Tests pruefen den Quelltext, nicht das Verhalten - der Fehler, um den es
geht, zeigt sich naemlich nur in der fertigen EXE und nie beim Entwickeln:
PyInstaller wertet beim Packen ausschliesslich die sichtbaren import-Zeilen aus.
Ein ueber __import__("pillow_heif") geladenes Modul landet nicht im Paket, und
die EXE meldete dann, HEIC/HEIF werde nicht unterstuetzt, obwohl dasselbe
Skript direkt ausgefuehrt einwandfrei damit umgehen konnte.
"""

import importlib.util
import os
import re
from pathlib import Path

import pytest

QUELLE = Path(__file__).resolve().parent.parent / "Bild-Toolbox.pyw"
SYMBOL = QUELLE.parent / "bild_toolbox.ico"
RELEASE = QUELLE.parent / ".github" / "workflows" / "release.yml"
ANFORDERUNGEN = QUELLE.parent / "requirements.txt"
LIZENZHINWEISE = QUELLE.parent / "DRITTANBIETER-LIZENZEN.md"

# Alle requirements-Dateien, deren Pakete in der EXE landen - auch eine
# kuenftige vierte. requirements-dev.txt bleibt aussen vor: ruff und pytest
# werden nie mitgeliefert. requirements-build.txt zaehlt dazu, denn der
# Bootloader von PyInstaller steckt in jeder gebauten EXE.
MITGELIEFERT = [pfad for pfad in sorted(QUELLE.parent.glob("requirements*.txt"))
                if pfad.name != "requirements-dev.txt"]
BAUVERSIONEN = QUELLE.parent / "requirements-build.txt"
LAUFZEIT = [pfad for pfad in MITGELIEFERT if pfad != BAUVERSIONEN]
CI = QUELLE.parent / ".github" / "workflows" / "ci.yml"
VERSIONSINFO = QUELLE.parent / "versionsinfo_erzeugen.py"
SYMBOLGROESSEN = {16, 24, 32, 48, 64, 128, 256}

# Image.Resampling, Image.Palette und die uebrigen Enums kamen mit Pillow
# 9.1.0 (01.04.2022); vorher hiessen die Konstanten Image.LANCZOS usw.
ENUMS_SEIT = (9, 1)


@pytest.fixture(scope="module")
def quelltext():
    return QUELLE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def versionsinfo():
    """versionsinfo_erzeugen.py als Modul - ein gewoehnliches Skript daneben."""
    spec = importlib.util.spec_from_file_location("versionsinfo_erzeugen",
                                                  VERSIONSINFO)
    assert spec is not None and spec.loader is not None, (
        f"Konnte fuer {VERSIONSINFO} keine Modulspezifikation erzeugen.")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


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


def test_heic_schreiben_und_lesen_mit_pillow_heif(tmp_path, toolbox):
    """Eine HEIC-Datei wirklich erzeugen und wieder oeffnen.

    Importieren allein beweist nichts: pillow-heif ist ein Plugin von Pillow.
    Hebt eine der beiden Seiten ihre Hauptversion an, kann register_heif_opener()
    stillschweigend scheitern - _register() verschluckt den Fehler, HAS_HEIF
    wird False, und die fertige EXE meldete nur noch "keine
    HEIC-Unterstuetzung". Dieser Test faellt stattdessen auf.
    """
    if os.environ.get("HEIC_PFLICHT"):
        # In der CI ist dieser Test Pflicht: Ein Ueberspringen waere gruen,
        # ohne dass etwas geschrieben oder gelesen wurde.
        import pillow_heif  # noqa: F401
    else:
        pytest.importorskip("pillow_heif",
                            reason="pillow-heif ist ein optionales Zusatzmodul")
    from PIL import Image

    assert toolbox.HAS_HEIF is True, (
        "register_heif_opener() ist fehlgeschlagen - passen Pillow und "
        "pillow-heif noch zusammen?")

    pfad = tmp_path / "probe.heic"
    Image.new("RGB", (64, 48), (10, 120, 200)).save(pfad, "HEIF", quality=80)
    assert pfad.stat().st_size > 0

    with Image.open(pfad) as wieder:
        wieder.load()
        assert wieder.size == (64, 48)
        assert wieder.mode in ("RGB", "RGBA")


def _normal(name):
    """Paketnamen vergleichbar machen: Pillow, pillow und pillow_heif."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _versionen(datei):
    """Paketname -> (Vergleich, Versionszahlen) aus einer requirements-Datei."""
    paare = {}
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        zeile = zeile.split("#")[0].strip()
        if not zeile:
            continue
        treffer = re.fullmatch(r"([\w.\-]+)\s*(==|>=)\s*(\d+(?:\.\d+)*)", zeile)
        assert treffer, (
            f"{datei.name}: {zeile!r} ist weder ==X.Y noch >=X.Y - diese "
            "Pruefung versteht nur einfache Zeilen.")
        name, vergleich, version = treffer.groups()
        paare[_normal(name)] = (vergleich,
                                tuple(int(teil) for teil in version.split(".")))
    return paare


def test_bauversionen_sind_festgenagelt():
    # Untergrenzen wie ">=9.1" sind fuer das Skript richtig, fuer die
    # veroeffentlichte EXE nicht: Die ausgelieferte Datei haengt sonst davon
    # ab, was am Tag des Baus die neueste Fassung war. Der Suchausdruck in
    # _versionen() laesst auch Platzhalter wie "==13.*" nicht durch.
    fest = _versionen(BAUVERSIONEN)
    assert fest, f"{BAUVERSIONEN.name} nennt kein einziges Paket"
    for name, (vergleich, _version) in fest.items():
        assert vergleich == "==", (
            f"{name} ist in {BAUVERSIONEN.name} nicht festgenagelt.")


@pytest.mark.parametrize("datei", LAUFZEIT, ids=lambda pfad: pfad.name)
def test_bauversionen_decken_alle_pakete_ab(datei):
    # Vor dem Festnageln installierte der Release-Job die requirements-Dateien
    # selbst - ein neues Zusatzmodul war damit automatisch in der EXE. Jetzt
    # zaehlt nur noch die Bauliste: Fehlt dort ein Paket, meldete die EXE die
    # Funktion stillschweigend als "nicht installiert".
    fest = _versionen(BAUVERSIONEN)
    for name, (_vergleich, untergrenze) in _versionen(datei).items():
        assert name in fest, (
            f"{name} steht in {datei.name}, aber nicht in "
            f"{BAUVERSIONEN.name} - die EXE wuerde ohne dieses Paket gebaut.")
        assert fest[name][1] >= untergrenze, (
            f"{name}: {BAUVERSIONEN.name} nagelt eine Fassung unterhalb der "
            f"Untergrenze aus {datei.name} fest.")


def test_ci_prueft_die_festgenagelten_versionen():
    # Ohne diesen Job laeuft die gepinnte Kombination erstmals beim Tag.
    yaml = _ohne_kommentare(CI.read_text(encoding="utf-8"))
    assert "-r requirements-build.txt" in yaml, (
        "Kein CI-Job installiert die festgenagelten Bauversionen.")
    assert "test_heic_schreiben_und_lesen" in yaml, (
        "Die CI ruft den HEIC-Rundlauf nicht namentlich auf.")
    assert yaml.count("HEIC_PFLICHT") >= 2, (
        "Ohne HEIC_PFLICHT darf der Rundlauf uebersprungen werden und der "
        "Schritt waere trotzdem gruen.")


def test_release_sieht_sich_die_fertige_exe_an():
    # Der Workflow-Text allein beweist nicht, dass die Metadaten in der Datei
    # landen. Dieser Schritt liest sie aus der gebauten EXE zurueck.
    yaml = _ohne_kommentare(RELEASE.read_text(encoding="utf-8"))
    assert "VersionInfo" in yaml, (
        "Nach dem Bau wird die Versionsressource der EXE nicht geprueft.")
    assert "GITHUB_REF_TYPE" in yaml, (
        "Der Tag wird nicht gegen die Version der EXE gehalten - eine "
        "vergessene Anhebung von APP_VERSION fiele nicht auf.")


def test_release_baut_aus_den_festen_versionen():
    # Geprueft werden die Installationszeilen, nicht die ganze Datei: Der
    # Quellpaket-Job kopiert requirements-optional.txt zu Recht mit ins ZIP.
    yaml = _ohne_kommentare(RELEASE.read_text(encoding="utf-8"))
    zeilen = [zeile for zeile in yaml.splitlines() if "pip install" in zeile]
    assert zeilen, "Im Release-Workflow wird nichts installiert?"
    assert any("-r requirements-build.txt" in zeile for zeile in zeilen), (
        "Der Release-Job installiert nicht aus requirements-build.txt.")
    gemischt = [zeile for zeile in zeilen
                if "requirements-optional.txt" in zeile or "requirements.txt" in zeile]
    assert not gemischt, (
        f"Der Build mischt wieder Untergrenzen hinein: {gemischt}")


def test_exe_traegt_produktname_und_version():
    # Ohne --version-file bleiben die Dateieigenschaften leer. Produktname und
    # Produktversion verlangt ausserdem jede Code-Signierung.
    yaml = _ohne_kommentare(RELEASE.read_text(encoding="utf-8"))
    assert "python versionsinfo_erzeugen.py" in yaml, (
        "Die Versionsdatei wird im Release nicht erzeugt.")
    assert "--version-file versionsinfo.txt" in yaml, (
        "PyInstaller bekommt die Versionsdatei nicht uebergeben.")


def test_versionsinfo_kommt_aus_dem_quelltext(toolbox, versionsinfo):
    # Eine zweite Stelle mit der Versionsnummer waere eine Stelle zu viel:
    # Der Erzeuger liest APP_NAME und APP_VERSION aus Bild-Toolbox.pyw. Wer
    # die Angaben dort fest einbaut, faellt hier auf.
    assert versionsinfo._aus_quelltext("APP_VERSION") == toolbox.APP_VERSION
    assert versionsinfo._aus_quelltext("APP_NAME") == toolbox.APP_NAME

    text = versionsinfo.inhalt(toolbox.APP_NAME, toolbox.APP_VERSION)
    haupt, neben, flick, bau = versionsinfo.vierstellig(toolbox.APP_VERSION)

    assert f"filevers=({haupt}, {neben}, {flick}, {bau})" in text
    assert f"StringStruct('ProductVersion', '{toolbox.APP_VERSION}')" in text
    assert f"StringStruct('ProductName', '{toolbox.APP_NAME}')" in text
    # Der Hinweis auf die KI-Unterstuetzung steht ueberall dort, wo auch der
    # Copyright-Vermerk steht - die Dateieigenschaften sind so eine Stelle.
    assert "Claude AI" in text


def test_versionsdatei_wird_von_pyinstaller_angenommen(tmp_path, toolbox,
                                                       versionsinfo):
    # Ein Tippfehler in der Vorlage faellt sonst erst im Release-Job auf.
    versioninfo = pytest.importorskip(
        "PyInstaller.utils.win32.versioninfo",
        reason="PyInstaller ist nur zum Bauen noetig, nicht fuer die Tests")
    datei = tmp_path / "versionsinfo.txt"
    datei.write_text(versionsinfo.inhalt(toolbox.APP_NAME, toolbox.APP_VERSION),
                     encoding="utf-8")

    info = versioninfo.load_version_info_from_text_file(str(datei))
    felder = {eintrag.name: eintrag.val
              for eintrag in info.kids[0].kids[0].kids}
    assert felder["ProductName"] == toolbox.APP_NAME
    assert felder["ProductVersion"] == toolbox.APP_VERSION
    assert felder["OriginalFilename"] == f"{toolbox.APP_NAME}.exe"


@pytest.mark.parametrize(
    ("version", "erwartet"),
    [
        ("1.1.0", (1, 1, 0, 0)),
        ("2.10.3", (2, 10, 3, 0)),
        ("1.2", (1, 2, 0, 0)),
        ("1", (1, 0, 0, 0)),
        ("1.1.0.4", (1, 1, 0, 4)),
    ],
)
def test_vierstellig_rechnet_richtig(versionsinfo, version, erwartet):
    # Von Hand hingeschrieben und nicht mit derselben Funktion errechnet:
    # Sonst prueft der Test nur, dass die Funktion sich selbst gleicht.
    assert versionsinfo.vierstellig(version) == erwartet


@pytest.mark.parametrize("version", ["1.2.0rc1", "1.2.0-beta", "v1.2.0", "",
                                     "1..0", "1.2.3.4.5", "1.70000.0"])
def test_vierstellig_lehnt_unbrauchbares_mit_klartext_ab(versionsinfo, version):
    # Ein "invalid literal for int()" mitten im Release-Lauf sagt niemandem,
    # dass APP_VERSION gemeint ist.
    with pytest.raises(SystemExit) as fehler:
        versionsinfo.vierstellig(version)
    assert "APP_VERSION" in str(fehler.value)
