# Sicherheitsrichtlinie

## Unterstützte Versionen

| Version | Unterstützt |
|---|---|
| 1.0.x   | ✅ |
| < 1.0   | ❌ |

Es wird immer nur die jeweils aktuelle Version gepflegt.

## Eine Sicherheitslücke melden

Bitte melden Sie Sicherheitslücken **nicht** als öffentliches Issue.

Nutzen Sie stattdessen die private Meldefunktion von GitHub:

**[Report a vulnerability](https://github.com/DerAlexmann/bild-toolbox/security/advisories/new)**
(im Repository unter *Security → Advisories*)

Der Bericht ist dabei nur für Sie und die Projektverantwortlichen sichtbar. Die
Behebung kann im selben Advisory besprochen werden, ohne dass die Lücke vorher
öffentlich wird. Einen weiteren Meldeweg gibt es bewusst nicht – so bleibt alles
an einer Stelle und nachvollziehbar.

Hilfreich für die Meldung:

- Beschreibung der Lücke und der möglichen Auswirkung
- Schritte zum Nachstellen, gern mit einer Beispieldatei
- Betriebssystem, Python-Version und installierte Zusatzmodule
- Falls vorhanden: ein Vorschlag zur Behebung

**Was Sie erwarten können:** eine Eingangsbestätigung innerhalb von 7 Tagen und
eine erste Einschätzung innerhalb von 30 Tagen. Nach der Behebung wird die Lücke
öffentlich gemacht; auf Wunsch mit Nennung der meldenden Person.

Dies ist ein Freizeitprojekt ohne Bug-Bounty-Programm.

## Womit das Programm umgeht – Einschätzung des Risikos

Die Bild-Toolbox läuft vollständig lokal. Sie stellt **keine Netzwerkverbindung**
her, sendet keine Telemetrie und lädt nichts nach. Trotzdem lohnt ein Blick auf
die Stellen, an denen fremde Daten verarbeitet werden:

| Bereich | Hinweis |
|---|---|
| **Bilddateien** | Werden über Pillow geöffnet. Sicherheitslücken in Bilddecodern sind ein bekanntes Thema – halten Sie `Pillow` aktuell. |
| **Bildgrößen-Grenze** | Das Programm setzt `Image.MAX_IMAGE_PIXELS = None` und hebt damit Pillows Schutz gegen „Decompression Bombs" auf. Das ist nötig, um sehr große, legitime Bilder zu verarbeiten – bedeutet aber, dass eine bösartig konstruierte Datei viel Arbeitsspeicher belegen kann. Öffnen Sie keine Bilder aus unbekannter Quelle in großen Mengen. |
| **EXE- und DLL-Dateien** | Der Icon-Extraktor liest die Ressourcen dieser Dateien über `icoextract`. Die Dateien werden dabei **nicht ausgeführt**. |
| **HEIC/HEIF** | Werden über `pillow-heif` gelesen. Auch dieses Paket aktuell halten. |
| **AVIF** | Wird ab Pillow 11.3 von Pillow selbst gelesen, davor von `pillow-heif`. |
| **Löschen und Verschieben** | Diese Aktionen sind endgültig, sofern `send2trash` nicht installiert und der Papierkorb-Modus aktiv ist. Es gibt keine eingebaute Rückgängig-Funktion. |
| **Konfigurationsdatei** | `bild-toolbox.json` enthält nur Sprache und Farbschema, keine persönlichen Daten. |
| **Fehlerprotokoll** | `bild-toolbox_fehler.log` kann Dateipfade enthalten. Vor dem Anhängen an ein Issue bitte durchsehen. |

## Abhängigkeiten aktuell halten

```bash
pip install --upgrade -r requirements.txt -r requirements-optional.txt
```

Im Repository hält [Dependabot](.github/dependabot.yml) die Abhängigkeiten und
die Versionen der GitHub-Actions monatlich nach.
