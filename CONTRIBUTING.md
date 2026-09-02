# Mitwirken an der Bild-Toolbox

Danke für das Interesse! Fehlerberichte, Übersetzungen, neue Module und
Verbesserungen sind alle willkommen. Beiträge auf Deutsch und Englisch sind
gleichermaßen in Ordnung.

*Contributions in English are equally welcome – just open the issue or pull
request in whichever language you are comfortable with.*

---

## Entwicklungsumgebung einrichten

```bash
git clone https://github.com/DerAlexmann/bild-toolbox.git
cd bild-toolbox
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt -r requirements-optional.txt -r requirements-dev.txt
```

Programm starten:

```bash
python Bild-Toolbox.pyw
```

---

## Vor jedem Pull Request

```bash
ruff check .            # Linting
python -m pytest        # Tests
```

Beides läuft auch automatisch in der CI (siehe `.github/workflows/ci.yml`) –
lokal geht es nur schneller.

Bitte zusätzlich das Programm starten und das geänderte Modul einmal von Hand
durchspielen. Die Tests sind bewusst GUI-frei und prüfen die Datenstrukturen,
nicht die Bedienung.

---

## Aufbau des Projekts

Die Anwendung ist **eine einzige Datei**, `Bild-Toolbox.pyw`. Das ist Absicht:
Herunterladen, Doppelklick, fertig – ohne Installation. Bitte diesen Aufbau
beibehalten.

Grober Aufbau der Datei von oben nach unten:

| Abschnitt | Inhalt |
|---|---|
| Abhängigkeiten | Pillow (Pflicht) sowie optionale Zusatzmodule, jedes über ein `HAS_...`-Flag |
| Ablageort | `app_folder()` – wohin Einstellungen und Fehlerprotokoll geschrieben werden, Skript- bzw. EXE-Ordner mit Rückfall auf das Benutzerverzeichnis |
| Logging | `ErrorOnlyHandler` – schreibt erst bei einem echten Fehler eine Datei |
| Konstanten | `APP_NAME`, `APP_VERSION`, Dateiendungen, Grenzwerte |
| `THEMES` | Farbpaletten hell/dunkel |
| Sprachumschaltung | `Translator`, Konfiguration lesen und schreiben |
| Hilfsfunktionen | `human_size`, `md5_of`, `average_hash`, `iter_images` … |
| Bausteine der Oberfläche | `FlatButton`, `make_card`, `NavButton` … |
| `Module` | Basisklasse, danach je ein Modul pro Werkzeug |
| `ToolboxApp` | Hauptfenster, Navigation, Tastenkürzel |
| `TRANSLATIONS` | Sprachtabelle, ganz am Ende |

### Stil

- Schreibweise wie im Rest der Datei: vier Leerzeichen Einrückung, Zeilen bis
  100 Zeichen, sprechende deutsche Bezeichner in Kommentaren.
- Neue Abhängigkeiten nur, wenn es gar nicht anders geht – und dann **optional**
  über ein `HAS_...`-Flag, damit das Programm ohne sie weiterläuft.
- Lange Arbeiten gehören in einen Thread und melden ihr Ergebnis über
  `self.app.event_queue`, damit die Oberfläche nicht einfriert.

---

## Ein neues Modul hinzufügen

1. Eine Klasse von `Module` ableiten und `key`, `icon`, `title`, `subtitle`,
   `description` und `group` setzen.
2. `build()` implementieren – dort entsteht der Inhalt der Seite.
3. Die Klasse in `ToolboxApp.module_classes` eintragen. Die Startseite, der
   Reiter „Info & Hilfe" und die Tastenkürzel `Strg+1` … `Strg+9` lesen alle aus
   dieser Liste und aktualisieren sich von selbst.
4. Alle sichtbaren Texte durch `_( ... )` führen und die deutschen Zeilen in
   `TRANSLATIONS` ergänzen.

> Die Tastenkürzel decken die ersten neun Einträge ab. Wächst die Liste
> darüber hinaus, muss `_bind_keys()` angepasst werden – ein Test weist darauf
> hin.

---

## Eine Sprache hinzufügen oder verbessern

Quellsprache ist Deutsch: der deutsche Text im Code **ist** der Schlüssel.

