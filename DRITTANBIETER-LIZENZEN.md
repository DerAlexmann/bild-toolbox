# Lizenzen der Fremdkomponenten

Der Quellcode der Bild-Toolbox steht unter der MIT-Lizenz – siehe [LICENSE](LICENSE).
Diese Datei listet die Bestandteile anderer Projekte auf, die in der fertigen
**Windows-EXE** mitgeliefert werden, und sagt, was daraus folgt.

*English version below – [Licenses of third-party components](#licenses-of-third-party-components).*

## Das Wichtigste in vier Sätzen

- **Der Quellcode bleibt MIT.** Daran ändert diese Datei nichts.
- **Das Skript** `Bild-Toolbox.pyw` liefert nichts mit. Pillow und die optionalen Pakete
  installieren Sie selbst; es gilt jeweils deren eigene Lizenz.
- **Die Windows-EXE** enthält zusätzlich Bibliotheken unter LGPLv3 und GPLv2 und wird
  deshalb als Gesamtwerk unter den Bedingungen der **GPLv2** weitergegeben.
- Wer ein Programm ohne GPL-Teile möchte, startet das Skript mit Pillow und **ohne**
  `pillow-heif`: Dann fehlen HEIC und HEIF, alles andere bleibt.

### Warum GPLv2?

HEIC- und HEIF-Dateien liest die Toolbox über `pillow-heif`. Das Paket selbst steht unter
BSD-3-Clause, seine Binärpakete bringen aber `libheif` und `libde265` (LGPLv3) sowie den
Encoder `x265` (GPLv2) mit – das Projekt bezeichnet seine Binärpakete darum selbst als
GPLv2.

Die Toolbox *schreibt* kein HEIC und benutzt den Encoder nie. Weglassen lässt er sich
trotzdem nicht: `libheif.dll` ist fest gegen `libx265` gebunden und lädt ohne diese Datei
überhaupt nicht – HEIC-Lesen fiele mit aus.

## Was in der Windows-EXE steckt

| Bestandteil | Lizenz | Lizenztext und Quellcode |
|---|---|---|
| **Python 3.12** – Laufzeit und Standardbibliothek | PSF License 2.0 | [docs.python.org](https://docs.python.org/3/license.html) |
| **Tcl/Tk 8.6** – die Oberfläche (`tcl86t.dll`, `tk86t.dll`) | Tcl/Tk-Lizenz (BSD-artig) | [tcl-lang.org](https://www.tcl-lang.org/software/tcltk/license.html) |
| **zlib** (`zlib1.dll`) | zlib-Lizenz | [zlib.net](https://zlib.net/zlib_license.html) |
| **Pillow** – Bilder lesen, schreiben, skalieren | MIT-CMU | [LICENSE](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| **Send2Trash** – Löschen in den Papierkorb | BSD 3-Clause | [LICENSE](https://github.com/arsenetar/send2trash/blob/master/LICENSE) |
| **icoextract** – Symbole aus EXE und DLL lesen | MIT | [LICENSE](https://github.com/jlu5/icoextract/blob/master/LICENSE) |
| **pillow-heif** – HEIC und HEIF lesen | BSD-3-Clause; die Binärpakete GPLv2 | [LICENSE.txt](https://github.com/bigcat88/pillow_heif/blob/master/LICENSE.txt), [LICENSES_bundled.txt](https://github.com/bigcat88/pillow_heif/blob/master/LICENSES_bundled.txt) |
| **libheif** – in `pillow-heif` enthalten | **LGPLv3** | [COPYING](https://github.com/strukturag/libheif/blob/master/COPYING) |
| **libde265** – HEVC-Decoder, in `pillow-heif` enthalten | **LGPLv3** | [COPYING](https://github.com/strukturag/libde265/blob/master/COPYING) |
| **x265** – HEVC-Encoder, in `pillow-heif` enthalten | **GPLv2** | [COPYING](https://bitbucket.org/multicoreware/x265_git/src/master/COPYING) |
| **libgcc, libstdc++** – MinGW-Laufzeit, kommt mit `pillow-heif` | GPLv3 **mit** GCC Runtime Library Exception | [Erläuterung](https://gcc.gnu.org/onlinedocs/libstdc++/manual/license.html), [Ausnahme](https://www.gnu.org/licenses/gcc-exception-3.1.html) |
| **libwinpthread** – MinGW-w64-Laufzeit, kommt mit `pillow-heif` | permissiv, siehe COPYING | [mingw-w64](https://sourceforge.net/p/mingw-w64/mingw-w64/ci/master/tree/COPYING) |
| **PyInstaller-Bootloader** – startet die gepackte Anwendung | GPLv2 **mit** Ausnahme für damit erzeugte Programme | [Lizenzhinweis](https://pyinstaller.org/en/stable/license.html) |

Die vollständigen Texte der beiden wichtigsten Lizenzen:
[GPLv2](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html) ·
[LGPLv3](https://www.gnu.org/licenses/lgpl-3.0.html).

### Quellcode der GPL- und LGPL-Teile

GPLv2 und LGPLv3 verlangen, dass der Quellcode der betroffenen Bibliotheken verfügbar
ist. Er liegt öffentlich bei den oben verlinkten Projekten. Welche Fassung ein Release
genau enthält, steht an zwei Stellen:

- in `LICENSES_bundled.txt` innerhalb des Pakets `pillow-heif`
- zur Laufzeit über `pillow_heif.libheif_info()` – der Reiter *Info & Hilfe* zeigt, ob
  HEIC-Unterstützung überhaupt geladen ist

Der Quellcode der Bild-Toolbox selbst liegt zu jeder Version als ZIP am
[Release](../../releases) und im Verlauf dieses Repositorys.

### Weitere Bibliotheken innerhalb von Pillow

Pillow bindet seine Bilddecoder fest in die eigenen Erweiterungsmodule ein
(`_imaging`, `_imagingcms`, `_webp`, `_avif`). Sie erscheinen deshalb nicht als eigene
Dateien, sind aber mit in der EXE: **libjpeg-turbo, libpng, libtiff, libwebp, FreeType,
HarfBuzz, Little CMS, OpenJPEG, libavif, brotli, XZ Utils** und **zlib**. Die
vollständigen Lizenztexte dazu stehen gesammelt in der
[LICENSE-Datei von Pillow](https://github.com/python-pillow/Pillow/blob/main/LICENSE),
die auch in jedem Pillow-Paket mitgeliefert wird.

Ebenso enthält der Windows-Build von Python Bestandteile, die nicht von uns stammen –
unter anderem **OpenSSL**, **libffi**, **bzip2** und **liblzma**. Die
[Lizenzseite von Python](https://docs.python.org/3/license.html) führt sie im Abschnitt
*Licenses and Acknowledgements for Incorporated Software* samt Lizenztexten auf.

### Nicht aufgeführt: Systembibliotheken von Windows

Dateien wie `VCRUNTIME140.dll` oder die `api-ms-win-*`-Bibliotheken gehören zum
Betriebssystem beziehungsweise zu dessen Laufzeitumgebung und werden hier nicht
einzeln aufgeführt.

## Pflege dieser Datei

Kommt eine Abhängigkeit hinzu oder fällt eine weg, gehört das hier hinein. Der Test
`tests/test_verpackung.py` prüft, dass jedes Paket aus `requirements.txt` und
`requirements-optional.txt` in dieser Datei vorkommt und dass sie im Release mitgeliefert
wird – er schlägt fehl, wenn das vergessen wird.

---

# Licenses of third-party components

The Bild-Toolbox source code is licensed under the MIT License – see
[LICENSE](LICENSE). This file lists the components from other projects that ship inside
the finished **Windows executable**, and what follows from that.

## The short version

- **The source code stays MIT.** This file changes nothing about that.
- **The script** `Bild-Toolbox.pyw` bundles nothing. You install Pillow and the optional
  packages yourself, and their own licenses apply.
- **The Windows executable** additionally contains libraries under LGPLv3 and GPLv2 and
  is therefore distributed as a whole under the terms of the **GPLv2**.
- If you want a program without any GPL parts, run the script with Pillow and **without**
  `pillow-heif`: HEIC and HEIF are then unavailable, everything else stays.

### Why GPLv2?

The toolbox reads HEIC and HEIF files through `pillow-heif`. That package itself is
BSD-3-Clause, but its binary wheels bundle `libheif` and `libde265` (LGPLv3) as well as
the `x265` encoder (GPLv2) – which is why the project labels its own binary wheels GPLv2.

The toolbox never *writes* HEIC and never uses the encoder. Leaving it out is not
possible all the same: `libheif.dll` is linked against `libx265` and does not load at all
without that file, which would take HEIC reading down with it.

## What is inside the Windows executable

| Component | License | License text and source |
|---|---|---|
| **Python 3.12** – runtime and standard library | PSF License 2.0 | [docs.python.org](https://docs.python.org/3/license.html) |
| **Tcl/Tk 8.6** – the user interface (`tcl86t.dll`, `tk86t.dll`) | Tcl/Tk license (BSD-style) | [tcl-lang.org](https://www.tcl-lang.org/software/tcltk/license.html) |
| **zlib** (`zlib1.dll`) | zlib license | [zlib.net](https://zlib.net/zlib_license.html) |
| **Pillow** – reading, writing and scaling images | MIT-CMU | [LICENSE](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| **Send2Trash** – deleting to the recycle bin | BSD 3-Clause | [LICENSE](https://github.com/arsenetar/send2trash/blob/master/LICENSE) |
| **icoextract** – reading icons from EXE and DLL files | MIT | [LICENSE](https://github.com/jlu5/icoextract/blob/master/LICENSE) |
| **pillow-heif** – reading HEIC and HEIF | BSD-3-Clause; binary wheels GPLv2 | [LICENSE.txt](https://github.com/bigcat88/pillow_heif/blob/master/LICENSE.txt), [LICENSES_bundled.txt](https://github.com/bigcat88/pillow_heif/blob/master/LICENSES_bundled.txt) |
| **libheif** – bundled in `pillow-heif` | **LGPLv3** | [COPYING](https://github.com/strukturag/libheif/blob/master/COPYING) |
| **libde265** – HEVC decoder, bundled in `pillow-heif` | **LGPLv3** | [COPYING](https://github.com/strukturag/libde265/blob/master/COPYING) |
| **x265** – HEVC encoder, bundled in `pillow-heif` | **GPLv2** | [COPYING](https://bitbucket.org/multicoreware/x265_git/src/master/COPYING) |
| **libgcc, libstdc++** – MinGW runtime, ships with `pillow-heif` | GPLv3 **with** the GCC Runtime Library Exception | [explanation](https://gcc.gnu.org/onlinedocs/libstdc++/manual/license.html), [exception](https://www.gnu.org/licenses/gcc-exception-3.1.html) |
| **libwinpthread** – MinGW-w64 runtime, ships with `pillow-heif` | permissive, see COPYING | [mingw-w64](https://sourceforge.net/p/mingw-w64/mingw-w64/ci/master/tree/COPYING) |
| **PyInstaller bootloader** – starts the packaged application | GPLv2 **with** an exception for the programs it builds | [license notice](https://pyinstaller.org/en/stable/license.html) |

Full texts of the two licenses that matter most:
[GPLv2](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html) ·
[LGPLv3](https://www.gnu.org/licenses/lgpl-3.0.html).

### Source code of the GPL and LGPL parts

GPLv2 and LGPLv3 require the source code of the affected libraries to be available. It is
public at the projects linked above. The exact version a release contains is recorded in
two places:

- in `LICENSES_bundled.txt` inside the `pillow-heif` package
- at runtime via `pillow_heif.libheif_info()` – the *Info & help* tab shows whether HEIC
  support was loaded at all

The source code of Bild-Toolbox itself is attached to every [release](../../releases) as a
ZIP file and is part of this repository's history.

### Further libraries inside Pillow

Pillow links its image decoders into its own extension modules (`_imaging`,
`_imagingcms`, `_webp`, `_avif`). They therefore do not appear as separate files, but they
are in the executable: **libjpeg-turbo, libpng, libtiff, libwebp, FreeType, HarfBuzz,
Little CMS, OpenJPEG, libavif, brotli, XZ Utils** and **zlib**. Their full license texts
are collected in [Pillow's LICENSE file](https://github.com/python-pillow/Pillow/blob/main/LICENSE),
which ships inside every Pillow package.

The Windows build of Python likewise contains components that are not ours – among them
**OpenSSL**, **libffi**, **bzip2** and **liblzma**. Python's
[license page](https://docs.python.org/3/license.html) lists them with their license texts
in the section *Licenses and Acknowledgements for Incorporated Software*.

### Not listed: Windows system libraries

Files such as `VCRUNTIME140.dll` or the `api-ms-win-*` libraries belong to the operating
system and its runtime environment and are not listed individually here.

## Keeping this file current

When a dependency is added or dropped, it belongs in here. The test
`tests/test_verpackung.py` checks that every package from `requirements.txt` and
`requirements-optional.txt` appears in this file and that the file ships with the
release – it fails if that is forgotten.
