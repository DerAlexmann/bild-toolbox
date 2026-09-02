# Bild-Toolbox

**Alle Bildwerkzeuge in einer Anwendung** – ein Desktop-Programm für Windows, macOS und Linux,
das Bildvergleich, Duplikat-Suche, Format-Konvertierung, Icon-Extraktion und mehr unter einer
Oberfläche zusammenfasst. Eine einzige Python-Datei, keine Installation, keine Cloud, keine
Telemetrie – alles läuft lokal.

[![CI](https://github.com/DerAlexmann/bild-toolbox/actions/workflows/ci.yml/badge.svg)](https://github.com/DerAlexmann/bild-toolbox/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

*[English version below / Englische Fassung: **[README.en.md](README.en.md)**]*

---

## Screenshots

![Startseite mit allen Modulen als Kacheln](docs/screenshots/start.png)

<details>
<summary><b>Weitere Ansichten</b> – Duplikat-Finder, Format-Konverter, dunkles Schema</summary>

### Duplikat-Finder

Byte-identische Bilder werden nach Dateigröße und MD5-Prüfsumme gruppiert. Die
erste Datei jeder Gruppe ist als *[behalten]* markiert, alles Weitere lässt sich
gruppenweise löschen oder verschieben.

![Duplikat-Finder mit gefundenen Gruppen](docs/screenshots/duplikate.png)

### Format-Konverter

![Format-Konverter mit gefüllter Batch-Liste](docs/screenshots/konverter.png)

### Dunkles Farbschema

Umschaltbar zur Laufzeit, unten links in der Seitenleiste.

![Startseite im dunklen Farbschema](docs/screenshots/start-dunkel.png)

</details>

---

## Module

| Modul | Was es tut |
|---|---|
| 🖼 **Bild-Vergleich** | Zwei Bilder im Split-Screen prüfen – inklusive Metadaten und MD5-Prüfsumme. Öffnen, tauschen, löschen. |
| 🔎 **Duplikat-Finder** | Byte-identische Bilder über Dateigröße und MD5 finden und gruppenweise löschen oder verschieben. |
| 🧩 **Ähnliche Bilder** | Visuell ähnliche Bilder über einen Perceptual Hash erkennen – Varianten, Skalierungen, Neukomprimierungen. |
| 📐 **Dimensions-Filter** | Bilder aufspüren, die in Breite **und** Höhe unter einem Schwellwert liegen, und aussortieren. |
| 🏷 **Batch-Umbenennung** | Ganze Ordner nach einem Muster umbenennen – mit Zähler, Originalname, Datum und Bildgröße. |
| 📊 **Statistiken** | Formate, Auflösungen und Dateigrößen eines Ordners auswerten. |
| 🔄 **Format-Konverter** | JPEG, PNG, WebP, AVIF, BMP, GIF, TIFF, ICO und PPM – einzeln oder als Stapelverarbeitung. |
| 🖥 **Icon-Extraktor** | Alle Icon-Größen aus EXE-, DLL- und Bilddateien holen und als ICO oder PNG sichern. |
| ℹ **Info & Hilfe** | Kurzbeschreibung aller Module und Status der optionalen Bibliotheken. |

**Weitere Eigenschaften**

- Helles und dunkles Farbschema, umschaltbar zur Laufzeit
- Zweisprachige Oberfläche (Deutsch / Englisch), Sprache wird beim ersten Start
  aus dem System übernommen
- Tastatur: `Strg+1` … `Strg+9` wechseln direkt zwischen den Modulen, `Esc` führt zurück zum Start
- Löschen wahlweise in den Papierkorb (mit `send2trash`) statt endgültig
- Unterstützte Formate: JPG, JPEG, PNG, BMP, GIF, WebP, AVIF, TIF, TIFF, ICO, JFIF, HEIC, HEIF, PPM

---

## Installation

### Voraussetzungen

- **Python 3.9 oder neuer** ([python.org](https://www.python.org/downloads/)) – unter Windows
  beim Installieren *„Add Python to PATH"* anhaken
- **Tkinter** – bei den offiziellen Windows- und macOS-Installern bereits enthalten.
  Unter Debian/Ubuntu zusätzlich: `sudo apt install python3-tk`

### Schnellstart

```bash
git clone https://github.com/DerAlexmann/bild-toolbox.git
cd bild-toolbox
pip install -r requirements.txt
```

Danach starten:

- **Windows:** Doppelklick auf `Bild-Toolbox.pyw` (die Endung `.pyw` startet das Programm
  ohne Konsolenfenster)
- **macOS / Linux:** `python Bild-Toolbox.pyw`

### Optionale Zusatzmodule

Die Toolbox läuft auch ohne diese Pakete – einzelne Funktionen sind dann aber nicht verfügbar.
Der Reiter *Info & Hilfe* zeigt jederzeit an, was installiert ist.

```bash
pip install -r requirements-optional.txt
```

| Paket | Wofür | Ohne das Paket |
|---|---|---|
| `Pillow` | Bilder lesen, schreiben und skalieren | **Pflicht** – das Programm startet nicht |
| `send2trash` | Löschen in den Papierkorb statt endgültig | Es wird endgültig gelöscht |
| `icoextract` | Icons aus EXE- und DLL-Dateien lesen | Icon-Extraktor kann nur Bilddateien lesen |
| `pillow-heif` | HEIC- und HEIF-Dateien öffnen | Diese Formate werden übersprungen |

---

## Bedienung in Kürze

1. Programm starten – die Startseite zeigt alle Module als Kacheln.
2. Modul anklicken, Ordner oder Datei auswählen, Suche bzw. Umwandlung starten.
3. Ergebnisse werden als Liste mit Vorschaubildern angezeigt (maximal 300 Vorschauen pro
   Trefferliste, damit die Oberfläche flüssig bleibt).
4. Aktionen wie *Löschen* oder *Verschieben* betreffen immer nur die ausgewählten Einträge und
   fragen vorher nach.

> [!TIP]
> Aktivieren Sie in den Einstellungen den Papierkorb-Modus (`send2trash`), solange Sie sich mit
> den Aufräum-Modulen vertraut machen. Gelöschtes lässt sich dann wiederherstellen.

---

## Einstellungen und erzeugte Dateien

Das Programm legt neben dem Skript zwei Dateien an:

| Datei | Inhalt |
|---|---|
| `bild-toolbox.json` | Gewählte Sprache und Farbschema |
| `bild-toolbox_fehler.log` | Wird **nur** angelegt, wenn ein echter Fehler auftritt |

Ist der Ordner nicht beschreibbar, weichen beide Dateien auf das
Benutzerverzeichnis aus. In einer mit PyInstaller gebauten EXE liegen sie neben
der EXE, damit Sprache und Farbschema einen Neustart überleben. Beide Dateien
sind in `.gitignore` eingetragen.

---

## Plattform-Hinweise

Die Toolbox ist plattformübergreifend geschrieben, ist aber unter **Windows** am ausgereiftesten:

- Der **Icon-Extraktor** kann Icons aus `.exe`, `.dll`, `.sys`, `.mun`, `.ocx`, `.cpl` und `.scr`
  auslesen – das ist naturgemäß nur unter Windows sinnvoll. Bilddateien liest er überall.
- Die Oberfläche nutzt die Schriftarten *Segoe UI* und *Consolas*. Unter macOS und Linux ersetzt
  Tk sie automatisch, das Layout kann dadurch leicht abweichen.
- *Im Explorer zeigen* und *Öffnen mit Standardprogramm* nutzen `explorer`, `open` bzw.
  `xdg-open`, je nach System.

---

## Eigene Sprache ergänzen

Quellsprache ist Deutsch: Der deutsche Text im Code ist zugleich der Übersetzungsschlüssel.
Eine weitere Sprache kommt in zwei Schritten dazu (ganz unten in `Bild-Toolbox.pyw`):

1. Kürzel und Anzeigename in `LANGUAGE_NAMES` eintragen, z. B. `"fr": "Français"`.
2. In `TRANSLATIONS` einen Eintrag `"fr": { ... }` anlegen und die gewünschten Zeilen übersetzen.

Nicht übersetzte Zeilen erscheinen automatisch auf Deutsch – eine unvollständige Tabelle ist
also unproblematisch. Platzhalter in geschweiften Klammern (`{count}`, `{path}`, `{error}` …)
müssen in der Übersetzung unverändert vorkommen; ihre Reihenfolge im Satz ist frei.
Die Testsuite prüft das automatisch.

## Eigenes Farbschema ergänzen

In `THEMES` eine weitere Palette mit **denselben** Schlüsselnamen anlegen. `apply_theme()`
schreibt die Werte in die Modulvariablen, der übrige Code muss vom Umschalten nichts wissen.

---

## Entwicklung

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check .            # Linting
python -m pytest        # Tests (Übersetzungen, Themes, Modulregistrierung)
```

Die Tests sind bewusst GUI-frei: Sie laden `Bild-Toolbox.pyw` als Modul und prüfen die
Datenstrukturen, ohne ein Fenster zu öffnen.

---

## Mitwirken

Fehlerberichte, Übersetzungen und Verbesserungsvorschläge sind willkommen.
Siehe [CONTRIBUTING.md](CONTRIBUTING.md) und den [Verhaltenskodex](CODE_OF_CONDUCT.md).
Sicherheitsrelevante Meldungen bitte nach [SECURITY.md](SECURITY.md).

## Änderungen

Alle Versionen sind in [CHANGELOG.md](CHANGELOG.md) dokumentiert.

---

## Lizenz und Entstehung

[MIT](LICENSE) · Copyright © 2026 Alexander Unverhau
· **Erstellt mit Unterstützung von Claude AI (Anthropic)**

Die Bild-Toolbox ist in Zusammenarbeit mit Claude AI entstanden. Dieser Hinweis
steht der Transparenz halber überall dort, wo auch der Copyright-Vermerk steht –
im Kopf von `Bild-Toolbox.pyw`, im Reiter *Info & Hilfe* der Anwendung, in
dieser Datei und in [NOTICE](NOTICE). An der MIT-Lizenz ändert er nichts.

Das Programm vereint die früheren Einzelprogramme *Bildbetrachter Pro 2.0*,
*Icon Extraktor*, *Universal Image Converter* und *Bild-Dimensions-Filter* in
einer Oberfläche.
