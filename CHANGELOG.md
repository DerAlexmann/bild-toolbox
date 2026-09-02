# Änderungsprotokoll

Alle nennenswerten Änderungen an diesem Projekt werden hier festgehalten.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionsnummern folgen der [Semantischen Versionierung](https://semver.org/lang/de/).

## [Unveröffentlicht]

<!-- Neue Einträge hier sammeln, bis die nächste Version getaggt wird. -->

## [1.0.0] – 2026-09-02

Erste öffentliche Veröffentlichung. Die Bild-Toolbox vereint die früheren
Einzelprogramme *Bildbetrachter Pro 2.0*, *Icon Extraktor*,
*Universal Image Converter* und *Bild-Dimensions-Filter* in einer Oberfläche.

### Hinzugefügt

- **Bild-Vergleich** – zwei Bilder im Split-Screen, mit Metadaten und
  MD5-Prüfsumme; öffnen, tauschen und löschen
- **Duplikat-Finder** – byte-identische Bilder über Dateigröße und MD5,
  gruppenweise löschen oder verschieben
- **Ähnliche Bilder** – visuell ähnliche Bilder über einen Perceptual Hash
- **Dimensions-Filter** – Bilder aufspüren, die in Breite und Höhe unter einem
  Schwellwert liegen
- **Batch-Umbenennung** – Muster mit Zähler, Originalname, Datum und Bildgröße
- **Statistiken** – Formate, Auflösungen und Dateigrößen eines Ordners
- **Format-Konverter** – JPEG, PNG, WebP, AVIF, BMP, GIF, TIFF, ICO und PPM,
  einzeln oder als Stapelverarbeitung
- **Icon-Extraktor** – alle Icon-Größen aus EXE-, DLL- und Bilddateien,
  speicherbar als ICO oder PNG
- **Info & Hilfe** – Kurzbeschreibung aller Module und Status der optionalen
  Bibliotheken
- Helles und dunkles Farbschema, zur Laufzeit umschaltbar
- Zweisprachige Oberfläche (Deutsch/Englisch); die Sprache wird beim ersten
  Start aus dem System übernommen
- Tastenkürzel `Strg+1` … `Strg+9` für die Module, `Esc` zurück zum Start
- Optionales Löschen in den Papierkorb über `send2trash`
- Unterstützung für HEIC und HEIF über `pillow-heif`; AVIF bringt Pillow ab
  Version 11.3 selbst mit, ältere Pillow-Versionen bekommen es von `pillow-heif`
- Fehlerprotokoll, das erst bei einem echten Fehler angelegt wird
- Einstellungen und Fehlerprotokoll landen neben dem Programm – in einer
  mit PyInstaller gebauten EXE neben der EXE, bei einem schreibgeschützten
  Ordner im Benutzerverzeichnis
- HEIC- und HEIF-Unterstützung steht auch in der gepackten EXE zur Verfügung:
  `pillow-heif` wird mit einer gewöhnlichen `import`-Zeile geladen, damit
  PyInstaller es beim Packen findet

[Unveröffentlicht]: https://github.com/DerAlexmann/bild-toolbox/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/DerAlexmann/bild-toolbox/releases/tag/v1.0.0
