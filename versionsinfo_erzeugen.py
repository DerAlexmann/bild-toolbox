"""Erzeugt versionsinfo.txt - die Versionsmetadaten fuer die Windows-EXE.

Der Explorer zeigt unter "Eigenschaften" nur, was in der EXE selbst steht.
PyInstaller legt von sich aus keine Versionsressource an: Ohne diese Datei
bleiben Produktname, Version und Urheber leer. Wer die EXE herunterlaedt, kann
dann nicht einmal nachsehen, welche Fassung er vor sich hat.

Die Angaben stammen aus APP_NAME und APP_VERSION in Bild-Toolbox.pyw - aus
derselben Quelle, aus der auch die Titelleiste und der Reiter "Info & Hilfe"
lesen. Gepflegt wird die Version also weiterhin an genau einer Stelle. Gelesen
wird der Quelltext mit einem Suchausdruck und nicht per Import, damit hier
kein Tkinter und kein Pillow gebraucht wird.

Die erzeugte Datei ist abgeleitet und gehoert nicht ins Repository - sie steht
in .gitignore. Der Release-Workflow erzeugt sie vor dem Packen neu.

Aufruf:     python versionsinfo_erzeugen.py
Danach:     pyinstaller ... --version-file versionsinfo.txt ...
"""

from __future__ import annotations

import re
from pathlib import Path

HIER = Path(__file__).resolve().parent
QUELLE = HIER / "Bild-Toolbox.pyw"
ZIEL = HIER / "versionsinfo.txt"

URHEBER = "Alexander Unverhau"
JAHR = "2026"
BESCHREIBUNG = "Bild-Toolbox - alle Bildwerkzeuge in einer Anwendung"
HINWEIS = "Lizenzen der mitgelieferten Komponenten: DRITTANBIETER-LIZENZEN.md"

# Nur ASCII in den Feldern: Die Datei wird von PyInstaller eingelesen und als
# Ressource in die EXE gelegt. Umlaute waeren eine Fehlerquelle ohne Not,
# deshalb sind die Texte so formuliert, dass sie keine brauchen.
SPRACHE = 1031          # Deutsch, die Ausgangssprache des Programms
ZEICHENSATZ = 1200      # Unicode
GRENZE = 65535          # so weit reicht eine Stelle im Versionsfeld


def _aus_quelltext(name: str) -> str:
    """Den Wert einer Zeichenketten-Konstante aus Bild-Toolbox.pyw holen.

    Gesucht wird die ganze Datei ab und nicht nur bis zum ersten Treffer:
    Stuende derselbe Name ein zweites Mal am Zeilenanfang - etwa als Beispiel
    in einem Docstring -, naehme die Suche den falschen Wert, waehrend Python
    den letzten benutzt. Dann ist Abbrechen richtiger als Raten.
    """
    text = QUELLE.read_text(encoding="utf-8")
    treffer = re.findall(rf'^{name}\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if len(treffer) != 1:
        raise SystemExit(
            f"{name} steht {len(treffer)}-mal in {QUELLE.name}, erwartet war "
            "genau eine Zeile - Quelltext geaendert?")
    if not treffer[0].isascii():
        raise SystemExit(
            f"{name} = {treffer[0]!r} enthaelt Zeichen ausserhalb von ASCII. "
            "Die Versionsressource wird als Quelltext eingelesen; hier bitte "
            "bei ASCII bleiben.")
    return treffer[0]


def vierstellig(version: str) -> tuple[int, int, int, int]:
    """"1.1.0" wird zu (1, 1, 0, 0) - Windows erwartet immer vier Zahlen.

    Fehler werden hier mit Klartext abgelehnt. Sonst stolperte der
    Release-Lauf ueber ein "invalid literal for int()", und niemand saehe auf
    Anhieb, dass APP_VERSION gemeint ist.
    """
    try:
        zahlen = [int(teil) for teil in version.split(".")]
    except ValueError:
        raise SystemExit(
            f"APP_VERSION {version!r} muss die Form 1.2.3 haben: Zahlen, "
            "durch Punkte getrennt. Vorabfassungen wie 1.2.3rc1 kann die "
            "Versionsressource von Windows nicht abbilden.") from None
    if len(zahlen) > 4:
        raise SystemExit(
            f"APP_VERSION {version!r} hat mehr als vier Stellen - die hinteren "
            "fielen stillschweigend weg.")
    if any(zahl < 0 or zahl > GRENZE for zahl in zahlen):
        raise SystemExit(
            f"APP_VERSION {version!r}: jede Stelle muss zwischen 0 und "
            f"{GRENZE} liegen, sonst lehnt PyInstaller die Datei ab.")
    zahlen += [0] * (4 - len(zahlen))
    return tuple(zahlen)                            # type: ignore[return-value]


def inhalt(name: str, version: str) -> str:
    haupt, neben, flick, bau = vierstellig(version)
    tabelle = f"{SPRACHE:04x}{ZEICHENSATZ:04x}".upper()
    dateiname = f"{name}.exe"
    return f"""# Von versionsinfo_erzeugen.py erstellt - nicht von Hand aendern.
# Quelle der Angaben: APP_NAME und APP_VERSION in Bild-Toolbox.pyw
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({haupt}, {neben}, {flick}, {bau}),
    prodvers=({haupt}, {neben}, {flick}, {bau}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '{tabelle}',
        [StringStruct('CompanyName', '{URHEBER}'),
        StringStruct('FileDescription', '{BESCHREIBUNG}'),
        StringStruct('FileVersion', {version!r}),
        StringStruct('InternalName', {name!r}),
        StringStruct('LegalCopyright',
                     'Copyright (c) {JAHR} {URHEBER} - MIT-Lizenz - '
                     'entstanden mit Hilfe von Claude AI (Anthropic)'),
        StringStruct('OriginalFilename', {dateiname!r}),
        StringStruct('ProductName', {name!r}),
        StringStruct('ProductVersion', {version!r}),
        StringStruct('Comments', '{HINWEIS}')])
      ]),
    VarFileInfo([VarStruct('Translation', [{SPRACHE}, {ZEICHENSATZ}])])
  ]
)
"""


def main() -> None:
    name = _aus_quelltext("APP_NAME")
    version = _aus_quelltext("APP_VERSION")
    ZIEL.write_text(inhalt(name, version), encoding="utf-8", newline="\n")
    print(f"geschrieben: {ZIEL}  ({name} {version})")


if __name__ == "__main__":
    main()