1. Kürzel und Anzeigename in `LANGUAGE_NAMES` eintragen, z. B. `"fr": "Français"`.
2. In `TRANSLATIONS` einen Eintrag `"fr": { ... }` anlegen und übersetzen.

Regeln:

- Nicht übersetzte Zeilen erscheinen automatisch auf Deutsch. Eine
  unvollständige Tabelle ist also unproblematisch – lieber wenige gute
  Übersetzungen als viele maschinelle.
- Platzhalter in geschweiften Klammern – `{count}`, `{path}`, `{error}` … –
  müssen in der Übersetzung unverändert vorkommen. Ihre Reihenfolge im Satz ist
  frei. `python -m pytest` prüft das.

---

## Ein Farbschema hinzufügen

In `THEMES` eine weitere Palette anlegen, die **exakt dieselben** Schlüssel
enthält wie die vorhandenen. `apply_theme()` schreibt die Werte per
`globals().update()` in die Modulvariablen; der übrige Code benutzt einfach
`BG`, `CARD`, `TEXT` … und muss vom Umschalten nichts wissen.

Genau wegen dieses Musters ist die Ruff-Regel `F821` (undefined name) in
`pyproject.toml` abgeschaltet – die Farbnamen entstehen erst zur Laufzeit.

---

## Commits

Kurze, aussagekräftige Betreffzeile im Imperativ, gern mit Präfix:

```
konverter: AVIF-Qualität war nicht einstellbar
i18n: französische Übersetzung ergänzt
docs: Installationshinweis für Linux
```

---

## Eigenständige EXE bauen

`.github/workflows/release.yml` baut bei einem Versions-Tag automatisch eine
Windows-EXE mit PyInstaller. Lokal geht das so:

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name "Bild-Toolbox"             --collect-all pillow_heif Bild-Toolbox.pyw
```

> [!IMPORTANT]
> **Optionale Module müssen mit einer gewöhnlichen `import`-Zeile geladen
> werden.** PyInstaller wertet beim Packen nur die sichtbaren `import`-Zeilen
> aus. Ein über `__import__("name")` geladenes Modul landet nicht mit im Paket –
> die fertige EXE meldete dann, HEIC/HEIF werde nicht unterstützt, obwohl
> dasselbe Skript direkt ausgeführt einwandfrei damit umging. Genau deshalb
> steht `import pillow_heif` oben in der Datei als normale Zeile.
> `tests/test_verpackung.py` wacht darüber. `--collect-all pillow_heif` ist
> zusätzliche Absicherung und kostet nichts.

> [!NOTE]
> Im `--onefile`-Modus entpackt PyInstaller das Programm bei jedem Start in
> einen temporären Ordner. Damit die Einstellungen das überleben, fragt
> `app_folder()` `sys.frozen` ab und legt `bild-toolbox.json` und
> `bild-toolbox_fehler.log` im gepackten Zustand **neben der EXE** ab statt
> neben `__file__`. Ist dieser Ordner nicht beschreibbar – etwa unter
> `C:\Program Files` –, weicht die Ablage auf das Benutzerverzeichnis aus.
> Wer an dieser Stelle etwas ändert, sollte `tests/test_ablageort.py` im Blick
> behalten.

---

## Verhaltenskodex

Für dieses Projekt gilt der [Verhaltenskodex](CODE_OF_CONDUCT.md).

## Lizenz und Entstehung

Mit einem Beitrag stimmen Sie zu, dass er unter der [MIT-Lizenz](LICENSE)
veröffentlicht wird.

Copyright © 2026 Alexander Unverhau · **Erstellt mit Unterstützung von
Claude AI (Anthropic)**, siehe [NOTICE](NOTICE). Der Hinweis auf die
KI-Unterstützung steht der Transparenz halber überall dort, wo auch der
Copyright-Vermerk steht. Wer den Kopf von `Bild-Toolbox.pyw`, den Reiter
*Info & Hilfe* oder die `NOTICE` bearbeitet, sollte ihn deshalb bitte stehen
lassen. Die `LICENSE` bleibt bewusst wortgleich beim MIT-Text, damit GitHub die
Lizenz weiterhin automatisch erkennt.
