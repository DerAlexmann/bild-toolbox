"""
Bild-Toolbox 1.0 - Alle Bildwerkzeuge in einer Anwendung

Vereint die Einzelprogramme:
  * Bildbetrachter Pro 2.0  -> Vergleich, Duplikat-Finder, Ähnliche Bilder,
                               Batch-Umbenennung, Statistiken
  * Icon Extraktor          -> Icon-Extraktor
  * Universal Image Converter -> Format-Konverter
  * Bild-Dimensions-Filter  -> Dimensions-Filter

Licensed under MIT License
Copyright 2026 Alexander Unverhau
Created with assistance of Claude AI

Benötigt:  pip install Pillow
Optional :  pip install send2trash icoextract pillow-heif
"""

import atexit
import hashlib
import json
import locale
import logging
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from collections import defaultdict
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

# --------------------------------------------------------------------------
# Abhängigkeiten
# --------------------------------------------------------------------------

try:
    from PIL import Image, ImageTk, UnidentifiedImageError
    HAS_PIL = True
except ImportError:                                     # ohne Pillow geht nichts
    HAS_PIL = False
    Image = ImageTk = None
    UnidentifiedImageError = Exception


# pillow-heif wird mit einer gewoehnlichen import-Zeile geladen und nicht ueber
# __import__("pillow_heif"). Das ist wichtig: PyInstaller wertet beim Packen nur
# die sichtbaren import-Zeilen aus. Ein dynamischer Import landet nicht mit im
# Paket, und die fertige EXE meldete dann faelschlich, HEIC/HEIF werde nicht
# unterstuetzt - obwohl dasselbe Skript direkt ausgefuehrt problemlos damit
# umgehen konnte. Diese Zeile bitte so stehen lassen.
try:
    import pillow_heif
except ImportError:
    pillow_heif = None


def _register(func_name):
    """Ein Bildformat-Plugin von pillow-heif bei Pillow anmelden, falls vorhanden."""
    try:
        getattr(pillow_heif, func_name)()
        return True
    except Exception:
        return False


HAS_HEIF = False
if HAS_PIL:
    HAS_HEIF = _register("register_heif_opener")
    # AVIF bringt Pillow ab Version 11.3 selbst mit; aeltere Pillow-Versionen
    # bekamen es von pillow-heif, das die Funktion seit Version 1.0 nicht mehr
    # hat. Der Versuch schadet nicht - schlaegt er fehl, ist AVIF entweder schon
    # da oder gar nicht verfuegbar.
    _register("register_avif_opener")
    Image.MAX_IMAGE_PIXELS = None          # grosse Bilder nicht als "Bombe" ablehnen

try:
    from send2trash import send2trash
    HAS_TRASH = True
except Exception:
    HAS_TRASH = False

try:
    from icoextract import IconExtractor, IconExtractorError
    HAS_ICOEXTRACT = True
except ImportError:
    HAS_ICOEXTRACT = False

    class IconExtractorError(Exception):
        pass


# --------------------------------------------------------------------------
# Ablageort fuer Einstellungen und Fehlerprotokoll
# --------------------------------------------------------------------------

_APP_FOLDER = None


def _writable(folder):
    """Prueft, ob sich in dem Ordner tatsaechlich eine Datei anlegen laesst."""
    probe = os.path.join(folder, ".bild-toolbox-schreibtest")
    try:
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def app_folder():
    """Ordner fuer Einstellungen und Fehlerprotokoll.

    Normalerweise der Ordner des Programms. Ist das Programm mit PyInstaller
    gepackt, liegt __file__ in einem temporaeren Entpackordner, den das System
    beim Beenden wieder wegraeumt - dort waeren Sprache und Farbschema nach
    jedem Start verloren. Im gepackten Zustand zaehlt deshalb der Ordner der
    EXE. Laesst sich dort nicht schreiben (Programme-Verzeichnis, gesperrter
    USB-Stick), weicht die Ablage auf das Benutzerverzeichnis aus.

    Das Ergebnis wird gemerkt, damit der Schreibtest nur einmal pro
    Programmlauf stattfindet.
    """
    global _APP_FOLDER
    if _APP_FOLDER is not None:
        return _APP_FOLDER

    if getattr(sys, "frozen", False):           # von PyInstaller gepackt
        folder = os.path.dirname(os.path.abspath(sys.executable))
    else:
        try:
            folder = os.path.dirname(os.path.abspath(__file__))
        except NameError:                       # z. B. interaktiv ausgefuehrt
            folder = os.path.expanduser("~")

    if not _writable(folder):
        folder = os.path.expanduser("~")
    _APP_FOLDER = folder
    return _APP_FOLDER


# --------------------------------------------------------------------------
# Logging - schreibt erst bei einem echten Fehler eine Datei
# --------------------------------------------------------------------------

class ErrorOnlyHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.file_handler = None

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            if self.file_handler is None:
                path = os.path.join(app_folder(), LOG_NAME)
                self.file_handler = logging.FileHandler(path, encoding="utf-8")
                self.file_handler.setFormatter(logging.Formatter(
                    "%(asctime)s - %(levelname)s - %(message)s"))
            self.file_handler.emit(record)

    def close(self):
        if self.file_handler is not None:
            self.file_handler.close()
        super().close()


logger = logging.getLogger()
logger.setLevel(logging.ERROR)      # nur echte Fehler - kein Debug-Rauschen fremder Module
_error_handler = ErrorOnlyHandler()
logger.addHandler(_error_handler)
atexit.register(logging.shutdown)


# --------------------------------------------------------------------------
# Konstanten / Design
# --------------------------------------------------------------------------

APP_NAME = "Bild-Toolbox"
APP_VERSION = "1.0.5"

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".avif",
                    ".tif", ".tiff", ".ico", ".jfif", ".heic", ".heif", ".ppm")
EXE_EXTENSIONS = (".exe", ".dll", ".sys", ".mun", ".ocx", ".cpl", ".scr")
ICO_MAX = 256
MAX_THUMBS = 300          # so viele Vorschaubilder maximal in einer Trefferliste

# --------------------------------------------------------------------------
# Farbschemata (hell / dunkel)
#
# Beide Paletten enthalten dieselben Namen. apply_theme() schreibt die Werte
# der gewaehlten Palette in die Modulvariablen - der uebrige Code benutzt
# einfach BG, CARD, TEXT ... und muss vom Umschalten nichts wissen. Ein
# eigenes Schema entsteht durch eine weitere Palette mit denselben Namen.
# --------------------------------------------------------------------------

THEMES = {
    "light": {
        "BG": "#eef1f5",             # Seitenhintergrund
        "CARD": "#ffffff",           # Karten
        "CARD_ALT": "#fbfcfe",       # Text- und Listenflaechen in Karten
        "BORDER": "#d7dce4",
        "TEXT": "#1b2430",
        "MUTED": "#6c7684",          # Nebentext
        "SIDEBAR": "#1d2330",
        "SIDEBAR_HOVER": "#2b3346",
        "SIDEBAR_TEXT": "#c2cad8",
        "SIDEBAR_GROUP": "#69748c",  # Gruppenueberschriften der Navigation
        "SIDEBAR_TITLE": "#ffffff",
        "ACCENT": "#2f7de1",
        "ACCENT_DARK": "#1f66c4",
        "ON_ACCENT": "#ffffff",      # Schrift auf farbigen Flaechen
        "OK": "#2e9e5b",
        "OK_DARK": "#25864b",
        "WARN": "#e08b1f",
        "WARN_DARK": "#c4770f",
        "DANGER": "#d64545",
        "DANGER_DARK": "#b83a3a",
        "BTN_BG": "#e3e8f0",         # unauffaelliger Schalter
        "BTN_HOVER": "#d2d9e6",
        "BTN_TEXT": "#1b2430",
        "BTN_DISABLED": "#9aa3b0",
        "FIELD_BG": "#ffffff",       # Eingabefelder
        "TROUGH": "#e3e8f0",         # Rille von Fortschritt und Schieber
        "HEAD_BG": "#eef1f5",        # Spaltenkoepfe der Trefferlisten
        "TILE_HOVER": "#f4f8fe",     # Kachel auf der Startseite
        "STATUS_BG": "#e4e8ef",
        "VIEWER_BG": "#2b3038",      # Bildflaeche im Vergleich
        "VIEWER_TEXT": "#8b95a5",
    },
    "dark": {
        "BG": "#12161d",
        "CARD": "#1a1f28",
        "CARD_ALT": "#151a22",
        "BORDER": "#2c3441",
        "TEXT": "#e6eaf0",
        "MUTED": "#98a2b3",
        "SIDEBAR": "#0e1218",
        "SIDEBAR_HOVER": "#212a38",
        "SIDEBAR_TEXT": "#b8c2d0",
        "SIDEBAR_GROUP": "#6b7688",
        "SIDEBAR_TITLE": "#ffffff",
        "ACCENT": "#4a90e8",
        "ACCENT_DARK": "#3a7ad0",
        "ON_ACCENT": "#ffffff",
        "OK": "#3fb972",
        "OK_DARK": "#349b60",
        "WARN": "#e9a23b",
        "WARN_DARK": "#cc8a26",
        "DANGER": "#e05a5a",
        "DANGER_DARK": "#c44a4a",
        "BTN_BG": "#2a323f",
        "BTN_HOVER": "#353f4f",
        "BTN_TEXT": "#e6eaf0",
        "BTN_DISABLED": "#626c7a",
        "FIELD_BG": "#232b36",
        "TROUGH": "#2a323f",
        "HEAD_BG": "#232b36",
        "TILE_HOVER": "#222c3a",
        "STATUS_BG": "#0e1218",
        "VIEWER_BG": "#0d1014",
        "VIEWER_TEXT": "#7d8794",
    },
}

DEFAULT_THEME = "light"
CURRENT_THEME = DEFAULT_THEME


class Color(str):
    """Farbwert aus der Palette, der seine Rolle kennt ("CARD", "TEXT" ...).

    Verhaelt sich ueberall wie der Farbwert selbst. Die Widgets der
    Bild-Toolbox (siehe Themed) merken sich beim Einfaerben die Rolle und
    faerben sich nach einem Wechsel des Farbschemas mit der neuen Palette nach.
    Vom Farbwert allein liesse sich nicht auf die Rolle schliessen: "#ffffff"
    ist im hellen Schema zugleich CARD und ON_ACCENT, im dunklen nicht.
    """

    def __new__(cls, value, role):
        new = super().__new__(cls, value)
        new.role = role
        return new


def apply_theme(name):
    """Farbwerte des gewaehlten Schemas in die Modulvariablen schreiben."""
    global CURRENT_THEME
    CURRENT_THEME = name if name in THEMES else DEFAULT_THEME
    globals().update({role: Color(value, role)
                      for role, value in THEMES[CURRENT_THEME].items()})


apply_theme(DEFAULT_THEME)      # legt BG, CARD, TEXT ... ueberhaupt erst an

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_TINY = ("Segoe UI", 8)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_H1 = ("Segoe UI", 18, "bold")
FONT_H2 = ("Segoe UI", 12, "bold")
FONT_MONO = ("Consolas", 10)


# --------------------------------------------------------------------------
# Sprachumschaltung
#
# Quellsprache ist Deutsch: im Code steht der deutsche Text, _("...") sucht
# ihn zur Laufzeit in der Sprachtabelle TRANSLATIONS (ganz unten in dieser
# Datei). Dort ist auch beschrieben, wie eine weitere Sprache dazukommt.
# --------------------------------------------------------------------------

SOURCE_LANGUAGE = "de"
CONFIG_NAME = "bild-toolbox.json"
LOG_NAME = "bild-toolbox_fehler.log"


class Translated(str):
    """Uebersetzter Text, der weiss, wie er entstanden ist.

    Verhaelt sich ueberall wie ein gewoehnlicher String. Zusaetzlich kennt er
    seinen deutschen Schluessel und die Werte, die mit format() eingesetzt
    wurden, und kann sich deshalb nach einem Sprachwechsel neu bilden (siehe
    again() und set_text). Das gilt auch fuer Verkettungen: "   " + _("Start")
    ergibt wieder einen Translated.
    """

    def __new__(cls, text, key=None, values=None, parts=None):
        new = super().__new__(cls, text)
        new.key = key
        new.values = values or {}
        new.parts = parts                    # (links, rechts) einer Verkettung
        return new

    def format(self, *args, **kwargs):
        if args or self.parts is not None:   # Positionsargumente nutzt hier niemand
            return str.format(self, *args, **kwargs)
        return Translated(str.format(self, **kwargs), self.key, kwargs)

    def __add__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return Translated(str.__add__(self, other), parts=(self, other))

    def __radd__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return Translated(str.__add__(other, self), parts=(other, self))

    def again(self):
        """Derselbe Text in der jetzt eingestellten Sprache."""
        if self.parts is not None:
            left, right = (part.again() if isinstance(part, Translated) else part
                           for part in self.parts)
            return Translated(str.__add__(left, right), parts=(left, right))
        text = _(self.key)
        if not self.values:
            return text
        # Eingesetzte Werte koennen selbst uebersetzt sein ("{action}" = "geloescht")
        return text.format(**{name: value.again() if isinstance(value, Translated) else value
                              for name, value in self.values.items()})


class Translator:
    """Uebersetzt einen deutschen Quelltext in die eingestellte Sprache."""

    def __init__(self, language=SOURCE_LANGUAGE):
        self.language = language

    def __call__(self, text):
        if self.language == SOURCE_LANGUAGE:
            return Translated(text, text)
        return Translated(TRANSLATIONS.get(self.language, {}).get(text, text), text)

    def available(self):
        """Sprachkuerzel -> Anzeigename, Quellsprache immer zuerst."""
        names = {SOURCE_LANGUAGE: LANGUAGE_NAMES[SOURCE_LANGUAGE]}
        for code in TRANSLATIONS:
            names[code] = LANGUAGE_NAMES.get(code, code)
        return names


_ = Translator()


# --------------------------------------------------------------------------
# Beschriftungen, die einen Sprachwechsel ueberstehen
#
# set_text() merkt sich zu jedem Widget, woraus sein Text entstanden ist.
# refresh_texts() bildet nach einem Sprachwechsel alle Texte in der neuen
# Sprache neu - die Widgets samt ihren Inhalten und Eingaben bleiben stehen,
# statt abgerissen und neu gebaut zu werden.
#
# Wer den Text eines Widgets spaeter aendert, tut das ebenfalls ueber
# set_text(). Sonst holte der naechste Sprachwechsel den alten Text zurueck.
# --------------------------------------------------------------------------

# Ort -> (Setzfunktion, Text). Ort ist meist (Widget, Option).
_TEXTS = {}


def remember_text(place, setter, text):
    """setter(text) ausfuehren und den Text fuer den Sprachwechsel merken.

    text ist ein Translated aus _() oder eine Funktion ohne Argumente, die den
    Text liefert - fuer Zusammengesetztes wie den Statistikbericht. Ein
    gewoehnlicher String vergisst, was an diesem Ort gemerkt war.
    """
    value = text() if callable(text) else text
    setter(value)
    if callable(text) or isinstance(value, Translated):
        _TEXTS[place] = (setter, text)
    else:
        _TEXTS.pop(place, None)


def forget_text(place):
    """Gemerkten Text vergessen - der Ort wird nicht mehr nachuebersetzt."""
    _TEXTS.pop(place, None)


def set_text(widget, text, option="text", **options):
    """Widget beschriften und den Text fuer den Sprachwechsel merken.

    Weitere Optionen werden nur jetzt gesetzt, nicht bei jedem Sprachwechsel:
        set_text(self.summary, _("Keine Treffer."), fg=MUTED)
    Liefert das Widget, damit sich .pack() direkt anhaengen laesst.
    """
    if options:
        widget.configure(**options)
    remember_text((widget, option), lambda value: widget.configure(**{option: value}), text)
    return widget


def text_of(widget, option="text"):
    """Aktueller Text eines Widgets - als Translated, wenn er gemerkt ist."""
    remembered = _TEXTS.get((widget, option))
    if remembered and isinstance(remembered[1], Translated):
        return remembered[1]
    return widget.cget(option)


def set_heading(tree, column, text):
    """Spaltenkopf einer Treeview beschriften und fuer den Sprachwechsel merken."""
    remember_text((tree, "heading", column),
                  lambda value: tree.heading(column, text=value), text)


def set_item_text(tree, item, text):
    """Eintrag einer Treeview beschriften und fuer den Sprachwechsel merken."""
    remember_text((tree, "item", item), lambda value: tree.item(item, text=value), text)


def refresh_texts():
    """Alle gemerkten Texte in die eingestellte Sprache bringen.

    Zerstoerte Widgets melden sich mit einem TclError und fallen dabei aus
    dem Verzeichnis heraus.
    """
    for place, (setter, text) in list(_TEXTS.items()):
        value = text() if callable(text) else text.again()
        try:
            setter(value)
        except tk.TclError:
            del _TEXTS[place]
            continue
        if not callable(text):
            _TEXTS[place] = (setter, value)


def config_path():
    """Ablageort der Einstellungen - siehe app_folder()."""
    return os.path.join(app_folder(), CONFIG_NAME)


def load_config():
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(data):
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except OSError as e:
        logging.error(f"Einstellungen nicht speicherbar: {e}")
        return False


def detect_language():
    """Sprache des Betriebssystems, falls dafuer eine Tabelle vorliegt."""
    try:
        locale.setlocale(locale.LC_CTYPE, "")
        code = (locale.getlocale()[0] or "").lower()
    except Exception:
        code = ""
    known = {SOURCE_LANGUAGE, *TRANSLATIONS}
    short = code.split("_")[0]
    if short in known:
        return short
    for name, lang in (("german", "de"), ("deutsch", "de"), ("english", "en")):
        if short.startswith(name) and lang in known:
            return lang
    return SOURCE_LANGUAGE


def startup_language():
    """Gespeicherte Sprache, sonst die des Betriebssystems."""
    stored = load_config().get("language")
    if stored and (stored == SOURCE_LANGUAGE or stored in TRANSLATIONS):
        return stored
    return detect_language()


def startup_theme():
    """Gespeichertes Farbschema, sonst das helle."""
    stored = load_config().get("theme")
    return stored if stored in THEMES else DEFAULT_THEME


# --------------------------------------------------------------------------
# Fenstergroesse und -lage
# --------------------------------------------------------------------------

# Titelleiste und Rahmen, die das Betriebssystem um den Inhalt legt - grob
# geschaetzt. Tk zaehlt sie bei der Fenstergroesse nicht mit, bei der Lage
# aber schon.
WINDOW_FRAME = (16, 40)

_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")


def parse_geometry(text):
    """Tk-Geometrie wie '1200x700+100+50' in ein Woerterbuch zerlegen."""
    match = _GEOMETRY_RE.match(text or "")
    if not match:
        return None
    width, height, x, y = (int(value) for value in match.groups())
    return {"x": x, "y": y, "width": width, "height": height}


def window_from_config(settings):
    """Gespeicherte Fensterlage pruefen - None, wenn nichts Brauchbares da ist."""
    window = settings.get("window") if isinstance(settings, dict) else None
    if not isinstance(window, dict):
        return None
    try:
        values = {key: int(window[key]) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    if values["width"] <= 0 or values["height"] <= 0:
        return None
    values["maximized"] = window.get("maximized") is True
    return values


def window_placement(natural, area, saved=None, on_screen=None):
    """Groesse, Lage und Mindestgroesse des Hauptfensters beim Start.

    natural   -- Platzbedarf der Oberflaeche als (Breite, Hoehe)
    area      -- nutzbare Flaeche des Hauptbildschirms als (x, y, Breite, Hoehe)
    saved     -- gespeicherte Lage aus window_from_config() oder None
    on_screen -- prueft, ob ein Punkt (x, y) auf einem angeschlossenen
                 Bildschirm liegt; None heisst: nicht pruefen

    Ohne gespeicherte Lage startet das Fenster in der kleinsten Groesse, die
    alles zeigt, mittig auf dem Hauptbildschirm. Eine gespeicherte Lage wird
    uebernommen, solange die Titelleiste auf einem Bildschirm liegt - sonst,
    etwa nach dem Abstecken eines zweiten Monitors, wird das Fenster wieder
    zentriert. Kleiner als der Platzbedarf wird es nie, und groesser als der
    Bildschirm nur, wenn der Nutzer es selbst so aufgezogen hat.

    Liefert (breite, hoehe, x, y, min_breite, min_hoehe).
    """
    area_x, area_y, area_w, area_h = area
    frame_w, frame_h = WINDOW_FRAME
    max_w, max_h = max(area_w - frame_w, 1), max(area_h - frame_h, 1)
    min_w, min_h = min(natural[0], max_w), min(natural[1], max_h)

    if saved:
        width, height = max(saved["width"], min_w), max(saved["height"], min_h)
        # Probepunkt mitten in der Titelleiste - dort greift man das Fenster
        if on_screen is None or on_screen(saved["x"] + width // 2, saved["y"] + 10):
            return width, height, saved["x"], saved["y"], min_w, min_h
    else:
        width, height = natural
    width, height = min(width, max_w), min(height, max_h)
    x = area_x + (area_w - width - frame_w) // 2
    y = area_y + (area_h - height - frame_h) // 2
    return width, height, x, y, min_w, min_h


def work_area(root):
    """Nutzbare Flaeche des Hauptbildschirms ohne Taskleiste: (x, y, Breite, Hoehe)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            spi_getworkarea = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(
                    spi_getworkarea, 0, ctypes.byref(rect), 0):
                return (rect.left, rect.top,
                        rect.right - rect.left, rect.bottom - rect.top)
        except Exception:
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def point_on_screen(root, x, y):
    """Liegt der Punkt auf einem der angeschlossenen Bildschirme?"""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.restype = wintypes.HMONITOR
            monitor_defaulttonull = 0
            return bool(user32.MonitorFromPoint(wintypes.POINT(x, y),
                                                monitor_defaulttonull))
        except Exception:
            pass
    return 0 <= x < root.winfo_screenwidth() and 0 <= y < root.winfo_screenheight()


def pause_drawing(window_id):
    """Haelt das Zeichnen eines Fensters samt Inhalt an; liefert die Fortsetzung.

    Tk zeichnet jedes Element einzeln auf den Bildschirm. Aendern sich beim
    Umschalten Texte, Farben und Layout, saehe man sonst jeden Zwischenstand.
    Mit WM_SETREDRAW laesst Windows das alte Bild stehen, bis alles fertig
    ist; danach wird in einem Zug neu gezeichnet.

    window_id ist root.winfo_id() - das Tk-Kindfenster, nicht das aeussere
    Fenster. Die Fortsetzung muss auch im Fehlerfall laufen, sonst bliebe das
    Fenster eingefroren; der Aufruf gehoert deshalb in ein try/finally.
    """
    if sys.platform != "win32":
        return lambda: None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SendMessageW(window_id, 0x000B, 0, 0)       # WM_SETREDRAW aus
    except (AttributeError, OSError):
        return lambda: None

    def resume():
        user32.SendMessageW(window_id, 0x000B, 1, 0)       # WM_SETREDRAW an
        # RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_UPDATENOW
        user32.RedrawWindow(window_id, None, None, 0x0001 | 0x0080 | 0x0100)
    return resume


# --------------------------------------------------------------------------
# Allgemeine Helfer
# --------------------------------------------------------------------------

def human_size(num):
    """Bytes als lesbare Größe."""
    num = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def unique_path(dest):
    """Hängt _1, _2, ... an, falls die Zieldatei schon existiert."""
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(dest)
    i = 1
    while os.path.exists(f"{base}_{i}{ext}"):
        i += 1
    return f"{base}_{i}{ext}"


def open_path(path):
    """Datei mit dem Standardprogramm öffnen."""
    system = platform.system()
    if system == "Windows":
        os.startfile(path)                                    # noqa: S606
    elif system == "Darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


def show_in_explorer(path):
    """Datei im Datei-Manager markieren."""
    system = platform.system()
    if system == "Windows":
        subprocess.run(["explorer", "/select,", os.path.normpath(path)], check=False)
    elif system == "Darwin":
        subprocess.run(["open", "-R", path], check=False)
    else:
        subprocess.run(["xdg-open", os.path.dirname(path)], check=False)


def remove_file(path, to_trash=False):
    """Datei löschen - wahlweise in den Papierkorb."""
    if to_trash and HAS_TRASH:
        send2trash(os.path.abspath(path))
    else:
        os.remove(path)


def md5_of(path, chunk=1024 * 1024):
    """MD5 einer Datei, blockweise gelesen."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def image_size(path):
    """(Breite, Höhe) eines Bildes oder (0, 0)."""
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def image_info(path):
    """Basisdaten eines Bildes für Anzeige und Statistik."""
    try:
        with Image.open(path) as im:
            width, height = im.size
            fmt = im.format or _("Unbekannt")
        size_bytes = os.path.getsize(path)
        return {"resolution": f"{width}x{height}", "width": width, "height": height,
                "pixels": width * height, "bytes": size_bytes,
                "size": human_size(size_bytes), "format": fmt}
    except Exception as e:
        logging.error(f"Fehler beim Lesen von {path}: {e}")
        return None


def average_hash(path, size=8):
    """Perceptual Hash (average hash) als Integer - ohne Fremdbibliothek."""
    try:
        with Image.open(path) as im:
            small = im.convert("L").resize((size, size), Image.Resampling.LANCZOS)
            pixels = list(small.getdata())
    except Exception:
        return None
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p > avg else 0)
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def iter_images(folder, recursive=True, extensions=IMAGE_EXTENSIONS):
    """Alle Bilddateien eines Ordners liefern."""
    if recursive:
        walker = os.walk(folder)
    else:
        try:
            walker = [(folder, [], os.listdir(folder))]
        except OSError:
            walker = []
    for dirpath, _dirs, files in walker:
        for fn in files:
            if extensions is None or fn.lower().endswith(extensions):
                path = os.path.join(dirpath, fn)
                if os.path.isfile(path):
                    yield path


def iter_frames(img):
    """Alle Frames (Größen) eines Bildes als Kopien liefern."""
    frames = getattr(img, "n_frames", 1)
    for i in range(frames):
        try:
            img.seek(i)
        except (EOFError, ValueError):
            break
        yield img.copy()


# --------------------------------------------------------------------------
# Wiederverwendbare Widgets
# --------------------------------------------------------------------------

class Themed:
    """Tk-Widget, das sich merkt, welche Farbrolle in welcher Option steckt.

    Wird es mit bg=CARD gebaut oder spaeter mit fg=OK umgefaerbt, merkt es
    sich {"bg": "CARD"} bzw. {"fg": "OK"}; repaint() setzt dann die Farben des
    eingestellten Schemas. Ein Farbwert, der nicht aus der Palette stammt,
    loescht die Rolle der Option wieder und bleibt beim Wechsel stehen.

    Alle Tk-Widgets der Bild-Toolbox stammen deshalb von den Klassen unten ab
    (Frame, Label ...) statt direkt von tkinter. ttk-Widgets folgen dem Stil
    aus ToolboxApp._setup_style().
    """

    def __init__(self, master=None, cnf=None, **kw):
        self._roles = {}
        super().__init__(master, cnf or {}, **kw)
        self._remember_roles({**(cnf or {}), **kw})

    def configure(self, cnf=None, **kw):
        result = super().configure(cnf, **kw)
        self._remember_roles({**cnf, **kw} if isinstance(cnf, dict) else kw)
        return result

    config = configure

    def _remember_roles(self, options):
        for option, value in options.items():
            if isinstance(value, Color):
                self._roles[option] = value.role
            else:
                self._roles.pop(option, None)

    def repaint(self):
        """Mit der Palette des eingestellten Schemas nachfaerben."""
        if self._roles:
            palette = THEMES[CURRENT_THEME]
            super().configure({option: palette[role] for option, role in self._roles.items()})


class Frame(Themed, tk.Frame):
    pass


class Label(Themed, tk.Label):
    pass


class Button(Themed, tk.Button):
    pass


class Checkbutton(Themed, tk.Checkbutton):
    pass


class Radiobutton(Themed, tk.Radiobutton):
    pass


class Text(Themed, tk.Text):
    pass


class Listbox(Themed, tk.Listbox):
    pass


class Canvas(Themed, tk.Canvas):
    pass


def color_of(widget, option):
    """Aktuelle Farbe einer Option - als Color, wenn sie aus der Palette stammt."""
    role = getattr(widget, "_roles", {}).get(option)
    return globals()[role] if role else widget.cget(option)


def listbox_colors():
    """Farben der Klapplisten in Auswahlfeldern (Namen der Optionsdatenbank)."""
    return {"background": FIELD_BG, "foreground": TEXT,
            "selectBackground": ACCENT, "selectForeground": ON_ACCENT}


def refresh_colors(root):
    """Alle Widgets unter root mit der Palette des eingestellten Schemas nachfaerben.

    Die Klappliste eines Auswahlfelds legt Tk selbst an, beim ersten
    Aufklappen und mit den Farben aus der Optionsdatenbank. tkinter kennt sie
    nicht als Kind; eine schon angelegte wird deshalb hier gesondert
    nachgefaerbt ($combobox.popdown.f.l ist ihr Pfad in ttk).
    """
    pending = [root]
    while pending:
        widget = pending.pop()
        if isinstance(widget, Themed):
            widget.repaint()
        elif widget.winfo_class() == "TCombobox":
            listbox = f"{widget}.popdown.f.l"
            if int(widget.tk.call("winfo", "exists", listbox)):
                options = []
                for option, color in listbox_colors().items():
                    options += [f"-{option.lower()}", color]
                widget.tk.call(listbox, "configure", *options)
        pending.extend(widget.winfo_children())


class FlatButton(Button):
    """Flacher Button mit Hover-Effekt in vier Farbvarianten."""

    @staticmethod
    def styles():
        """Farbvarianten - erst beim Aufruf gelesen, damit das Schema stimmt."""
        return {
            "primary":   (ACCENT, ACCENT_DARK, ON_ACCENT),
            "secondary": (BTN_BG, BTN_HOVER, BTN_TEXT),
            "success":   (OK, OK_DARK, ON_ACCENT),
            "warn":      (WARN, WARN_DARK, ON_ACCENT),
            "danger":    (DANGER, DANGER_DARK, ON_ACCENT),
        }

    def __init__(self, parent, text, command=None, kind="secondary", **kw):
        styles = self.styles()
        bg, hover, fg = styles.get(kind, styles["secondary"])
        kw.setdefault("padx", 14)
        kw.setdefault("pady", 6)
        super().__init__(parent, command=command, bg=bg, fg=fg,
                         activebackground=hover, activeforeground=fg,
                         disabledforeground=BTN_DISABLED, relief="flat", bd=0,
                         highlightthickness=0, cursor="hand2", font=FONT_SMALL, **kw)
        set_text(self, text)
        self.kind = kind if kind in styles else "secondary"
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _enabled(self):
        return str(self["state"]) != "disabled"

    # Die Farben erst beim Ereignis nachschlagen - gemerkte Werte stimmten
    # nach einem Wechsel des Farbschemas nicht mehr
    def _on_enter(self, _e):
        if self._enabled():
            self.configure(bg=self.styles()[self.kind][1])

    def _on_leave(self, _e):
        self.configure(bg=self.styles()[self.kind][0])


def make_card(parent, **pack_kw):
    """Weisse Karte mit dünnem Rahmen."""
    card = Frame(parent, bg=CARD, highlightbackground=BORDER,
                 highlightcolor=BORDER, highlightthickness=1)
    if pack_kw:
        card.pack(**pack_kw)
    return card


def card_title(parent, text):
    set_text(Label(parent, font=FONT_BOLD, bg=CARD, fg=TEXT, anchor="w"),
             text).pack(fill="x", padx=14, pady=(12, 6))


class ScrollArea(Frame):
    """Senkrecht rollbarer Bereich fuer Seiten, die hoeher werden koennen als das Fenster.

    Inhalte kommen in ``inner``. Solange alles passt, fuellt ``inner`` die
    ganze Flaeche aus - Karten mit expand=True wachsen also wie gewohnt mit -
    und der Rollbalken bleibt unsichtbar. Erst wenn der Platz nicht reicht,
    erscheint er, und das Mausrad rollt die Seite.
    """

    WHEEL_EVENTS = ("<MouseWheel>", "<Button-4>", "<Button-5>")

    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = Canvas(self, bg=bg, highlightthickness=0, bd=0,
                             yscrollincrement=20)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical",
                                       command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = Frame(self.canvas, bg=bg)
        self._item = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._layout)
        self.canvas.bind("<Configure>", self._layout)

        # Eigene Bindemarke je Bereich: So rollt das Mausrad ueber jedem Widget
        # der Seite, nicht nur ueber dem Rollbalken, ohne sich global an alle
        # Fenster zu haengen.
        self._wheel_tag = f"ScrollArea{id(self)}"
        for sequence in self.WHEEL_EVENTS:
            self.bind_class(self._wheel_tag, sequence, self._on_wheel)

    def _layout(self, _event=None):
        width = self.canvas.winfo_width()
        visible = self.canvas.winfo_height()
        needed = self.inner.winfo_reqheight()
        height = max(needed, visible)
        self.canvas.itemconfigure(self._item, width=width, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        if needed > visible:
            if not self.scrollbar.winfo_manager():
                self.scrollbar.pack(side="right", fill="y", padx=(6, 0),
                                    before=self.canvas)
        elif self.scrollbar.winfo_manager():
            self.scrollbar.pack_forget()
            self.canvas.yview_moveto(0)

    def bind_wheel(self):
        """Mausrad fuer alle Widgets im Bereich einschalten - nach dem Aufbau aufrufen."""
        pending = [self]
        while pending:
            widget = pending.pop()
            tags = widget.bindtags()
            if self._wheel_tag not in tags:
                widget.bindtags((self._wheel_tag, *tags))
            pending.extend(widget.winfo_children())

    def _on_wheel(self, event):
        if not self.scrollbar.winfo_manager():          # passt alles, nichts zu rollen
            return None
        if event.num == 4 or event.delta > 0:
            direction = -1
        elif event.num == 5 or event.delta < 0:
            direction = 1
        else:
            return None
        # Windows meldet 120 je Raste, macOS kleinere Werte, Linux gar keine
        steps = max(1, abs(event.delta) // 120)
        self.canvas.yview_scroll(direction * steps * 3, "units")
        return "break"

    def destroy(self):
        for sequence in self.WHEEL_EVENTS:
            self.unbind_class(self._wheel_tag, sequence)
        super().destroy()


def path_row(parent, label, var, browse_cmd, button_text=None):
    """Zeile: Beschriftung + Eingabefeld + Durchsuchen-Button."""
    row = Frame(parent, bg=CARD)
    row.pack(fill="x", padx=14, pady=4)
    set_text(Label(row, font=FONT_SMALL, bg=CARD, fg=MUTED, width=16, anchor="w"),
             label).pack(side="left")
    entry = ttk.Entry(row, textvariable=var)
    entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
    # Frueher stand hier ein fester deutscher Vorgabetext - in der englischen
    # Oberflaeche hiessen diese Knoepfe deshalb weiter "Durchsuchen ..."
    FlatButton(row, button_text or _("Durchsuchen ..."), browse_cmd).pack(side="right")
    return entry


class NavButton(Frame):
    """Eintrag in der linken Navigationsleiste."""

    def __init__(self, parent, icon, text, command):
        super().__init__(parent, bg=SIDEBAR, cursor="hand2")
        self.command = command
        self.active = False

        self.bar = Frame(self, bg=SIDEBAR, width=3)
        self.bar.pack(side="left", fill="y")
        self.icon = Label(self, text=icon, bg=SIDEBAR, fg=SIDEBAR_TEXT,
                          font=("Segoe UI Emoji", 11), width=3)
        self.icon.pack(side="left", pady=5)
        self.label = set_text(Label(self, bg=SIDEBAR, fg=SIDEBAR_TEXT,
                                    font=FONT_SMALL, anchor="w"), text)
        self.label.pack(side="left", fill="x", expand=True, pady=5)

        for widget in (self, self.icon, self.label):
            widget.bind("<Button-1>", lambda _e: self.command())
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

    def _paint(self, bg, fg, bar):
        for widget in (self, self.icon, self.label):
            widget.configure(bg=bg)
        self.icon.configure(fg=fg)
        self.label.configure(fg=fg)
        self.bar.configure(bg=bar)

    def _on_enter(self, _e):
        if not self.active:
            self._paint(SIDEBAR_HOVER, SIDEBAR_TITLE, SIDEBAR_HOVER)

    def _on_leave(self, _e):
        if not self.active:
            self._paint(SIDEBAR, SIDEBAR_TEXT, SIDEBAR)

    def set_active(self, active):
        self.active = active
        if active:
            self._paint(SIDEBAR_HOVER, SIDEBAR_TITLE, ACCENT)
        else:
            self._paint(SIDEBAR, SIDEBAR_TEXT, SIDEBAR)


# --------------------------------------------------------------------------
# Basisklasse aller Module
# --------------------------------------------------------------------------

class Module:
    key = ""
    icon = "*"
    title = ""
    subtitle = ""
    group = ""
    description = ""

    def __init__(self, app, parent):
        self.app = app
        self.root = app.root
        self.body = parent
        self.busy = False
        self.cancel_event = threading.Event()
        self.build()

    # --- von den Modulen zu überschreiben ---------------------------------
    def build(self):
        raise NotImplementedError

    def repaint(self):
        """Farben nachziehen, die an keinem Widget haengen (etwa Tags einer Treeview).

        Die Widgets selbst faerbt refresh_colors() nach.
        """

    # --- Helfer für alle Module ------------------------------------------
    def ui(self, func, *args):
        """Callback im Hauptthread ausführen lassen.

        Tk darf nur aus dem Hauptthread bedient werden. Worker legen ihre
        Aufgaben deshalb in die Warteschlange der Anwendung; der Hauptthread
        arbeitet sie in ToolboxApp._pump ab.
        """
        self.app.event_queue.put((func, args))

    def run_async(self, worker, *args):
        """Worker in einem Hintergrundthread starten."""
        self.cancel_event.clear()
        thread = threading.Thread(target=self._guarded, args=(worker,) + args, daemon=True)
        thread.start()
        return thread

    def _guarded(self, worker, *args):
        try:
            worker(*args)
        except Exception as e:
            logging.error(f"{self.title}: {e}\n{traceback.format_exc()}")
            self.ui(messagebox.showerror, _("Fehler"),
                    _("Unerwarteter Fehler:\n{error}").format(error=e))

    def status(self, text):
        self.app.set_status(text)

    def ask_dir(self, title, var=None):
        folder = filedialog.askdirectory(title=title)
        if folder and var is not None:
            var.set(folder)
        return folder


# --------------------------------------------------------------------------
# Modul: Start
# --------------------------------------------------------------------------

class HomeModule(Module):
    key = "home"
    icon = "\U0001F3E0"
    title = "Start"
    subtitle = "Alle Werkzeuge auf einen Blick - Modul anklicken zum Öffnen"
    group = ""

    def build(self):
        wrap = Frame(self.body, bg=BG)
        wrap.pack(fill="both", expand=True)

        cards = Frame(wrap, bg=BG)
        cards.pack(fill="both", expand=True)
        for col in range(3):
            cards.columnconfigure(col, weight=1, uniform="cards")

        entries = [m for m in self.app.module_classes if m.key != "home"]
        for index, cls in enumerate(entries):
            self._make_tile(cards, cls, index // 3, index % 3)

        hint = Frame(wrap, bg=BG)
        hint.pack(fill="x", pady=(14, 0))
        missing = self.app.missing_dependencies()
        if missing:
            text = _("Optionale Zusatzmodule fehlen: {list}  -  Details unter "
                     "'Info & Hilfe'.").format(list=", ".join(missing))
            set_text(Label(hint, bg=BG, fg=WARN, font=FONT_SMALL, anchor="w"),
                     text).pack(fill="x")
        else:
            set_text(Label(hint, bg=BG, fg=OK, font=FONT_SMALL, anchor="w"),
                     _("Alle optionalen Zusatzmodule sind installiert.")).pack(fill="x")

    def _make_tile(self, parent, cls, row, col):
        tile = Frame(parent, bg=CARD, highlightbackground=BORDER,
                     highlightcolor=BORDER, highlightthickness=1, cursor="hand2")
        tile.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)

        icon = Label(tile, text=cls.icon, bg=CARD, fg=ACCENT,
                     font=("Segoe UI Emoji", 20), anchor="w")
        icon.pack(fill="x", padx=16, pady=(14, 2))
        title = set_text(Label(tile, bg=CARD, fg=TEXT, font=FONT_H2, anchor="w"),
                         _(cls.title))
        title.pack(fill="x", padx=16)
        desc = set_text(Label(tile, bg=CARD, fg=MUTED, font=FONT_SMALL, anchor="w",
                              justify="left", wraplength=250), _(cls.description))
        desc.pack(fill="x", padx=16, pady=(4, 16))

        def open_module(_e=None):
            self.app.show(cls.key)

        def enter(_e=None):
            for widget in (tile, icon, title, desc):
                widget.configure(bg=TILE_HOVER)
            tile.configure(highlightbackground=ACCENT, highlightcolor=ACCENT)

        def leave(_e=None):
            for widget in (tile, icon, title, desc):
                widget.configure(bg=CARD)
            tile.configure(highlightbackground=BORDER, highlightcolor=BORDER)

        for widget in (tile, icon, title, desc):
            widget.bind("<Button-1>", open_module)
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)


# --------------------------------------------------------------------------
# Modul: Bild-Vergleich (Split-Screen)
# --------------------------------------------------------------------------

class CompareModule(Module):
    key = "compare"
    icon = "\U0001F5BC"
    title = "Bild-Vergleich"
    subtitle = "Zwei Bilder nebeneinander prüfen, öffnen, tauschen oder löschen"
    group = "Ansehen"
    description = "Split-Screen für zwei Bilder inklusive Metadaten und MD5-Prüfsumme."

    @staticmethod
    def filetypes():
        """Dateifilter - erst beim Aufruf gebaut, damit die Sprache stimmt."""
        return [(_("Bilder"),
                 "*.jpg *.jpeg *.png *.bmp *.gif *.webp *.avif *.tif *.tiff *.ico"),
                (_("Alle Dateien"), "*.*")]

    def build(self):
        self.paths = {"left": None, "right": None}
        self.images = {"left": None, "right": None}
        self.photos = {"left": None, "right": None}
        self.labels = {}
        self.holders = {}
        self.infos = {}
        self._resize_jobs = {"left": None, "right": None}
        self.use_trash = tk.BooleanVar(value=HAS_TRASH)

        bar = make_card(self.body, fill="x")
        row = Frame(bar, bg=CARD)
        row.pack(fill="x", padx=14, pady=10)
        FlatButton(row, _("Linkes Bild öffnen"), lambda: self.open("left"),
                   kind="primary").pack(side="left", padx=(0, 6))
        FlatButton(row, _("Rechtes Bild öffnen"), lambda: self.open("right"),
                   kind="primary").pack(side="left", padx=6)
        FlatButton(row, _("Seiten tauschen"), self.swap).pack(side="left", padx=6)
        set_text(Checkbutton(row, variable=self.use_trash, bg=CARD, fg=MUTED,
                             font=FONT_SMALL, activebackground=CARD,
                             state="normal" if HAS_TRASH else "disabled",
                             selectcolor=CARD),
                 _("in den Papierkorb")).pack(side="right")

        panes = Frame(self.body, bg=BG)
        panes.pack(fill="both", expand=True, pady=(10, 0))
        panes.columnconfigure(0, weight=1, uniform="panes")
        panes.columnconfigure(1, weight=1, uniform="panes")
        panes.rowconfigure(0, weight=1)

        self._make_pane(panes, "left", _("LINKES BILD"), 0)
        self._make_pane(panes, "right", _("RECHTES BILD"), 1)

    def _make_pane(self, parent, side, caption, column):
        pane = Frame(parent, bg=CARD, highlightbackground=BORDER,
                     highlightcolor=BORDER, highlightthickness=1)
        pane.grid(row=0, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (6, 0))

        set_text(Label(pane, font=FONT_BOLD, bg=CARD, fg=TEXT), caption).pack(pady=(10, 6))

        # Ein tk.Label fordert immer so viel Platz an, wie sein Bild gross ist.
        # Diese Anforderung wandert sonst nach oben durch pane -> panes ->
        # content -> outer. Da outer vor der Statusleiste gepackt ist und
        # expand=True hat, quetscht ein grosses Bild die Statusleiste aus dem
        # Fenster - beim Tauschen schaukelte sich das mit jedem Wechsel weiter
        # auf. Der Halterahmen mit pack_propagate(False) sperrt die Anforderung
        # ein: Er behaelt die Groesse, die ihm das Gitter zuweist, egal was
        # darin liegt.
        holder = Frame(pane, bg=VIEWER_BG, width=200, height=200)
        holder.pack(fill="both", expand=True, padx=12)
        holder.pack_propagate(False)
        holder.bind("<Configure>", lambda _e, s=side: self._schedule_fit(s))
        self.holders[side] = holder

        canvas = set_text(Label(holder, bg=VIEWER_BG, fg=VIEWER_TEXT, font=FONT_SMALL),
                          _("Kein Bild geladen"))
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Double-Button-1>", lambda _e, s=side: self.open(s))
        self.labels[side] = canvas

        info = set_text(Label(pane, font=FONT_SMALL, bg=CARD, fg=MUTED, justify="left",
                              anchor="w", wraplength=420), _("Keine Datei geladen"))
        info.pack(fill="x", padx=12, pady=8)
        self.infos[side] = info

        actions = Frame(pane, bg=CARD)
        actions.pack(fill="x", padx=12, pady=(0, 12))
        FlatButton(actions, _("Öffnen"), lambda s=side: self.external(s)).pack(side="left")
        FlatButton(actions, _("Im Explorer zeigen"),
                   lambda s=side: self.explorer(s)).pack(side="left", padx=6)
        FlatButton(actions, _("Löschen"), lambda s=side: self.delete(s),
                   kind="danger").pack(side="right")

    # ------------------------------------------------------------------ laden
    def open(self, side):
        path = filedialog.askopenfilename(title=_("Bild auswählen"),
                                          filetypes=self.filetypes())
        if path:
            self.load(side, path)

    def load(self, side, path):
        try:
            with Image.open(path) as im:
                self.images[side] = im.convert("RGBA") if im.mode == "P" else im.copy()
            info = image_info(path)
            if not info:
                messagebox.showerror(_("Fehler"), _("Bild konnte nicht gelesen werden."))
                return
            self.paths[side] = path
            checksum = md5_of(path)
            set_text(self.infos[side],
                     _("Datei: {name}\n"
                       "Auflösung: {res}     Größe: {size}     Format: {format}\n"
                       "MD5: {md5}\n{path}").format(
                         name=os.path.basename(path), res=info["resolution"],
                         size=info["size"], format=info["format"],
                         md5=checksum, path=path), fg=TEXT)
            self._fit(side)
            self.status(_("Geladen: {name}").format(name=os.path.basename(path)))
        except Exception as e:
            logging.error(f"Fehler beim Laden von {path}: {e}")
            messagebox.showerror(
                _("Fehler"),
                _("Bild konnte nicht geladen werden:\n{error}").format(error=e))

    def _schedule_fit(self, side):
        """Nachskalieren kurz aufschieben - je Seite ein eigener Auftrag.

        Vorher teilten sich beide Seiten einen Auftrag: Meldete rechts eine
        Groessenaenderung, wurde der noch offene Auftrag von links verworfen
        und die linke Seite blieb unskaliert.
        """
        if self.images[side] is None:
            return
        job = self._resize_jobs.get(side)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._resize_jobs[side] = self.root.after(150, lambda: self._fit(side))

    def _fit(self, side):
        image = self.images[side]
        label = self.labels[side]
        holder = self.holders[side]
        self._resize_jobs[side] = None
        if image is None:
            return
        try:
            # Der Halterahmen hat die verlaessliche Groesse: Das Label darin
            # traegt die Groesse seines Bildes und wuerde sich selbst messen.
            width = max(holder.winfo_width() - 8, 100)
            height = max(holder.winfo_height() - 8, 100)
        except tk.TclError:
            return                          # Fenster wird gerade geschlossen
        try:
            thumb = image.copy()
            thumb.thumbnail((width, height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            self.photos[side] = photo
            set_text(label, "", image=photo)
        except Exception as e:
            logging.error(f"Fehler beim Skalieren: {e}")

    # ---------------------------------------------------------------- Aktionen
    def swap(self):
        """Seiten tauschen.

        Alles Noetige liegt bereits im Speicher, deshalb wird nichts neu von
        der Platte gelesen. Frueher lief bei jedem Tausch ein vollstaendiges
        load() - inklusive MD5 ueber die ganze Datei, was bei grossen Bildern
        spuerbar hakte.
        """
        for feld in (self.paths, self.images, self.photos):
            feld["left"], feld["right"] = feld["right"], feld["left"]

        links, rechts = self.infos["left"], self.infos["right"]
        # text_of und color_of statt cget: So folgen Text und Farbe auch nach
        # dem Tausch einem Sprach- oder Farbwechsel
        text, farbe = text_of(links), color_of(links, "fg")
        set_text(links, text_of(rechts), fg=color_of(rechts, "fg"))
        set_text(rechts, text, fg=farbe)

        for side in ("left", "right"):
            if self.images[side] is None:
                self.clear(side)
            else:
                self._fit(side)

        if any(self.paths.values()):
            self.status(_("Seiten getauscht."))

    def clear(self, side):
        self.paths[side] = None
        self.images[side] = None
        self.photos[side] = None
        set_text(self.labels[side], _("Kein Bild geladen"), image="")
        set_text(self.infos[side], _("Keine Datei geladen"), fg=MUTED)

    def external(self, side):
        path = self.paths[side]
        if not path:
            messagebox.showinfo(_("Info"), _("Keine Datei geladen."))
            return
        try:
            open_path(path)
        except Exception as e:
            messagebox.showerror(
                _("Fehler"),
                _("Konnte Datei nicht öffnen:\n{error}").format(error=e))

    def explorer(self, side):
        path = self.paths[side]
        if not path:
            messagebox.showinfo(_("Info"), _("Keine Datei geladen."))
            return
        try:
            show_in_explorer(path)
        except Exception as e:
            messagebox.showerror(
                _("Fehler"),
                _("Konnte Ordner nicht öffnen:\n{error}").format(error=e))

    def delete(self, side):
        path = self.paths[side]
        if not path:
            messagebox.showinfo(_("Info"), _("Keine Datei geladen."))
            return
        trash = self.use_trash.get() and HAS_TRASH
        verb = (_("in den Papierkorb verschieben") if trash
                else _("ENDGÜLTIG löschen"))
        if not messagebox.askyesno(
                _("Löschen"),
                _("Datei wirklich {action}?\n\n{path}").format(action=verb, path=path)):
            return
        try:
            self.images[side] = None      # Datei-Handle freigeben
            remove_file(path, trash)
            self.clear(side)
            self.status(_("Gelöscht: {name}").format(name=os.path.basename(path)))
        except Exception as e:
            logging.error(f"Fehler beim Löschen: {e}")
            messagebox.showerror(
                _("Fehler"),
                _("Konnte nicht löschen:\n{error}").format(error=e))


# --------------------------------------------------------------------------
# Gemeinsame Basis für die beiden Trefferlisten (Duplikate / Ähnliche)
# --------------------------------------------------------------------------

class GroupResultModule(Module):
    """Basis für Module, die Gruppen von Dateien finden und bearbeiten."""

    tree_heading = "Treffer"

    def __init__(self, app, parent):
        self.groups = []          # [(gruppentitel, [eintrag, ...]), ...]
        self.thumbnails = {}
        super().__init__(app, parent)

    # ---------------------------------------------------------------- Baumteil
    def build_tree(self, parent):
        wrap = Frame(parent, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        columns = ("res", "size")
        self.tree = ttk.Treeview(wrap, columns=columns, show="tree headings",
                                 selectmode="extended")
        set_heading(self.tree, "#0", _(self.tree_heading))
        set_heading(self.tree, "res", _("Auflösung"))
        set_heading(self.tree, "size", _("Größe"))
        self.tree.column("#0", width=520, stretch=True)
        self.tree.column("res", width=110, anchor="center", stretch=False)
        self.tree.column("size", width=90, anchor="e", stretch=False)

        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.tag_configure("group", font=FONT_BOLD)
        self.repaint()
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<Double-Button-1>", self._on_double_click)

    def repaint(self):
        self.tree.tag_configure("keep", foreground=OK)

    def visible_groups(self):
        """Gruppen, die angezeigt und bearbeitet werden (Filter-Hook)."""
        return self.groups

    def render_groups(self):
        for item in self.tree.get_children():
            for row in (item, *self.tree.get_children(item)):
                forget_text((self.tree, "item", row))
            self.tree.delete(item)
        self.thumbnails.clear()

        groups = self.visible_groups()
        if not groups:
            self.set_summary(_("Keine Treffer."))
            return

        thumb_budget = MAX_THUMBS
        for index, (caption, entries) in enumerate(groups, 1):
            parent = self.tree.insert("", "end", open=True, tags=("group",))
            set_item_text(self.tree, parent,
                          _("GRUPPE {no}  -  {name}  ({count} Dateien)").format(
                              no=index, name=caption, count=len(entries)))
            for position, entry in enumerate(entries):
                path = entry["path"]
                thumb = None
                if thumb_budget > 0:
                    thumb = self._thumbnail(path)
                    if thumb is not None:
                        thumb_budget -= 1
                tags = (path, "keep") if position == 0 else (path,)
                item = self.tree.insert(parent, "end",
                                        values=(entry.get("resolution", "?"),
                                                entry.get("size", "?")),
                                        image=thumb if thumb else "",
                                        tags=tags)
                text = " " + os.path.basename(path)
                if position == 0:                   # die erste Datei jeder Gruppe bleibt
                    text += "  " + _("[behalten]")
                set_item_text(self.tree, item, text)
        total = sum(len(entries) - 1 for _c, entries in groups)
        self.set_summary(_("{groups} Gruppen - {files} Datei(en) über die jeweils "
                           "erste hinaus. Rechtsklick für Optionen.").format(
            groups=len(groups), files=total))

    def _thumbnail(self, path, size=(38, 38)):
        try:
            with Image.open(path) as im:
                im = im.convert("RGBA")
                im.thumbnail(size, Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(im)
            self.thumbnails[path] = photo
            return photo
        except Exception:
            return None

    def set_summary(self, text):
        set_text(self.summary, text)

    # --------------------------------------------------------------- Auswahl
    def selected_paths(self):
        paths = []
        for item in self.tree.selection():
            tags = self.tree.item(item, "tags")
            if tags and tags[0] not in ("group", "keep"):
                paths.append(tags[0])
        return paths

    def _on_double_click(self, _event):
        for path in self.selected_paths():
            try:
                open_path(path)
            except Exception as e:
                messagebox.showerror(
                    _("Fehler"),
                    _("Konnte Datei nicht öffnen:\n{error}").format(error=e))
            break

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        if item not in self.tree.selection():
            self.tree.selection_set(item)
        paths = self.selected_paths()
        if not paths:
            return

        menu = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TEXT,
                       activebackground=ACCENT, activeforeground=ON_ACCENT,
                       borderwidth=1)
        menu.add_command(label=_("Öffnen"), command=lambda: self._each(paths, open_path))
        menu.add_command(label=_("Im Explorer zeigen"),
                         command=lambda: self._each(paths[:1], show_in_explorer))
        menu.add_separator()
        menu.add_command(label=_("Links im Vergleich öffnen"),
                         command=lambda: self.app.send_to_compare(paths[0], "left"))
        menu.add_command(label=_("Rechts im Vergleich öffnen"),
                         command=lambda: self.app.send_to_compare(paths[0], "right"))
        menu.add_separator()
        menu.add_command(label=_("Auswahl löschen ({count})").format(count=len(paths)),
                         command=lambda: self.delete_selection(paths))
        menu.add_command(label=_("Auswahl verschieben ({count})").format(count=len(paths)),
                         command=lambda: self.move_selection(paths))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    @staticmethod
    def _each(paths, func):
        for path in paths:
            try:
                func(path)
            except Exception as e:
                messagebox.showerror(_("Fehler"), f"{path}\n{e}")

    # -------------------------------------------------------------- Aktionen
    def _forget(self, paths):
        """Dateien aus den Gruppen entfernen und Ansicht aktualisieren."""
        gone = set(paths)
        new_groups = []
        for caption, entries in self.groups:
            rest = [e for e in entries if e["path"] not in gone]
            if len(rest) > 1:
                new_groups.append((caption, rest))
        self.groups = new_groups
        self.render_groups()

    def delete_selection(self, paths):
        trash = self.use_trash.get() and HAS_TRASH
        verb = (_("in den Papierkorb verschieben") if trash
                else _("ENDGÜLTIG löschen"))
        if not messagebox.askyesno(
                _("Bestätigen"),
                _("{count} Datei(en) {action}?").format(count=len(paths), action=verb)):
            return
        done, failed = 0, 0
        for path in paths:
            try:
                remove_file(path, trash)
                done += 1
            except Exception as e:
                failed += 1
                logging.error(f"Löschen fehlgeschlagen {path}: {e}")
        self._forget(paths)
        self.status(_("{done} gelöscht, {failed} fehlgeschlagen.").format(
            done=done, failed=failed))
        messagebox.showinfo(_("Fertig"),
                            _("{done} Datei(en) gelöscht.\n{failed} fehlgeschlagen."
                              ).format(done=done, failed=failed))

    def move_selection(self, paths):
        target = filedialog.askdirectory(title=_("Zielordner auswählen"))
        if not target:
            return
        done, failed = 0, 0
        for path in paths:
            try:
                dest = unique_path(os.path.join(target, os.path.basename(path)))
                shutil.move(path, dest)
                done += 1
            except Exception as e:
                failed += 1
                logging.error(f"Verschieben fehlgeschlagen {path}: {e}")
        self._forget(paths)
        self.status(_("{done} verschoben, {failed} fehlgeschlagen.").format(
            done=done, failed=failed))
        messagebox.showinfo(_("Fertig"),
                            _("{done} Datei(en) verschoben.\n{failed} fehlgeschlagen."
                              ).format(done=done, failed=failed))

    def extra_paths(self):
        """Alle sichtbaren Dateien ausser der jeweils ersten je Gruppe."""
        paths = []
        for _caption, entries in self.visible_groups():
            paths.extend(e["path"] for e in entries[1:])
        return paths

    def delete_all_extra(self):
        paths = self.extra_paths()
        if not paths:
            messagebox.showinfo(_("Info"), _("Keine Treffer vorhanden."))
            return
        self.delete_selection(paths)

    def move_all_extra(self):
        paths = self.extra_paths()
        if not paths:
            messagebox.showinfo(_("Info"), _("Keine Treffer vorhanden."))
            return
        self.move_selection(paths)


# --------------------------------------------------------------------------
# Modul: Duplikat-Finder
# --------------------------------------------------------------------------

class DuplicateModule(GroupResultModule):
    key = "duplicates"
    icon = "\U0001F50E"
    title = "Duplikat-Finder"
    subtitle = "Findet byte-identische Bilder über Dateigröße und MD5-Prüfsumme"
    group = "Aufräumen"
    description = "Exakte Doppel finden und gruppenweise löschen oder verschieben."
    tree_heading = "Datei"

    def build(self):
        self.folder = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.min_px = tk.StringVar(value="0")
        self.max_px = tk.StringVar(value="")
        self.use_trash = tk.BooleanVar(value=HAS_TRASH)

        card = make_card(self.body, fill="x")
        card_title(card, _("Ordner scannen"))
        path_row(card, _("Quellordner"), self.folder,
                 lambda: self.ask_dir(_("Ordner zum Scannen auswählen"), self.folder))

        options = Frame(card, bg=CARD)
        options.pack(fill="x", padx=14, pady=(4, 4))
        set_text(Checkbutton(options, variable=self.recursive, bg=CARD, fg=TEXT,
                             font=FONT_SMALL, activebackground=CARD, selectcolor=CARD),
                 _("Unterordner einbeziehen")).pack(side="left")
        set_text(Label(options, bg=CARD, fg=MUTED, font=FONT_SMALL),
                 _("Pixel min.:")).pack(side="left", padx=(20, 4))
        ttk.Entry(options, textvariable=self.min_px, width=12).pack(side="left")
        set_text(Label(options, bg=CARD, fg=MUTED, font=FONT_SMALL),
                 _("max.:")).pack(side="left", padx=(10, 4))
        ttk.Entry(options, textvariable=self.max_px, width=12).pack(side="left")
        FlatButton(options, _("Filter anwenden"), self.render_groups).pack(side="left", padx=10)

        actions = Frame(card, bg=CARD)
        actions.pack(fill="x", padx=14, pady=(6, 12))
        self.scan_btn = FlatButton(actions, _("Scan starten"), self.start_scan, kind="primary")
        self.scan_btn.pack(side="left")
        self.cancel_btn = FlatButton(actions, _("Abbrechen"), self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        FlatButton(actions, _("Alle Duplikate löschen"), self.delete_all_extra,
                   kind="danger").pack(side="left", padx=(20, 6))
        FlatButton(actions, _("Alle Duplikate verschieben"), self.move_all_extra,
                   kind="warn").pack(side="left")
        set_text(Checkbutton(actions, variable=self.use_trash, bg=CARD, fg=MUTED,
                             font=FONT_SMALL, activebackground=CARD,
                             state="normal" if HAS_TRASH else "disabled",
                             selectcolor=CARD),
                 _("in den Papierkorb")).pack(side="right")

        self.progress = ttk.Progressbar(card, mode="determinate")
        self.progress.pack(fill="x", padx=14, pady=(0, 12))

        result = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(result, _("Gefundene Gruppen"))
        self.summary = set_text(Label(result, bg=CARD, fg=MUTED, font=FONT_SMALL,
                                      anchor="w"), _("Noch nicht gescannt."))
        self.summary.pack(fill="x", padx=14, pady=(0, 6))
        self.build_tree(result)

    # ------------------------------------------------------------------ Scan
    def cancel(self):
        self.cancel_event.set()
        self.status(_("Abbruch angefordert ..."))

    def _set_busy(self, busy):
        self.busy = busy
        self.scan_btn.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    def start_scan(self):
        folder = self.folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror(_("Ordner"), _("Bitte einen gültigen Quellordner wählen."))
            return
        if self.busy:
            return
        self._set_busy(True)
        self.groups = []
        self.render_groups()
        self.set_summary(_("Scanne ..."))
        self.progress.configure(value=0, maximum=100)
        self.run_async(self._scan_worker, folder, self.recursive.get())

    def _scan_worker(self, folder, recursive):
        self.ui(self.status, _("Sammle Dateien ..."))
        files = list(iter_images(folder, recursive))
        by_size = defaultdict(list)
        for path in files:
            try:
                by_size[os.path.getsize(path)].append(path)
            except OSError:
                continue

        candidates = [group for group in by_size.values() if len(group) > 1]
        total = sum(len(group) for group in candidates)
        self.ui(self.progress.configure, {"maximum": max(total, 1), "value": 0})

        by_hash = defaultdict(list)
        processed = 0
        for group in candidates:
            for path in group:
                if self.cancel_event.is_set():
                    self.ui(self._scan_done, [], len(files), True)
                    return
                try:
                    by_hash[md5_of(path)].append(path)
                except OSError:
                    pass
                processed += 1
                if processed % 25 == 0 or processed == total:
                    self.ui(self.progress.configure, {"value": processed})
                    self.ui(self.status,
                            _("Prüfe Inhalte ... {done}/{total}").format(
                                done=processed, total=total))

        groups = []
        for checksum, paths in by_hash.items():
            if len(paths) < 2:
                continue
            entries = []
            for path in paths:
                info = image_info(path) or {}
                entries.append({"path": path,
                                "resolution": info.get("resolution", "?"),
                                "size": info.get("size", human_size(
                                    os.path.getsize(path))),
                                "pixels": info.get("pixels", 0),
                                "bytes": info.get("bytes", 0)})
            entries.sort(key=lambda e: (-e["pixels"], -e["bytes"], e["path"]))
            groups.append((checksum[:12], entries))

        groups.sort(key=lambda g: -len(g[1]))
        self.ui(self._scan_done, groups, len(files), False)

    def _scan_done(self, groups, scanned, cancelled):
        self.progress.configure(value=0)
        self._set_busy(False)
        self.groups = groups
        self.render_groups()
        extra = sum(len(entries) - 1 for _c, entries in groups)
        note = _("Abgebrochen - ") if cancelled else ""
        self.status(note + _("{scanned} Bilder geprüft, {groups} Duplikat-Gruppen "
                             "({extra} überzählige Dateien).").format(
            scanned=scanned, groups=len(groups), extra=extra))

    # ---------------------------------------------------------------- Filter
    def visible_groups(self):
        """Gruppen nach dem Pixel-Filter (Gesamtpixel je Bild)."""
        try:
            min_px = int(self.min_px.get() or 0)
        except ValueError:
            min_px = 0
        try:
            max_px = int(self.max_px.get()) if self.max_px.get().strip() else None
        except ValueError:
            max_px = None
        if not min_px and max_px is None:
            return self.groups

        filtered = []
        for caption, entries in self.groups:
            keep = [e for e in entries
                    if e["pixels"] >= min_px
                    and (max_px is None or e["pixels"] <= max_px)]
            if len(keep) > 1:
                filtered.append((caption, keep))
        return filtered


# --------------------------------------------------------------------------
# Modul: Ähnliche Bilder
# --------------------------------------------------------------------------

class SimilarModule(GroupResultModule):
    key = "similar"
    icon = "\U0001F9E9"
    title = "Ähnliche Bilder"
    subtitle = "Findet visuell ähnliche Bilder über einen Perceptual Hash"
    group = "Aufräumen"
    description = "Erkennt Varianten, Skalierungen und Neukomprimierungen desselben Motivs."
    tree_heading = "Datei"

    def build(self):
        self.folder = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.similarity = tk.IntVar(value=90)
        self.use_trash = tk.BooleanVar(value=HAS_TRASH)

        card = make_card(self.body, fill="x")
        card_title(card, _("Ordner scannen"))
        path_row(card, _("Quellordner"), self.folder,
                 lambda: self.ask_dir(_("Ordner zum Scannen auswählen"), self.folder))

        options = Frame(card, bg=CARD)
        options.pack(fill="x", padx=14, pady=(4, 4))
        set_text(Checkbutton(options, variable=self.recursive, bg=CARD, fg=TEXT,
                             font=FONT_SMALL, activebackground=CARD, selectcolor=CARD),
                 _("Unterordner einbeziehen")).pack(side="left")
        set_text(Label(options, bg=CARD, fg=MUTED, font=FONT_SMALL),
                 _("Ähnlichkeit:")).pack(side="left", padx=(20, 6))
        scale = ttk.Scale(options, from_=50, to=100, orient="horizontal", length=220)
        scale.pack(side="left")
        self.similarity_label = Label(options, text="90 %", bg=CARD, fg=TEXT,
                                      font=FONT_BOLD, width=6)
        self.similarity_label.pack(side="left", padx=6)
        scale.set(90)                       # erst jetzt - Label muss existieren
        scale.configure(command=self._on_scale)

        actions = Frame(card, bg=CARD)
        actions.pack(fill="x", padx=14, pady=(6, 12))
        self.scan_btn = FlatButton(actions, _("Scan starten"), self.start_scan, kind="primary")
        self.scan_btn.pack(side="left")
        self.cancel_btn = FlatButton(actions, _("Abbrechen"), self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        FlatButton(actions, _("Alle Ähnlichen löschen"), self.delete_all_extra,
                   kind="danger").pack(side="left", padx=(20, 6))
        FlatButton(actions, _("Alle Ähnlichen verschieben"), self.move_all_extra,
                   kind="warn").pack(side="left")
        set_text(Checkbutton(actions, variable=self.use_trash, bg=CARD, fg=MUTED,
                             font=FONT_SMALL, activebackground=CARD,
                             state="normal" if HAS_TRASH else "disabled",
                             selectcolor=CARD),
                 _("in den Papierkorb")).pack(side="right")

        self.progress = ttk.Progressbar(card, mode="determinate")
        self.progress.pack(fill="x", padx=14, pady=(0, 12))

        result = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(result, _("Gefundene Gruppen"))
        self.summary = set_text(Label(result, bg=CARD, fg=MUTED, font=FONT_SMALL,
                                      anchor="w"), _("Noch nicht gescannt."))
        self.summary.pack(fill="x", padx=14, pady=(0, 6))
        self.build_tree(result)

    def _on_scale(self, value):
        percent = int(float(value))
        self.similarity.set(percent)
        self.similarity_label.configure(text=f"{percent} %")

    def cancel(self):
        self.cancel_event.set()
        self.status(_("Abbruch angefordert ..."))

    def _set_busy(self, busy):
        self.busy = busy
        self.scan_btn.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    def start_scan(self):
        folder = self.folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror(_("Ordner"), _("Bitte einen gültigen Quellordner wählen."))
            return
        if self.busy:
            return
        self._set_busy(True)
        self.groups = []
        self.render_groups()
        self.set_summary(_("Scanne ..."))
        self.progress.configure(value=0, maximum=100)
        self.run_async(self._scan_worker, folder, self.recursive.get(),
                       self.similarity.get())

    def _scan_worker(self, folder, recursive, threshold):
        self.ui(self.status, _("Sammle Dateien ..."))
        files = list(iter_images(folder, recursive))
        total = len(files)
        self.ui(self.progress.configure, {"maximum": max(total, 1), "value": 0})

        hashes = []
        for index, path in enumerate(files, 1):
            if self.cancel_event.is_set():
                self.ui(self._scan_done, [], 0, True)
                return
            value = average_hash(path)
            if value is not None:
                hashes.append((path, value))
            if index % 20 == 0 or index == total:
                self.ui(self.progress.configure, {"value": index})
                self.ui(self.status,
                        _("Berechne Hashes ... {done}/{total}").format(
                            done=index, total=total))

        # 64 Bit -> erlaubter Abstand in Bit
        max_distance = round((100 - threshold) / 100 * 64)
        self.ui(self.status, _("Vergleiche Bilder ..."))

        used = set()
        groups = []
        for i, (path1, hash1) in enumerate(hashes):
            if path1 in used or self.cancel_event.is_set():
                continue
            members = [path1]
            for path2, hash2 in hashes[i + 1:]:
                if path2 in used:
                    continue
                if hamming(hash1, hash2) <= max_distance:
                    members.append(path2)
                    used.add(path2)
            if len(members) > 1:
                used.add(path1)
                entries = []
                for path in members:
                    info = image_info(path) or {}
                    entries.append({"path": path,
                                    "resolution": info.get("resolution", "?"),
                                    "size": info.get("size", "?"),
                                    "pixels": info.get("pixels", 0),
                                    "bytes": info.get("bytes", 0)})
                entries.sort(key=lambda e: (-e["pixels"], -e["bytes"], e["path"]))
                groups.append((os.path.basename(entries[0]["path"]), entries))

        groups.sort(key=lambda g: -len(g[1]))
        self.ui(self._scan_done, groups, len(hashes), self.cancel_event.is_set())

    def _scan_done(self, groups, scanned, cancelled):
        self.progress.configure(value=0)
        self._set_busy(False)
        self.groups = groups
        self.render_groups()
        note = _("Abgebrochen - ") if cancelled else ""
        self.status(note + _("{scanned} Bilder verglichen, {groups} ähnliche Gruppen."
                             ).format(scanned=scanned, groups=len(groups)))


# --------------------------------------------------------------------------
# Modul: Dimensions-Filter
# --------------------------------------------------------------------------

class DimensionModule(Module):
    key = "dimensions"
    icon = "\U0001F4D0"
    title = "Dimensions-Filter"
    subtitle = ("Findet Bilder, die in Breite UND Höhe unter einem Schwellwert liegen, "
                "und räumt sie weg")
    group = "Aufräumen"
    description = "Kleine Bilder aufspüren und in einen Ordner verschieben oder löschen."

    def build(self):
        self.folder = tk.StringVar()
        self.target = tk.StringVar()
        self.threshold = tk.StringVar(value="2000")
        self.recursive = tk.BooleanVar(value=True)
        self.action = tk.StringVar(value="move")
        self.permanent = tk.BooleanVar(value=not HAS_TRASH)
        self.candidates = []

        card = make_card(self.body, fill="x")
        card_title(card, _("Suche"))
        path_row(card, _("Quellordner"), self.folder,
                 lambda: self.ask_dir(_("Quellordner wählen"), self.folder))

        options = Frame(card, bg=CARD)
        options.pack(fill="x", padx=14, pady=4)
        set_text(Checkbutton(options, variable=self.recursive, bg=CARD, fg=TEXT,
                             font=FONT_SMALL, activebackground=CARD, selectcolor=CARD),
                 _("Unterordner einbeziehen")).pack(side="left")
        set_text(Label(options, bg=CARD, fg=MUTED, font=FONT_SMALL),
                 _("Schwellwert in Pixel:")).pack(side="left", padx=(20, 6))
        ttk.Spinbox(options, from_=1, to=200000, width=8,
                    textvariable=self.threshold).pack(side="left")
        set_text(Label(options, bg=CARD, fg=MUTED, font=FONT_SMALL),
                 _("Treffer = Breite UND Höhe kleiner als dieser Wert")).pack(
            side="left", padx=8)

        scan_row = Frame(card, bg=CARD)
        scan_row.pack(fill="x", padx=14, pady=(6, 12))
        self.scan_btn = FlatButton(scan_row, _("Scannen"), self.start_scan, kind="primary")
        self.scan_btn.pack(side="left")
        self.cancel_btn = FlatButton(scan_row, _("Abbrechen"), self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        self.summary = set_text(Label(scan_row, bg=CARD, fg=MUTED, font=FONT_SMALL),
                                _("Noch nicht gescannt."))
        self.summary.pack(side="left", padx=12)

        action_card = make_card(self.body, fill="x", pady=(10, 0))
        card_title(action_card, _("Aktion mit den Treffern"))

        move_row = Frame(action_card, bg=CARD)
        move_row.pack(fill="x", padx=14, pady=2)
        set_text(Radiobutton(move_row, variable=self.action, value="move",
                             command=self._sync, bg=CARD, fg=TEXT, font=FONT_SMALL,
                             activebackground=CARD, selectcolor=CARD, width=16,
                             anchor="w"), _("Verschieben nach")).pack(side="left")
        self.target_entry = ttk.Entry(move_row, textvariable=self.target)
        self.target_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.target_btn = FlatButton(move_row, _("Durchsuchen ..."),
                                     lambda: self.ask_dir(_("Zielordner wählen"), self.target))
        self.target_btn.pack(side="right")

        del_row = Frame(action_card, bg=CARD)
        del_row.pack(fill="x", padx=14, pady=2)
        set_text(Radiobutton(del_row, variable=self.action, value="delete",
                             command=self._sync, bg=CARD, fg=TEXT, font=FONT_SMALL,
                             activebackground=CARD, selectcolor=CARD, width=16,
                             anchor="w"), _("Löschen")).pack(side="left")
        self.perm_chk = set_text(Checkbutton(
            del_row, variable=self.permanent, bg=CARD, fg=TEXT, font=FONT_SMALL,
            activebackground=CARD, selectcolor=CARD),
            _("endgültig löschen (ohne Haken: in den Papierkorb)"))
        self.perm_chk.pack(side="left")

        run_row = Frame(action_card, bg=CARD)
        run_row.pack(fill="x", padx=14, pady=(8, 12))
        self.run_btn = FlatButton(run_row, _("Ausführen"), self.start_action,
                                  kind="danger", state="disabled")
        self.run_btn.pack(side="left")
        self.progress = ttk.Progressbar(run_row, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

        log_card = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(log_card, _("Protokoll"))
        log_wrap = Frame(log_card, bg=CARD)
        log_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.log = Text(log_wrap, height=10, wrap="none", font=FONT_MONO,
                        bg=CARD_ALT, fg=TEXT, insertbackground=TEXT, relief="flat",
                        highlightbackground=BORDER, highlightthickness=1)
        yscroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        if not HAS_TRASH:
            # Steht allein im Protokoll, bis der erste Scan es leert - bis dahin
            # folgt der Hinweis einem Sprachwechsel
            remember_text((self.log, "content"), self._set_log,
                          _("Hinweis: 'send2trash' nicht installiert - Löschen erfolgt "
                            "endgültig.  pip install send2trash"))
        self._sync()

    # ------------------------------------------------------------------ Helfer
    def _set_log(self, text):
        self.log.delete("1.0", "end")
        self.log.insert("end", text + "\n")

    def _log(self, message):
        forget_text((self.log, "content"))      # was jetzt dazukommt, ist Verlauf
        self.log.insert("end", message + "\n")
        self.log.see("end")

    def _sync(self, *_args):
        is_move = self.action.get() == "move"
        state = "normal" if is_move else "disabled"
        self.target_entry.configure(state=state)
        self.target_btn.configure(state=state)
        if is_move:
            self.perm_chk.configure(state="disabled")
        else:
            self.perm_chk.configure(state="normal" if HAS_TRASH else "disabled")
        self.run_btn.configure(
            state="normal" if (self.candidates and not self.busy) else "disabled")

    def _set_busy(self, busy):
        self.busy = busy
        self.scan_btn.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        self._sync()

    def cancel(self):
        self.cancel_event.set()
        self.status(_("Abbruch angefordert ..."))

    def _get_threshold(self):
        try:
            value = int(float(self.threshold.get()))
            if value < 1:
                raise ValueError
            return value
        except ValueError:
            messagebox.showerror(_("Ungültig"),
                                 _("Bitte einen Schwellwert als Ganzzahl > 0 eingeben."))
            return None

    # -------------------------------------------------------------------- Scan
    def start_scan(self):
        if self.busy:
            return
        folder = self.folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror(_("Ordner"), _("Bitte einen gültigen Quellordner wählen."))
            return
        threshold = self._get_threshold()
        if threshold is None:
            return

        self.candidates = []
        self.log.delete("1.0", "end")
        self._set_busy(True)
        set_text(self.summary, _("Scanne ..."))
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        # Tk-Variablen im Hauptthread lesen und dem Worker mitgeben
        self.run_async(self._scan_worker, folder, self.recursive.get(), threshold,
                       self.target.get().strip())

    def _scan_worker(self, folder, recursive, threshold, target):
        candidates, total, errors = [], 0, 0
        target_prefix = (os.path.normcase(os.path.abspath(target)) + os.sep) if target else None

        walker = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]
        for dirpath, _dirs, files in walker:
            if self.cancel_event.is_set():
                break
            if target_prefix and (os.path.normcase(os.path.abspath(dirpath)) + os.sep
                                  ).startswith(target_prefix):
                continue
            for filename in files:
                path = os.path.join(dirpath, filename)
                if not os.path.isfile(path):
                    continue
                try:
                    with Image.open(path) as im:
                        width, height = im.size
                except (UnidentifiedImageError, OSError, ValueError):
                    continue                       # keine (lesbare) Bilddatei
                except Exception:
                    errors += 1
                    continue
                total += 1
                if width < threshold and height < threshold:
                    candidates.append((path, width, height))
            self.ui(self.status,
                    _("Scanne ... {count} Bilder geprüft").format(count=total))

        self.ui(self._scan_done, candidates, total, errors, threshold)

    def _scan_done(self, candidates, total, errors, threshold):
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.candidates = candidates
        self._set_busy(False)

        message = _("{total} Bilder geprüft - {hits} Treffer "
                    "(< {limit} px in Breite und Höhe).").format(
            total=total, hits=len(candidates), limit=threshold)
        if errors:
            message += _("  {count} Datei(en) nicht lesbar.").format(count=errors)
        set_text(self.summary, message, fg=OK if candidates else MUTED)
        self._log(message)
        for path, width, height in candidates[:1000]:
            self._log(f"  {width}x{height}\t{path}")
        if len(candidates) > 1000:
            self._log(_("  ... und {count} weitere.").format(
                count=len(candidates) - 1000))
        self.status(message)

    # ------------------------------------------------------------------ Aktion
    def start_action(self):
        if self.busy or not self.candidates:
            return
        mode = self.action.get()
        count = len(self.candidates)

        if mode == "move":
            target = self.target.get().strip()
            if not target:
                messagebox.showerror(_("Zielordner"), _("Bitte einen Zielordner wählen."))
                return
            source = os.path.normcase(os.path.abspath(self.folder.get().strip())) + os.sep
            if (os.path.normcase(os.path.abspath(target)) + os.sep).startswith(source):
                if not messagebox.askyesno(
                        _("Achtung"),
                        _("Der Zielordner liegt innerhalb des Quellordners. Fortfahren?")):
                    return
            try:
                os.makedirs(target, exist_ok=True)
            except OSError as e:
                messagebox.showerror(
                    _("Zielordner"),
                    _("Kann Zielordner nicht anlegen:\n{error}").format(error=e))
                return
            question = _("{count} Bild(er) verschieben nach:\n{target}").format(
                count=count, target=target)
        else:
            permanent = self.permanent.get() or not HAS_TRASH
            question = (_("{count} Bild(er) ENDGÜLTIG löschen?\n"
                          "Das kann NICHT rückgängig gemacht werden.")
                        if permanent else
                        _("{count} Bild(er) in den Papierkorb verschieben?")
                        ).format(count=count)

        if not messagebox.askyesno(_("Bestätigen"), question):
            return

        self._set_busy(True)
        self.progress.configure(mode="determinate", maximum=count, value=0)
        # Tk-Variablen im Hauptthread lesen und dem Worker mitgeben
        self.run_async(self._action_worker, list(self.candidates), mode,
                       os.path.abspath(self.folder.get().strip()),
                       self.target.get().strip(),
                       self.permanent.get() or not HAS_TRASH)

    def _action_worker(self, items, mode, source_root, target, permanent):
        done, failed = 0, 0

        for index, (path, _w, _h) in enumerate(items, 1):
            if self.cancel_event.is_set():
                break
            try:
                if mode == "move":
                    try:
                        relative = os.path.relpath(path, source_root)
                        if relative.startswith(".."):
                            relative = os.path.basename(path)
                    except ValueError:
                        relative = os.path.basename(path)
                    dest = os.path.join(target, relative)
                    os.makedirs(os.path.dirname(dest) or target, exist_ok=True)
                    shutil.move(path, unique_path(dest))
                else:
                    remove_file(path, not permanent)
                done += 1
            except Exception as e:
                failed += 1
                self.ui(self._log,
                        _("FEHLER  {path}\n        {error}").format(path=path, error=e))
            self.ui(self.progress.configure, {"value": index})

        self.ui(self._action_done, mode, done, failed)

    def _action_done(self, mode, done, failed):
        verb = _("verschoben") if mode == "move" else _("gelöscht")
        self.candidates = [c for c in self.candidates if os.path.exists(c[0])]
        self._set_busy(False)
        summary = _("{done} {action}, {failed} fehlgeschlagen.").format(
            done=done, action=verb, failed=failed)
        self._log(_("Fertig: ") + summary)
        set_text(self.summary, summary)
        self.status(_("{done} Datei(en) {action}.").format(done=done, action=verb))
        messagebox.showinfo(
            _("Fertig"),
            _("{done} Datei(en) {action}.\n{failed} fehlgeschlagen.").format(
                done=done, action=verb, failed=failed))


# --------------------------------------------------------------------------
# Modul: Batch-Umbenennung
# --------------------------------------------------------------------------

class RenameModule(Module):
    key = "rename"
    icon = "\U0001F3F7"
    title = "Batch-Umbenennung"
    subtitle = "Alle Bilder eines Ordners nach einem Muster umbenennen"
    group = "Aufräumen"
    description = "Muster mit Zähler, Originalname, Datum und Bildgröße."

    PLACEHOLDERS = ("{counter}  fortlaufende Nummer (auch {counter:04d})   "
                    "{name}  bisheriger Name   {date}  Datum JJJJMMTT   "
                    "{w}/{h}  Breite/Höhe")

    def build(self):
        self.folder = tk.StringVar()
        self.pattern = tk.StringVar(value="image_{counter:04d}")
        self.start_number = tk.StringVar(value="1")
        self.lower_ext = tk.BooleanVar(value=True)
        self.plan = []

        card = make_card(self.body, fill="x")
        card_title(card, _("Ordner und Muster"))
        path_row(card, _("Ordner"), self.folder, self.pick_folder)

        pattern_row = Frame(card, bg=CARD)
        pattern_row.pack(fill="x", padx=14, pady=4)
        set_text(Label(pattern_row, font=FONT_SMALL, bg=CARD, fg=MUTED, width=16,
                       anchor="w"), _("Muster")).pack(side="left")
        entry = ttk.Entry(pattern_row, textvariable=self.pattern)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        entry.bind("<KeyRelease>", lambda _e: self.preview())
        set_text(Label(pattern_row, font=FONT_SMALL, bg=CARD, fg=MUTED),
                 _("Start bei")).pack(side="left", padx=(0, 4))
        start_entry = ttk.Entry(pattern_row, textvariable=self.start_number, width=6)
        start_entry.pack(side="left")
        start_entry.bind("<KeyRelease>", lambda _e: self.preview())

        set_text(Label(card, bg=CARD, fg=MUTED, font=FONT_TINY, anchor="w",
                       justify="left", wraplength=900),
                 _(self.PLACEHOLDERS)).pack(fill="x", padx=14, pady=(2, 4))

        actions = Frame(card, bg=CARD)
        actions.pack(fill="x", padx=14, pady=(4, 12))
        set_text(Checkbutton(actions, variable=self.lower_ext, command=self.preview,
                             bg=CARD, fg=TEXT, font=FONT_SMALL, activebackground=CARD,
                             selectcolor=CARD),
                 _("Endung klein schreiben")).pack(side="left")
        FlatButton(actions, _("Vorschau aktualisieren"), self.preview).pack(side="left", padx=10)
        self.run_btn = FlatButton(actions, _("Umbenennen"), self.rename, kind="primary",
                                  state="disabled")
        self.run_btn.pack(side="right")

        preview_card = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(preview_card, _("Vorschau"))
        self.summary = set_text(Label(preview_card, bg=CARD, fg=MUTED, font=FONT_SMALL,
                                      anchor="w"), _("Noch kein Ordner gewählt."))
        self.summary.pack(fill="x", padx=14, pady=(0, 6))

        wrap = Frame(preview_card, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.tree = ttk.Treeview(wrap, columns=("old", "new"), show="headings")
        set_heading(self.tree, "old", _("bisher"))
        set_heading(self.tree, "new", _("neu"))
        self.tree.column("old", width=340)
        self.tree.column("new", width=340)
        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

    def pick_folder(self):
        if self.ask_dir(_("Ordner auswählen"), self.folder):
            self.preview()

    # ---------------------------------------------------------------- Vorschau
    def preview(self):
        folder = self.folder.get().strip()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.plan = []
        self.run_btn.configure(state="disabled")

        if not folder or not os.path.isdir(folder):
            set_text(self.summary, _("Noch kein gültiger Ordner gewählt."), fg=MUTED)
            return

        pattern = self.pattern.get()
        try:
            counter = int(self.start_number.get())
        except ValueError:
            counter = 1

        needs_size = "{w}" in pattern or "{h}" in pattern
        files = sorted(iter_images(folder, recursive=False))
        today = datetime.now().strftime("%Y%m%d")
        used_names = set()
        conflicts = 0

        for path in files:
            base, ext = os.path.splitext(os.path.basename(path))
            if self.lower_ext.get():
                ext = ext.lower()
            width = height = 0
            if needs_size:
                width, height = image_size(path)
            try:
                new_base = pattern.format(counter=counter, name=base, date=today,
                                          w=width, h=height)
            except (KeyError, ValueError, IndexError) as e:
                set_text(self.summary, _("Muster ungültig: {error}").format(error=e),
                         fg=DANGER)
                return
            new_name = new_base + ext
            key = new_name.lower()
            if key in used_names:
                conflicts += 1
            used_names.add(key)
            self.plan.append((path, os.path.join(folder, new_name)))
            self.tree.insert("", "end", values=(os.path.basename(path), new_name))
            counter += 1

        if not self.plan:
            set_text(self.summary, _("Keine Bilddateien in diesem Ordner."), fg=MUTED)
            return
        if conflicts:
            set_text(self.summary,
                     _("{count} Dateien - ACHTUNG: {conflicts} doppelte Zielnamen. "
                       "Bitte {{counter}} im Muster verwenden.").format(
                         count=len(self.plan), conflicts=conflicts), fg=DANGER)
            return

        set_text(self.summary,
                 _("{count} Dateien werden umbenannt.").format(count=len(self.plan)), fg=OK)
        self.run_btn.configure(state="normal")

    # -------------------------------------------------------------- Ausführen
    def rename(self):
        if not self.plan:
            return
        if not messagebox.askyesno(
                _("Bestätigen"),
                _("{count} Datei(en) umbenennen?").format(count=len(self.plan))):
            return

        renamed, failed = 0, 0
        temporary = []
        # Phase 1: auf temporäre Namen, damit sich nichts gegenseitig blockiert
        for index, (source, dest) in enumerate(self.plan):
            try:
                tmp = os.path.join(os.path.dirname(source),
                                   f"__toolbox_tmp_{index}__{os.path.basename(source)}")
                os.rename(source, tmp)
                temporary.append((tmp, dest))
            except Exception as e:
                failed += 1
                logging.error(f"Umbenennen (Phase 1) {source}: {e}")
        # Phase 2: auf die Zielnamen
        for tmp, dest in temporary:
            try:
                os.rename(tmp, unique_path(dest))
                renamed += 1
            except Exception as e:
                failed += 1
                logging.error(f"Umbenennen (Phase 2) {tmp}: {e}")

        self.status(_("{done} Dateien umbenannt, {failed} fehlgeschlagen.").format(
            done=renamed, failed=failed))
        messagebox.showinfo(
            _("Fertig"),
            _("{done} Datei(en) umbenannt.\n{failed} fehlgeschlagen.").format(
                done=renamed, failed=failed))
        self.preview()


# --------------------------------------------------------------------------
# Modul: Statistiken
# --------------------------------------------------------------------------

class StatisticsModule(Module):
    key = "stats"
    icon = "\U0001F4CA"
    title = "Statistiken"
    subtitle = "Formate, Auflösungen und Größen eines Ordners auswerten"
    group = "Ansehen"
    description = "Überblick über Anzahl, Formate, Auflösungen und Dateigrößen."

    def build(self):
        self.folder = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)

        card = make_card(self.body, fill="x")
        card_title(card, _("Ordner analysieren"))
        path_row(card, _("Ordner"), self.folder,
                 lambda: self.ask_dir(_("Ordner analysieren"), self.folder))

        actions = Frame(card, bg=CARD)
        actions.pack(fill="x", padx=14, pady=(4, 12))
        set_text(Checkbutton(actions, variable=self.recursive, bg=CARD, fg=TEXT,
                             font=FONT_SMALL, activebackground=CARD, selectcolor=CARD),
                 _("Unterordner einbeziehen")).pack(side="left")
        self.run_btn = FlatButton(actions, _("Analyse starten"), self.start, kind="primary")
        self.run_btn.pack(side="left", padx=12)
        FlatButton(actions, _("Bericht speichern ..."), self.save_report).pack(side="left")
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.pack(side="right")

        result = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(result, _("Ergebnis"))
        wrap = Frame(result, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.text = Text(wrap, wrap="none", font=FONT_MONO, bg=CARD_ALT, fg=TEXT,
                         insertbackground=TEXT,
                         relief="flat", highlightbackground=BORDER, highlightthickness=1)
        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        remember_text((self.text, "content"), self._show_text,
                      _("Ordner wählen und Analyse starten."))

    def start(self):
        folder = self.folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror(_("Ordner"), _("Bitte einen gültigen Ordner wählen."))
            return
        if self.busy:
            return
        self.busy = True
        self.run_btn.configure(state="disabled")
        self.progress.start(12)
        self.status(_("Analysiere Ordner ..."))
        self.run_async(self._worker, folder, self.recursive.get())

    def _worker(self, folder, recursive):
        stats = {"files": 0, "bytes": 0, "formats": defaultdict(int),
                 "resolutions": defaultdict(int), "pixels": 0,
                 "largest": ("", 0), "smallest": ("", float("inf")),
                 "widest": ("", 0), "tallest": ("", 0)}

        for index, path in enumerate(iter_images(folder, recursive), 1):
            info = image_info(path)
            if not info:
                continue
            stats["files"] += 1
            stats["bytes"] += info["bytes"]
            stats["pixels"] += info["pixels"]
            stats["formats"][info["format"]] += 1
            stats["resolutions"][info["resolution"]] += 1
            name = os.path.basename(path)
            if info["bytes"] > stats["largest"][1]:
                stats["largest"] = (name, info["bytes"])
            if info["bytes"] < stats["smallest"][1]:
                stats["smallest"] = (name, info["bytes"])
            if info["width"] > stats["widest"][1]:
                stats["widest"] = (name, info["width"])
            if info["height"] > stats["tallest"][1]:
                stats["tallest"] = (name, info["height"])
            if index % 50 == 0:
                self.ui(self.status,
                        _("Analysiere ... {count} Bilder").format(count=index))

        self.ui(self._done, folder, stats)

    def _done(self, folder, stats):
        self.progress.stop()
        self.busy = False
        self.run_btn.configure(state="normal")
        # Als Funktion gemerkt: Nach einem Sprachwechsel entsteht der Bericht neu
        stamp = datetime.now()
        remember_text((self.text, "content"), self._show_text,
                      lambda: self._report(folder, stats, stamp))
        self.status(_("Analyse fertig: {count} Bilder.").format(
            count=stats["files"]))

    def _show_text(self, text):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", text)
        self.text.configure(state="disabled")

    @staticmethod
    def _report(folder, stats, stamp):
        """Der Analysebericht als Text, in der eingestellten Sprache."""
        line = "-" * 66
        out = [_("ORDNER-ANALYSE") + "   " + stamp.strftime(_("%d.%m.%Y %H:%M")),
               folder, line, ""]
        if stats["files"] == 0:
            out.append(_("Keine lesbaren Bilddateien gefunden."))
        else:
            average = stats["bytes"] / stats["files"]
            out += [_("ALLGEMEIN"), line,
                    _("  Bilddateien          : {value}").format(value=stats["files"]),
                    _("  Gesamtgröße          : {value}").format(
                        value=human_size(stats["bytes"])),
                    _("  Durchschnittsgröße   : {value}").format(
                        value=human_size(average)),
                    _("  Gesamtpixel          : {value} Megapixel").format(
                        value=f"{stats['pixels'] / 1_000_000:.1f}"),
                    "", _("FORMATE"), line]
            for fmt, count in sorted(stats["formats"].items(), key=lambda x: -x[1]):
                share = count / stats["files"] * 100
                out.append(f"  {fmt:<12} : {count:>6}  ({share:5.1f} %)")
            out += ["", _("AUFLÖSUNGEN (Top 15)"), line]
            for res, count in sorted(stats["resolutions"].items(),
                                     key=lambda x: -x[1])[:15]:
                out.append(f"  {res:<14} : " +
                           _("{count} Dateien").format(count=f"{count:>6}"))
            out += ["", _("EXTREMWERTE"), line,
                    _("  Größte Datei    : {name} ({size})").format(
                        name=stats["largest"][0], size=human_size(stats["largest"][1])),
                    _("  Kleinste Datei  : {name} ({size})").format(
                        name=stats["smallest"][0], size=human_size(stats["smallest"][1])),
                    _("  Breitestes Bild : {name} ({value} px)").format(
                        name=stats["widest"][0], value=stats["widest"][1]),
                    _("  Höchstes Bild   : {name} ({value} px)").format(
                        name=stats["tallest"][0], value=stats["tallest"][1]),
                    "", _("Analyse abgeschlossen.")]
        return "\n".join(out)

    def save_report(self):
        content = self.text.get("1.0", "end").strip()
        if not content:
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[(_("Textdatei"), "*.txt")],
                                            initialfile="bild-analyse.txt")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content + "\n")
            self.status(_("Bericht gespeichert: {path}").format(path=path))
        except OSError as e:
            messagebox.showerror(
                _("Fehler"),
                _("Konnte Bericht nicht speichern:\n{error}").format(error=e))


# --------------------------------------------------------------------------
# Modul: Format-Konverter
# --------------------------------------------------------------------------

class ConverterModule(Module):
    key = "convert"
    icon = "\U0001F504"
    title = "Format-Konverter"
    subtitle = "Einzelne Bilder oder ganze Ordner in ein anderes Format umwandeln"
    group = "Umwandeln"
    description = "JPEG, PNG, WebP, AVIF, BMP, GIF, TIFF, ICO und PPM - einzeln oder als Batch."

    SUPPORTED_FORMATS = {
        "JPEG": ["jpg", "jpeg"],
        "PNG": ["png"],
        "WebP": ["webp"],
        "AVIF": ["avif"],
        "BMP": ["bmp"],
        "GIF": ["gif"],
        "TIFF": ["tiff", "tif"],
        "ICO": ["ico"],
        "PPM": ["ppm"],
    }

    def build(self):
        self.files = []
        self.input_format = tk.StringVar(value="JPEG")
        self.output_format = tk.StringVar(value="PNG")
        self.quality = tk.IntVar(value=95)

        card = make_card(self.body, fill="x")
        card_title(card, _("Format"))
        row = Frame(card, bg=CARD)
        row.pack(fill="x", padx=14, pady=4)
        set_text(Label(row, font=FONT_SMALL, bg=CARD, fg=MUTED, width=16, anchor="w"),
                 _("Von")).pack(side="left")
        ttk.Combobox(row, textvariable=self.input_format,
                     values=list(self.SUPPORTED_FORMATS), state="readonly",
                     width=14).pack(side="left")
        set_text(Label(row, font=FONT_SMALL, bg=CARD, fg=MUTED),
                 _("nach")).pack(side="left", padx=10)
        ttk.Combobox(row, textvariable=self.output_format,
                     values=list(self.SUPPORTED_FORMATS), state="readonly",
                     width=14).pack(side="left")
        FlatButton(row, _("Einzelne Datei konvertieren ..."), self.convert_single,
                   kind="secondary").pack(side="right")

        quality_row = Frame(card, bg=CARD)
        quality_row.pack(fill="x", padx=14, pady=(4, 12))
        set_text(Label(quality_row, font=FONT_SMALL, bg=CARD, fg=MUTED, width=16,
                       anchor="w"), _("Qualität")).pack(side="left")
        scale = ttk.Scale(quality_row, from_=1, to=100, orient="horizontal", length=260)
        scale.pack(side="left")
        self.quality_label = Label(quality_row, text="95 %", bg=CARD, fg=TEXT,
                                   font=FONT_BOLD, width=6)
        self.quality_label.pack(side="left", padx=8)
        scale.set(95)                       # erst jetzt - Label muss existieren
        scale.configure(command=self._on_quality)
        set_text(Label(quality_row, bg=CARD, fg=MUTED, font=FONT_SMALL),
                 _("(wirkt bei JPEG, WebP und AVIF)")).pack(side="left")

        batch = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(batch, _("Batch-Konvertierung"))
        buttons = Frame(batch, bg=CARD)
        buttons.pack(fill="x", padx=14, pady=4)
        FlatButton(buttons, _("Dateien hinzufügen"), self.add_files).pack(side="left")
        FlatButton(buttons, _("Ordner hinzufügen"), self.add_folder).pack(side="left", padx=6)
        FlatButton(buttons, _("Auswahl entfernen"), self.remove_selected).pack(side="left")
        FlatButton(buttons, _("Liste leeren"), self.clear_list).pack(side="left", padx=6)
        self.run_btn = FlatButton(buttons, _("Batch konvertieren"), self.start_batch,
                                  kind="primary")
        self.run_btn.pack(side="right")

        wrap = Frame(batch, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=14, pady=(6, 6))
        self.listbox = Listbox(wrap, selectmode="extended", font=FONT_SMALL,
                               bg=CARD_ALT, fg=TEXT, selectbackground=ACCENT,
                               selectforeground=ON_ACCENT, relief="flat",
                               highlightbackground=BORDER,
                               highlightthickness=1, activestyle="none")
        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)

        self.progress = ttk.Progressbar(batch, mode="determinate")
        self.progress.pack(fill="x", padx=14, pady=(0, 4))
        self.summary = set_text(Label(batch, bg=CARD, fg=MUTED, font=FONT_SMALL,
                                      anchor="w"), _("Keine Dateien in der Liste."))
        self.summary.pack(fill="x", padx=14, pady=(0, 12))

    def _on_quality(self, value):
        percent = int(float(value))
        self.quality.set(percent)
        self.quality_label.configure(text=f"{percent} %")

    # ------------------------------------------------------------------ Liste
    def _filter_for(self, format_name):
        extensions = self.SUPPORTED_FORMATS.get(format_name, [])
        if not extensions:
            return (_("Alle Dateien"), "*.*")
        return (_("{format}-Dateien").format(format=format_name),
                " ".join(f"*.{ext}" for ext in extensions))

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title=_("Dateien auswählen"),
            filetypes=[self._filter_for(self.input_format.get()),
                       (_("Alle Dateien"), "*.*")])
        if paths:
            self.files.extend(paths)
            self.refresh_list()

    def add_folder(self):
        folder = filedialog.askdirectory(
            title=_("Ordner mit {format}-Dateien auswählen").format(
                format=self.input_format.get()))
        if not folder:
            return
        extensions = tuple("." + e for e in self.SUPPORTED_FORMATS[self.input_format.get()])
        found = list(iter_images(folder, recursive=False, extensions=extensions))
        if not found:
            messagebox.showinfo(_("Info"), _("Keine passenden Dateien in diesem Ordner."))
            return
        self.files.extend(found)
        self.refresh_list()

    def remove_selected(self):
        for index in sorted(self.listbox.curselection(), reverse=True):
            del self.files[index]
        self.refresh_list()

    def clear_list(self):
        self.files = []
        self.refresh_list()

    def refresh_list(self):
        self.listbox.delete(0, "end")
        for path in self.files:
            self.listbox.insert("end", os.path.basename(path))
        count = len(self.files)
        set_text(self.summary,
                 _("Keine Dateien in der Liste.") if not count
                 else _("{count} Datei(en) bereit für die Konvertierung.").format(count=count))

    # ------------------------------------------------------------ Konvertieren
    def convert_image(self, source, dest, output_format, quality):
        with Image.open(source) as image:
            if output_format in ("JPEG", "BMP", "PPM"):
                if image.mode in ("RGBA", "LA", "P"):
                    if image.mode == "P":
                        image = image.convert("RGBA")
                    background = Image.new("RGB", image.size, (255, 255, 255))
                    mask = image.split()[-1] if image.mode in ("RGBA", "LA") else None
                    background.paste(image, mask=mask)
                    image = background
                elif image.mode != "RGB":
                    image = image.convert("RGB")
            elif output_format == "ICO":
                image = image.convert("RGBA")
                if image.width > ICO_MAX or image.height > ICO_MAX:
                    image.thumbnail((ICO_MAX, ICO_MAX), Image.Resampling.LANCZOS)

            options = {}
            if output_format in ("JPEG", "WebP", "AVIF"):
                options["quality"] = quality
            elif output_format in ("PNG", "GIF"):
                options["optimize"] = True
            image.save(dest, output_format, **options)

    def convert_single(self):
        input_format = self.input_format.get()
        output_format = self.output_format.get()
        source = filedialog.askopenfilename(
            title=_("Datei auswählen"),
            filetypes=[self._filter_for(input_format),
                       (_("Alle Dateien"), "*.*")])
        if not source:
            return
        extension = self.SUPPORTED_FORMATS[output_format][0]
        dest = filedialog.asksaveasfilename(
            defaultextension=f".{extension}",
            initialfile=os.path.splitext(os.path.basename(source))[0] + f".{extension}",
            filetypes=[self._filter_for(output_format)])
        if not dest:
            return
        try:
            self.status(_("Konvertiere ..."))
            self.convert_image(source, dest, output_format, self.quality.get())
            self.status(_("Gespeichert: {path}").format(path=dest))
            messagebox.showinfo(_("Erfolg"),
                                _("Datei gespeichert:\n{path}").format(path=dest))
        except Exception as e:
            logging.error(f"Konvertierung {source}: {e}")
            self.status(_("Konvertierung fehlgeschlagen."))
            messagebox.showerror(
                _("Fehler"),
                _("Konvertierung fehlgeschlagen:\n{error}").format(error=e))

    def start_batch(self):
        if self.busy:
            return
        if not self.files:
            messagebox.showwarning(_("Warnung"), _("Keine Dateien ausgewählt!"))
            return
        target = filedialog.askdirectory(title=_("Ausgabeordner auswählen"))
        if not target:
            return

        self.busy = True
        self.run_btn.configure(state="disabled")
        self.progress.configure(maximum=len(self.files), value=0)
        self.run_async(self._batch_worker, list(self.files), target,
                       self.output_format.get(), self.quality.get())

    def _batch_worker(self, files, target, output_format, quality):
        extension = self.SUPPORTED_FORMATS[output_format][0]
        done, failed, errors = 0, 0, []

        for index, source in enumerate(files, 1):
            name = os.path.basename(source)
            self.ui(self.status, _("Konvertiere {done}/{total}: {name}").format(
                done=index, total=len(files), name=name))
            try:
                base = os.path.splitext(name)[0]
                dest = unique_path(os.path.join(target, f"{base}.{extension}"))
                self.convert_image(source, dest, output_format, quality)
                done += 1
            except Exception as e:
                failed += 1
                errors.append(f"{name}: {e}")
                logging.error(f"Batch-Konvertierung {source}: {e}")
            self.ui(self.progress.configure, {"value": index})

        self.ui(self._batch_done, done, failed, errors, target)

    def _batch_done(self, done, failed, errors, target):
        self.busy = False
        self.run_btn.configure(state="normal")
        self.progress.configure(value=0)
        set_text(self.summary,
                 _("{done} konvertiert, {failed} fehlgeschlagen -> {target}").format(
                     done=done, failed=failed, target=target))
        self.status(_("Batch fertig: {done} konvertiert, {failed} fehlgeschlagen.").format(
            done=done, failed=failed))
        message = _("{done} Datei(en) konvertiert nach:\n{target}").format(
            done=done, target=target)
        if errors:
            message += _("\n\nFehler:\n") + "\n".join(errors[:10])
            if len(errors) > 10:
                message += _("\n... und {count} weitere.").format(
                    count=len(errors) - 10)
            messagebox.showwarning(_("Teilweise fertig"), message)
        else:
            messagebox.showinfo(_("Erfolg"), message)


# --------------------------------------------------------------------------
# Modul: Icon-Extraktor
# --------------------------------------------------------------------------

class IconModule(Module):
    key = "icons"
    icon = "\U0001F5A5"
    title = "Icon-Extraktor"
    subtitle = "Icons aus EXE-, DLL- und Bilddateien auslesen und speichern"
    group = "Umwandeln"
    description = "Alle Icon-Größen aus Programmdateien holen und als ICO oder PNG sichern."

    def build(self):
        self.source = tk.StringVar()
        self.output = tk.StringVar()
        self.save_format = tk.StringVar(value="ICO")
        self.icons = []
        self._photo_refs = []
        self._last_error = ""

        card = make_card(self.body, fill="x")
        card_title(card, _("Quelle und Ziel"))
        path_row(card, _("Quell-Datei"), self.source, self.pick_source)
        path_row(card, _("Ausgabe-Ordner"), self.output,
                 lambda: self.ask_dir(_("Zielordner auswählen"), self.output))

        set_text(Label(card, bg=CARD, fg=MUTED, font=FONT_TINY, anchor="w"),
                 _("Unterstützt: .exe, .dll, .sys, .ocx, .cpl, .scr sowie "
                   ".ico, .png, .jpg, .bmp, .tif ...")).pack(fill="x", padx=14)

        actions = Frame(card, bg=CARD)
        actions.pack(fill="x", padx=14, pady=(8, 12))
        FlatButton(actions, _("Vorschau laden"), self.load_preview,
                   kind="primary").pack(side="left")
        FlatButton(actions, _("Alle speichern"), self.save_icons,
                   kind="success").pack(side="left", padx=6)
        FlatButton(actions, _("Zurücksetzen"), self.reset).pack(side="left")
        set_text(Label(actions, bg=CARD, fg=MUTED, font=FONT_SMALL),
                 _("Speichern als")).pack(side="left", padx=(20, 6))
        ttk.Combobox(actions, textvariable=self.save_format, values=["ICO", "PNG"],
                     state="readonly", width=8).pack(side="left")

        self.progress = ttk.Progressbar(card, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=14, pady=(0, 12))

        preview = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(preview, _("Icon-Vorschau"))
        self.summary = set_text(Label(preview, bg=CARD, fg=MUTED, font=FONT_SMALL,
                                      anchor="w"), _("Noch nichts geladen."))
        self.summary.pack(fill="x", padx=14, pady=(0, 6))

        wrap = Frame(preview, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        yscroll = ttk.Scrollbar(wrap, orient="vertical")
        yscroll.pack(side="right", fill="y")
        self.canvas = Canvas(wrap, bg=CARD_ALT, highlightbackground=BORDER,
                             highlightthickness=1, yscrollcommand=yscroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        yscroll.configure(command=self.canvas.yview)
        self.grid_frame = Frame(self.canvas, bg=CARD_ALT)
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))

        if not HAS_ICOEXTRACT:
            set_text(Label(preview, bg=CARD, fg=WARN, font=FONT_SMALL, anchor="w"),
                     _("Hinweis: Modul 'icoextract' fehlt - Icons aus EXE/DLL "
                       "können nicht gelesen werden.  pip install icoextract")).pack(
                fill="x", padx=14, pady=(0, 10))

    def pick_source(self):
        path = filedialog.askopenfilename(title=_("Quelldatei auswählen"),
                                          filetypes=[(_("Alle Dateien"), "*.*")])
        if path:
            self.source.set(path)
            if not self.output.get():
                self.output.set(os.path.dirname(path))

    # ---------------------------------------------------------- Extraktion
    def _from_exe(self, path):
        if not HAS_ICOEXTRACT:
            self._last_error = _("Modul 'icoextract' nicht installiert "
                                 "(pip install icoextract).")
            return []
        icons = []
        try:
            extractor = IconExtractor(path)
            groups = extractor.list_group_icons()
            for index in range(len(groups)):
                try:
                    data = extractor.get_icon(num=index)
                    with Image.open(data) as im:
                        icons.extend(iter_frames(im))
                except Exception as e:
                    self._last_error = _("Gruppe {index}: {error}").format(
                        index=index, error=e)
        except IconExtractorError as e:
            self._last_error = f"icoextract: {e}"
        except Exception as e:
            self._last_error = str(e)
        return icons

    def _from_image(self, path):
        try:
            with Image.open(path) as im:
                return list(iter_frames(im))
        except Exception as e:
            self._last_error = str(e)
            return []

    def load_preview(self):
        source = self.source.get().strip()
        if not source:
            messagebox.showwarning(_("Fehler"), _("Bitte Quelldatei auswählen!"))
            return
        if not os.path.isfile(source):
            messagebox.showerror(_("Fehler"), _("Quelldatei existiert nicht!"))
            return

        self.status(_("Lade Icons ..."))
        self._last_error = ""
        if source.lower().endswith(EXE_EXTENSIONS):
            self.icons = self._from_exe(source)
            if not self.icons:
                self.icons = self._from_image(source)
        else:
            self.icons = self._from_image(source)

        if self.icons:
            self.render_preview()
            set_text(self.summary,
                     _("{count} Icons geladen - 'Alle speichern' zum Sichern.").format(
                         count=len(self.icons)), fg=OK)
            self.status(_("{count} Icons geladen.").format(count=len(self.icons)))
        else:
            message = _("Keine Icons in dieser Datei gefunden!")
            if self._last_error:
                message += _("\n\nDetails: {error}").format(error=self._last_error)
            set_text(self.summary, _("Keine Icons gefunden."), fg=DANGER)
            self.status(_("Keine Icons gefunden."))
            messagebox.showwarning(_("Fehler"), message)

    def render_preview(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        self._photo_refs.clear()

        for index, icon in enumerate(self.icons):
            try:
                thumb = icon.convert("RGBA")
                thumb.thumbnail((64, 64), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(thumb)
                self._photo_refs.append(photo)

                cell = Frame(self.grid_frame, bg=CARD, highlightbackground=BORDER,
                             highlightthickness=1)
                cell.grid(row=index // 8, column=index % 8, padx=6, pady=6)
                Label(cell, image=photo, bg=CARD, width=70, height=70).pack()
                Label(cell, text=f"{icon.width}x{icon.height}", bg=CARD, fg=MUTED,
                      font=FONT_TINY).pack(pady=(0, 4))
            except Exception as e:
                self._last_error = str(e)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def save_icons(self):
        output = self.output.get().strip()
        if not output:
            messagebox.showwarning(_("Fehler"), _("Bitte Zielordner angeben!"))
            return
        if not os.path.isdir(output):
            messagebox.showerror(_("Fehler"), _("Zielordner existiert nicht!"))
            return
        if not self.icons:
            messagebox.showwarning(_("Fehler"), _("Bitte erst die Vorschau laden!"))
            return

        fmt = self.save_format.get()
        extension = ".ico" if fmt == "ICO" else ".png"
        saved, total, errors = 0, len(self.icons), []
        self.progress.configure(value=0)

        for index, icon in enumerate(self.icons):
            try:
                image = icon.convert("RGBA")
                if fmt == "ICO" and (image.width > ICO_MAX or image.height > ICO_MAX):
                    image.thumbnail((ICO_MAX, ICO_MAX), Image.Resampling.LANCZOS)
                name = f"icon_{index + 1}_{icon.width}x{icon.height}{extension}"
                image.save(unique_path(os.path.join(output, name)), format=fmt)
                saved += 1
            except Exception as e:
                errors.append(f"#{index + 1}: {e}")
            self.progress.configure(value=int((index + 1) / total * 100))
            self.root.update_idletasks()

        self.progress.configure(value=0)
        saved_text = _("{done}/{total} Icons gespeichert.").format(done=saved, total=total)
        set_text(self.summary, saved_text, fg=OK)
        self.status(saved_text)
        message = _("{done} von {total} Icons gespeichert in:\n{folder}").format(
            done=saved, total=total, folder=output)
        if errors:
            message += _("\n\nFehler:\n") + "\n".join(errors[:10])
            messagebox.showwarning(_("Teilweise fertig"), message)
        else:
            messagebox.showinfo(_("Erfolg"), message)

    def reset(self):
        self.source.set("")
        self.output.set("")
        self.icons = []
        self._photo_refs.clear()
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        self.progress.configure(value=0)
        set_text(self.summary, _("Noch nichts geladen."), fg=MUTED)
        self.status(_("Bereit"))


# --------------------------------------------------------------------------
# Modul: Info & Hilfe
# --------------------------------------------------------------------------

class InfoModule(Module):
    key = "info"
    icon = "ℹ"
    title = "Info & Hilfe"
    subtitle = "Module, Abhängigkeiten und Lizenz"
    group = "Info"
    description = "Kurzbeschreibung aller Module und Status der Zusatzbibliotheken."

    def build(self):
        # In der kleinsten Fenstergroesse ist die Seite hoeher als der Platz
        # darunter. Sie rollt deshalb als Ganzes - frueher wurde der Text unter
        # "Ueber dieses Programm" unten einfach abgeschnitten.
        area = ScrollArea(self.body, bg=BG)
        area.pack(fill="both", expand=True)
        page = area.inner

        help_card = make_card(page, fill="x")
        card_title(help_card, _("Die Module im Überblick"))
        for cls in self.app.module_classes:
            if cls.key in ("home", "info"):
                continue
            row = Frame(help_card, bg=CARD)
            row.pack(fill="x", padx=14, pady=3)
            Label(row, text=cls.icon, bg=CARD, fg=ACCENT,
                  font=("Segoe UI Emoji", 11), width=3).pack(side="left")
            set_text(Label(row, bg=CARD, fg=TEXT, font=FONT_BOLD, width=20, anchor="w"),
                     _(cls.title)).pack(side="left")
            set_text(Label(row, bg=CARD, fg=MUTED, font=FONT_SMALL, anchor="w",
                           justify="left"),
                     _(cls.description)).pack(side="left", fill="x", expand=True)
        Frame(help_card, bg=CARD, height=8).pack()

        deps_card = make_card(page, fill="x", pady=(10, 0))
        card_title(deps_card, _("Bibliotheken"))
        for name, installed, purpose, command in self.app.dependency_table():
            row = Frame(deps_card, bg=CARD)
            row.pack(fill="x", padx=14, pady=3)
            Label(row, text="●", bg=CARD, fg=OK if installed else WARN,
                  font=FONT_SMALL, width=3).pack(side="left")
            Label(row, text=name, bg=CARD, fg=TEXT, font=FONT_BOLD, width=20,
                  anchor="w").pack(side="left")
            set_text(Label(row, bg=CARD, fg=MUTED, font=FONT_SMALL, anchor="w"),
                     purpose).pack(side="left", fill="x", expand=True)
            set_text(Label(row, bg=CARD, fg=OK if installed else WARN, font=FONT_SMALL),
                     _("installiert") if installed else command).pack(side="right")
        Frame(deps_card, bg=CARD, height=8).pack()

        about_card = make_card(page, fill="both", expand=True, pady=(10, 0))
        card_title(about_card, _("Über dieses Programm"))
        about = (f"{APP_NAME} {APP_VERSION}\n\n" +
                 _("Vereint die früheren Einzelprogramme Bildbetrachter Pro 2.0, "
                   "Icon Extraktor, Universal Image Converter und Bild-Dimensions-Filter "
                   "in einer Oberfläche.\n\n"
                   "Tastatur: Strg+1 bis Strg+9 wechseln direkt zwischen den Modulen, "
                   "Esc springt zurück zum Start.") +
                 "\n\nLicensed under MIT License\n"
                 "Copyright 2026 Alexander Unverhau\n"
                 "Created with assistance of Claude AI")
        set_text(Label(about_card, bg=CARD, fg=TEXT, font=FONT_SMALL, justify="left",
                       anchor="nw", wraplength=900), about).pack(
            fill="both", expand=True, padx=14, pady=(0, 14))
        area.bind_wheel()


# --------------------------------------------------------------------------
# Hauptfenster
# --------------------------------------------------------------------------

class ToolboxApp:
    module_classes = [HomeModule, CompareModule, StatisticsModule, DuplicateModule,
                      SimilarModule, DimensionModule, RenameModule, ConverterModule,
                      IconModule, InfoModule]

    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        # Unsichtbar aufbauen - gezeigt wird erst, wenn Groesse und Lage feststehen
        self.root.withdraw()

        self.pages = {}          # key -> (page_frame, module_instance oder None)
        self.nav_buttons = {}
        self.current = None
        self.event_queue = queue.Queue()
        self._pump_job = None
        self._window = None          # aktuelle normale Lage, siehe _remember_window
        self._window_saved = None    # zuletzt in die Einstellungen geschrieben
        self._window_job = None

        # Sprache und Farbschema stehen fest, bevor das erste Widget entsteht
        _.language = startup_language()
        apply_theme(startup_theme())
        self.root.configure(bg=BG)

        self._setup_style()
        self._build_layout()
        self.show("home")
        self._place_window()
        self._bind_keys()
        self._pump()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------------ Style
    def _setup_style(self):
        style = ttk.Style()
        try:
            # Nur einmal: theme_use laesst alle ttk-Widgets ihr Aussehen neu berechnen
            if style.theme_use() != "clam":
                style.theme_use("clam")
        except tk.TclError:
            pass
        for widget in ("TEntry", "TCombobox", "TSpinbox"):
            # lightcolor/darkcolor sind die 3D-Kanten des clam-Themes - ohne
            # sie zeichnet Tk im dunklen Schema weisse Raender um die Felder
            style.configure(widget, fieldbackground=FIELD_BG, foreground=TEXT,
                            background=BTN_BG, bordercolor=BORDER,
                            lightcolor=BORDER, darkcolor=BORDER,
                            arrowcolor=TEXT, insertcolor=TEXT, padding=3)
            style.map(widget,
                      fieldbackground=[("readonly", FIELD_BG),
                                       ("disabled", BG)],
                      background=[("readonly", BTN_BG), ("active", BTN_HOVER)],
                      foreground=[("readonly", TEXT), ("disabled", BTN_DISABLED)],
                      bordercolor=[("focus", ACCENT)],
                      lightcolor=[("focus", ACCENT)],
                      darkcolor=[("focus", ACCENT)])
        # Klappliste der Auswahlfelder ist ein klassisches Listenfeld. option_add
        # wirkt nur auf neu angelegte; schon angelegte faerbt refresh_colors() nach.
        for option, color in listbox_colors().items():
            self.root.option_add(f"*TCombobox*Listbox.{option}", color)
        style.configure("TProgressbar", background=ACCENT, troughcolor=TROUGH,
                        bordercolor=TROUGH, lightcolor=ACCENT, darkcolor=ACCENT,
                        thickness=8)
        style.configure("TScrollbar", background=BTN_BG, troughcolor=TROUGH,
                        bordercolor=BORDER, arrowcolor=MUTED)
        style.map("TScrollbar", background=[("active", BTN_HOVER)])
        style.configure("Treeview", background=CARD, fieldbackground=CARD,
                        foreground=TEXT, rowheight=44, font=FONT_SMALL,
                        bordercolor=BORDER)
        style.configure("Treeview.Heading", font=FONT_SMALL, background=HEAD_BG,
                        foreground=MUTED, relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", ON_ACCENT)])
        # Schieberegler: Griff in Akzentfarbe, Rille wie beim Fortschritt
        style.configure("TScale", background=ACCENT, troughcolor=TROUGH,
                        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("TScale", background=[("active", ACCENT_DARK)])

    # ----------------------------------------------------------------- Layout
    def _build_layout(self):
        outer = self.outer = Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)

        # --- Sidebar ---
        sidebar = self.sidebar = Frame(outer, bg=SIDEBAR, width=250)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand = Frame(sidebar, bg=SIDEBAR)
        brand.pack(fill="x", pady=(14, 8), padx=16)
        Label(brand, text=APP_NAME, bg=SIDEBAR, fg=SIDEBAR_TITLE,
              font=("Segoe UI", 15, "bold"), anchor="w").pack(fill="x")
        set_text(Label(brand, bg=SIDEBAR, fg=SIDEBAR_GROUP, font=FONT_TINY, anchor="w"),
                 _("Version {version}").format(version=APP_VERSION)).pack(fill="x")

        # Fusszeile und Sprachauswahl zuerst packen - so bleiben sie auch bei
        # kleiner Fensterhoehe sichtbar und die Navigation weicht darueber aus.
        footer = set_text(Label(sidebar, bg=SIDEBAR, fg=SIDEBAR_GROUP, font=FONT_TINY,
                                justify="left"),
                          _("MIT License\nCopyright 2026\nAlexander Unverhau\n"
                            "mit Unterstützung von Claude AI"))
        footer.pack(side="bottom", anchor="w", padx=18, pady=(6, 12))

        lang_frame = Frame(sidebar, bg=SIDEBAR)
        set_text(Label(lang_frame, bg=SIDEBAR, fg=SIDEBAR_GROUP,
                       font=("Segoe UI", 8, "bold"), anchor="w"),
                 _("Sprache & Darstellung")).pack(fill="x")
        row = Frame(lang_frame, bg=SIDEBAR)
        row.pack(fill="x", pady=(3, 0))

        self.language_names = _.available()
        self.language_box = ttk.Combobox(
            row, state="readonly", font=FONT_SMALL,
            values=list(self.language_names.values()))
        self.language_box.set(self.language_names[_.language])
        self.language_box.pack(side="left", fill="x", expand=True)
        self.language_box.bind("<<ComboboxSelected>>", self._on_language_selected)

        self.dark_var = tk.BooleanVar(value=CURRENT_THEME == "dark")
        set_text(Checkbutton(row, variable=self.dark_var,
                             command=self._on_theme_toggled, bg=SIDEBAR, fg=SIDEBAR_TEXT,
                             activebackground=SIDEBAR, activeforeground=SIDEBAR_TITLE,
                             selectcolor=SIDEBAR_HOVER, font=FONT_SMALL,
                             highlightthickness=0, bd=0, cursor="hand2"),
                 _("Dunkel")).pack(side="right", padx=(6, 0))

        lang_frame.pack(side="bottom", fill="x", padx=18, pady=(0, 4))

        current_group = None
        for cls in self.module_classes:
            if cls.group and cls.group != current_group:
                current_group = cls.group
                heading = Label(sidebar, bg=SIDEBAR, fg=SIDEBAR_GROUP,
                                font=("Segoe UI", 8, "bold"), anchor="w")
                heading.pack(fill="x", padx=18, pady=(9, 2))
                # .upper() machte aus dem Translated einen gewoehnlichen String -
                # die Grossschreibung gehoert deshalb in die Setzfunktion
                remember_text((heading, "text"),
                              lambda value, label=heading: label.configure(text=value.upper()),
                              _(cls.group))
            button = NavButton(sidebar, cls.icon, _(cls.title),
                               lambda key=cls.key: self.show(key))
            button.pack(fill="x")
            self.nav_buttons[cls.key] = button

        # --- Inhalt ---
        right = self.right = Frame(outer, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        header = Frame(right, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 8))
        self.header_title = Label(header, text="", bg=BG, fg=TEXT, font=FONT_H1,
                                  anchor="w")
        self.header_title.pack(fill="x")
        self.header_subtitle = Label(header, text="", bg=BG, fg=MUTED, font=FONT_SMALL,
                                     anchor="w", justify="left")
        self.header_subtitle.pack(fill="x", pady=(2, 0))

        self.content = Frame(right, bg=BG)
        self.content.pack(fill="both", expand=True, padx=24, pady=(6, 12))

        # --- Statusleiste ---
        status_bar = self.status_bar = Frame(self.root, bg=STATUS_BG, height=26)
        # Vor dem Inhaltsbereich packen: Wer zuerst gepackt wird, bekommt
        # zuerst Platz. Verlangt ein Reiter mehr Hoehe, als das Fenster hat,
        # draengte er sonst die Statusleiste hinaus und zog die Seitenleiste
        # mit in die Laenge.
        status_bar.pack(side="bottom", fill="x", before=outer)
        self.status_var = tk.StringVar()
        self.set_status(_("Bereit"))
        Label(status_bar, textvariable=self.status_var, bg=STATUS_BG, fg=MUTED,
              font=FONT_SMALL, anchor="w").pack(side="left", padx=14, pady=3)
        set_text(Label(status_bar, bg=STATUS_BG, fg=OK if HAS_TRASH else WARN,
                       font=FONT_TINY, anchor="e"),
                 _("Papierkorb aktiv") if HAS_TRASH
                 else _("ohne Papierkorb (send2trash fehlt)")).pack(side="right", padx=14)

    def _pump(self):
        """Aufträge der Hintergrundthreads im Hauptthread abarbeiten."""
        while True:
            try:
                func, args = self.event_queue.get_nowait()
            except queue.Empty:
                break
            try:
                func(*args)
            except Exception as e:
                logging.error(f"UI-Aktualisierung fehlgeschlagen: {e}\n"
                              f"{traceback.format_exc()}")
        try:
            self._pump_job = self.root.after(50, self._pump)
        except tk.TclError:                  # Fenster wird gerade geschlossen
            self._pump_job = None

    def close(self):
        """Fenster schliessen und die Warteschlange sauber anhalten."""
        for job in (self._pump_job, self._window_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        self._pump_job = self._window_job = None
        self._remember_window()
        self.root.destroy()

    def _bind_keys(self):
        for index, cls in enumerate(self.module_classes[:9], 1):
            self.root.bind(f"<Control-Key-{index}>",
                           lambda _e, key=cls.key: self.show(key))
        self.root.bind("<Escape>", lambda _e: self.show("home"))

    # ------------------------------------------------ Fenstergroesse und -lage
    def _natural_size(self):
        """Kleinste Fenstergroesse, in der Navigation und Startseite ganz passen.

        Gemessen wird der tatsaechliche Platzbedarf statt einer festen Zahl:
        Bringt ein Update weitere Module in die Navigation, waechst das Fenster
        von selbst mit, und andere Schriften oder Bildschirmskalierungen sind
        gleich beruecksichtigt.
        """
        previous = self.current
        # Der Abstecher auf die Startseite laesst die Statuszeile stehen
        if previous != "home":
            self.show("home", reset_status=False)
        self.root.update_idletasks()
        sidebar_width = self.sidebar.winfo_reqwidth()
        # Die Seitenleiste gibt ihre Hoehe sonst nicht nach oben weiter
        self.sidebar.pack_propagate(True)
        self.root.update_idletasks()
        sidebar_height = self.sidebar.winfo_reqheight()
        self.sidebar.pack_propagate(False)
        # Ohne das behielte die Seitenleiste die Breite ihres Inhalts - je nach
        # Sprache 236 oder 249 statt 250 px -, und jede weitere Messung fiele
        # zu breit aus. Das erneute Setzen fordert die feste Breite wieder an.
        self.sidebar.configure(width=self.sidebar.cget("width"))
        width = sidebar_width + self.right.winfo_reqwidth()
        height = (max(sidebar_height, self.right.winfo_reqheight())
                  + self.status_bar.winfo_reqheight())
        if previous and previous != "home":
            self.show(previous, reset_status=False)
        return width, height

    def _place_window(self):
        """Fenster in der gemerkten oder in der kleinsten Groesse zeigen."""
        saved = window_from_config(load_config())
        width, height, x, y, min_width, min_height = window_placement(
            self._natural_size(), work_area(self.root), saved,
            lambda px, py: point_on_screen(self.root, px, py))
        self.root.minsize(min_width, min_height)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        maximized = bool(saved and saved["maximized"])
        self._window = {"x": x, "y": y, "width": width, "height": height,
                        "maximized": maximized}
        # Geschrieben wird erst, wenn der Nutzer Groesse oder Lage aendert -
        # eine nur berechnete Startlage gehoert nicht in die Einstellungen
        self._window_saved = dict(self._window)

        self.root.deiconify()
        if maximized:
            try:
                self.root.state("zoomed")                  # Windows, macOS
            except tk.TclError:
                try:
                    self.root.attributes("-zoomed", True)  # Linux
                except tk.TclError:
                    pass
        self.root.bind("<Configure>", self._on_root_configure, add="+")

    def _update_minsize(self):
        """Mindestgroesse nachziehen - eine andere Sprache hat andere Textbreiten."""
        placement = window_placement(self._natural_size(), work_area(self.root))
        self.root.minsize(*placement[4:])

    def _on_root_configure(self, event):
        # Das Hauptfenster bekommt auch die Ereignisse aller Kind-Widgets
        if event.widget is not self.root:
            return
        # Erst merken, wenn das Ziehen vorbei ist, nicht bei jedem Zwischenschritt
        if self._window_job is not None:
            self.root.after_cancel(self._window_job)
        self._window_job = self.root.after(500, self._remember_window)

    def _remember_window(self):
        """Groesse und Lage in die Einstellungen schreiben, wenn sie sich geaendert haben."""
        self._window_job = None
        if self._window is None:
            return
        try:
            state = self.root.state()
            geometry = parse_geometry(self.root.geometry())
        except tk.TclError:
            return
        if state == "zoomed":
            # Maximiert meldet Tk die Bildschirmgroesse. Gemerkt bleibt die
            # normale Lage, in die das Fenster beim Wiederherstellen zurueckkehrt.
            self._window["maximized"] = True
        elif state == "normal" and geometry:
            self._window.update(geometry, maximized=False)
        else:                                          # minimiert
            return
        if self._window != self._window_saved:
            settings = load_config()
            settings["window"] = dict(self._window)
            if save_config(settings):
                self._window_saved = dict(self._window)

    # ------------------------------------------------------------ Navigation
    def show(self, key, reset_status=True):
        """Seite eines Moduls zeigen und sie dafuer bei Bedarf erst bauen.

        reset_status=False laesst die Statuszeile stehen - fuer den kurzen
        Abstecher auf die Startseite, mit dem _natural_size() misst.
        """
        cls = next((c for c in self.module_classes if c.key == key), None)
        if cls is None:
            return
        if self.current == key:
            return

        if self.current and self.current in self.pages:
            self.pages[self.current][0].pack_forget()

        if key not in self.pages:
            page = Frame(self.content, bg=BG)
            module = cls(self, page)
            self.pages[key] = (page, module)
        page, _module = self.pages[key]
        page.pack(fill="both", expand=True)

        set_text(self.header_title, cls.icon + "   " + _(cls.title))
        set_text(self.header_subtitle, _(cls.subtitle))
        for nav_key, button in self.nav_buttons.items():
            button.set_active(nav_key == key)
        self.current = key
        if reset_status:
            self.set_status(_("Bereit"))

    # ------------------------------------------- Sprache und Farbschema
    def _busy(self):
        """Laeuft gerade ein Scan oder eine Umwandlung?

        Solange, wird nicht umgeschaltet. Bis 1.0.4 haette ein Wechsel die
        Oberflaeche unter dem laufenden Vorgang abgerissen; das passiert nicht
        mehr, die Sperre bleibt aber als Vorsichtsmassnahme.
        """
        return any(module.busy for _page, module in self.pages.values() if module)

    def _switch(self, refresh):
        """Sprache oder Farbschema umstellen, ohne die Oberflaeche neu zu bauen.

        Bis 1.0.4 wurde dafuer alles abgerissen und neu aufgebaut. Man sah
        rund eine Viertelsekunde lang jeden Zwischenstand, und die Inhalte
        aller Module gingen verloren - etwa das Ergebnis einer langen
        Dublettensuche. Jetzt tauscht refresh() nur Texte bzw. Farben aus,
        waehrend das Zeichnen ruht (siehe pause_drawing).
        """
        resume = pause_drawing(self.root.winfo_id())
        try:
            refresh()
            self.root.update_idletasks()
        finally:
            resume()

    def _refresh_colors(self):
        """Alle Farben auf das eingestellte Schema umstellen - ohne Neuaufbau.

        Wie bei den Texten bleiben Widgets, Modulinhalte und Eingaben stehen;
        nur die Farben werden ausgetauscht (siehe Themed).
        """
        self.root.configure(bg=BG)
        self._setup_style()
        refresh_colors(self.root)
        for _page, module in self.pages.values():
            module.repaint()
        self.dark_var.set(CURRENT_THEME == "dark")

    def _refresh_texts(self):
        """Alle Beschriftungen in die eingestellte Sprache bringen - ohne Neuaufbau.

        Widgets, Modulinhalte und Eingaben bleiben stehen; nur die Texte
        werden ausgetauscht (siehe set_text).
        """
        refresh_texts()
        self.language_box.set(self.language_names[_.language])
        self._update_minsize()

    def _on_language_selected(self, _event=None):
        chosen = self.language_box.get()
        for code, name in self.language_names.items():
            if name == chosen:
                self.set_language(code)
                return

    def set_language(self, code):
        """Sprache umstellen - die Texte werden an Ort und Stelle ausgetauscht."""
        if code == _.language:
            return
        if self._busy():
            messagebox.showinfo(
                _("Sprache"),
                _("Bitte warten, bis der laufende Vorgang beendet ist."))
            self.language_box.set(self.language_names[_.language])
            return

        _.language = code
        settings = load_config()
        settings["language"] = code
        save_config(settings)
        self._switch(self._refresh_texts)

    def _on_theme_toggled(self):
        self.set_theme("dark" if self.dark_var.get() else "light")

    def set_theme(self, name):
        """Zwischen hellem und dunklem Schema wechseln."""
        if name == CURRENT_THEME:
            return
        if self._busy():
            messagebox.showinfo(
                _("Darstellung"),
                _("Bitte warten, bis der laufende Vorgang beendet ist."))
            self.dark_var.set(CURRENT_THEME == "dark")
            return

        apply_theme(name)
        settings = load_config()
        settings["theme"] = CURRENT_THEME
        save_config(settings)
        self._switch(self._refresh_colors)

    def module(self, key):
        """Modul-Instanz holen (baut die Seite bei Bedarf auf)."""
        if key not in self.pages:
            previous = self.current
            self.show(key)
            if previous and previous != key:
                self.show(previous)
        return self.pages[key][1]

    def send_to_compare(self, path, side):
        """Bild aus einer Trefferliste in den Split-Screen laden."""
        compare = self.module("compare")
        compare.load(side, path)
        self.show("compare")

    def set_status(self, text):
        remember_text((self, "status"), self.status_var.set, text)

    # ---------------------------------------------------------- Abhängigkeiten
    @staticmethod
    def dependency_table():
        return [
            ("Pillow", HAS_PIL, _("Bilder lesen, schreiben und skalieren (Pflicht)"),
             "pip install Pillow"),
            ("send2trash", HAS_TRASH, _("Löschen in den Papierkorb statt endgültig"),
             "pip install send2trash"),
            ("icoextract", HAS_ICOEXTRACT, _("Icons aus EXE- und DLL-Dateien lesen"),
             "pip install icoextract"),
            ("pillow-heif", HAS_HEIF, _("HEIC- und HEIF-Dateien öffnen"),
             "pip install pillow-heif"),
        ]

    def missing_dependencies(self):
        return [name for name, installed, _p, _c in self.dependency_table()
                if not installed]


# --------------------------------------------------------------------------
# SPRACHTABELLE / LANGUAGE TABLE
#
# Quellsprache ist Deutsch - der deutsche Text im Code ist zugleich der
# Schluessel. Eine weitere Sprache kommt in drei Schritten dazu:
#   1. Kuerzel und Anzeigename in LANGUAGE_NAMES eintragen,
#      z. B.  "fr": "Francais"
#   2. In TRANSLATIONS einen Eintrag "fr": { ... } anlegen und die
#      gewuenschten Zeilen uebersetzen.
#   3. Fertig - die Auswahl in der Seitenleiste zeigt die Sprache sofort an.
#
# Nicht uebersetzte Zeilen erscheinen automatisch auf Deutsch, eine
# unvollstaendige Tabelle ist also unproblematisch. Platzhalter in
# geschweiften Klammern - {count}, {path}, {error} ... - muessen in der
# Uebersetzung unveraendert vorkommen; ihre Reihenfolge im Satz ist frei.
# --------------------------------------------------------------------------

LANGUAGE_NAMES = {
    "de": "Deutsch",
    "en": "English",
}

TRANSLATIONS = {
    "en": {
        # --- Rahmen, Navigation, allgemeine Begriffe ----------------------
        "Start": "Home",
        "Seiten getauscht.": "Sides swapped.",
        "Ansehen": "View",
        "Aufräumen": "Clean up",
        "Umwandeln": "Convert",
        "Info": "Info",
        "Sprache": "Language",
        "Sprache & Darstellung": "Language & appearance",
        "Darstellung": "Appearance",
        "Dunkel": "Dark",
        "Version {version}": "Version {version}",
        "Bereit": "Ready",
        "Fertig": "Done",
        "Fertig: ": "Done: ",
        "Fehler": "Error",
        "Warnung": "Warning",
        "Achtung": "Warning",
        "Erfolg": "Success",
        "Ungültig": "Invalid",
        "Bestätigen": "Confirm",
        "Teilweise fertig": "Partly finished",
        "Abbrechen": "Cancel",
        "Abbruch angefordert ...": "Cancelling ...",
        "Abgebrochen - ": "Cancelled - ",
        "Durchsuchen ...": "Browse ...",
        "Öffnen": "Open",
        "Löschen": "Delete",
        "Umbenennen": "Rename",
        "Scannen": "Scan",
        "Ausführen": "Run",
        "Vorschau": "Preview",
        "Muster": "Pattern",
        "Ordner": "Folder",
        "Datei": "File",
        "Treffer": "Match",
        "Unbekannt": "Unknown",
        "Format": "Format",
        "Auflösung": "Resolution",
        "Größe": "Size",
        "Qualität": "Quality",
        "Von": "From",
        "nach": "to",
        "bisher": "current",
        "neu": "new",
        "max.:": "max.:",
        "Pixel min.:": "Pixels min.:",
        "Suche": "Search",
        "Protokoll": "Log",
        "Ergebnis": "Result",
        "Bibliotheken": "Libraries",
        "installiert": "installed",
        "MIT License\nCopyright 2026\nAlexander Unverhau\nmit Unterstützung von Claude AI":
            "MIT License\nCopyright 2026\nAlexander Unverhau\nwith assistance of Claude AI",
        "Papierkorb aktiv": "Recycle bin active",
        "ohne Papierkorb (send2trash fehlt)": "no recycle bin (send2trash missing)",
        "in den Papierkorb": "to the recycle bin",
        "in den Papierkorb verschieben": "move to the recycle bin",
        "ENDGÜLTIG löschen": "delete PERMANENTLY",
        "endgültig löschen (ohne Haken: in den Papierkorb)":
            "delete permanently (unchecked: move to the recycle bin)",
        "Unterordner einbeziehen": "Include subfolders",
        "Filter anwenden": "Apply filter",
        "Bitte warten, bis der laufende Vorgang beendet ist.":
            "Please wait until the running task has finished.",
        "Unerwarteter Fehler:\n{error}": "Unexpected error:\n{error}",
        "Kritischer Fehler:\n{error}": "Critical error:\n{error}",
        "Die Bibliothek 'Pillow' ist nicht installiert.\n\n"
        "Bitte ausführen:\n    pip install Pillow":
            "The 'Pillow' library is not installed.\n\n"
            "Please run:\n    pip install Pillow",

        # --- Modulnamen und Kurzbeschreibungen ----------------------------
        "Bild-Vergleich": "Image comparison",
        "Zwei Bilder nebeneinander prüfen, öffnen, tauschen oder löschen":
            "Inspect, open, swap or delete two images side by side",
        "Split-Screen für zwei Bilder inklusive Metadaten und MD5-Prüfsumme.":
            "Split screen for two images including metadata and MD5 checksum.",
        "Statistiken": "Statistics",
        "Formate, Auflösungen und Größen eines Ordners auswerten":
            "Analyse formats, resolutions and sizes of a folder",
        "Überblick über Anzahl, Formate, Auflösungen und Dateigrößen.":
            "Overview of count, formats, resolutions and file sizes.",
        "Duplikat-Finder": "Duplicate finder",
        "Findet byte-identische Bilder über Dateigröße und MD5-Prüfsumme":
            "Finds byte-identical images via file size and MD5 checksum",
        "Exakte Doppel finden und gruppenweise löschen oder verschieben.":
            "Find exact duplicates and delete or move them by group.",
        "Ähnliche Bilder": "Similar images",
        "Findet visuell ähnliche Bilder über einen Perceptual Hash":
            "Finds visually similar images using a perceptual hash",
        "Erkennt Varianten, Skalierungen und Neukomprimierungen desselben Motivs.":
            "Detects variants, rescaled copies and recompressions of the same shot.",
        "Dimensions-Filter": "Dimension filter",
        "Findet Bilder, die in Breite UND Höhe unter einem Schwellwert liegen, "
        "und räumt sie weg":
            "Finds images below a threshold in BOTH width and height and clears them out",
        "Kleine Bilder aufspüren und in einen Ordner verschieben oder löschen.":
            "Track down small images and move them to a folder or delete them.",
        "Batch-Umbenennung": "Batch rename",
        "Alle Bilder eines Ordners nach einem Muster umbenennen":
            "Rename all images in a folder using a pattern",
        "Muster mit Zähler, Originalname, Datum und Bildgröße.":
            "Patterns with counter, original name, date and image size.",
        "Format-Konverter": "Format converter",
        "Einzelne Bilder oder ganze Ordner in ein anderes Format umwandeln":
            "Convert single images or entire folders to another format",
        "JPEG, PNG, WebP, AVIF, BMP, GIF, TIFF, ICO und PPM - einzeln oder als Batch.":
            "JPEG, PNG, WebP, AVIF, BMP, GIF, TIFF, ICO and PPM - single or batch.",
        "Icon-Extraktor": "Icon extractor",
        "Icons aus EXE-, DLL- und Bilddateien auslesen und speichern":
            "Read icons from EXE, DLL and image files and save them",
        "Alle Icon-Größen aus Programmdateien holen und als ICO oder PNG sichern.":
            "Pull every icon size out of program files and save as ICO or PNG.",
        "Info & Hilfe": "Info & help",
        "Module, Abhängigkeiten und Lizenz": "Modules, dependencies and licence",
        "Kurzbeschreibung aller Module und Status der Zusatzbibliotheken.":
            "Short description of every module and the status of optional libraries.",

        # --- Startseite ---------------------------------------------------
        "Alle Werkzeuge auf einen Blick - Modul anklicken zum Öffnen":
            "All tools at a glance - click a module to open it",
        "Alle optionalen Zusatzmodule sind installiert.":
            "All optional libraries are installed.",
        "Optionale Zusatzmodule fehlen: {list}  -  Details unter 'Info & Hilfe'.":
            "Optional libraries missing: {list}  -  see 'Info & help' for details.",

        # --- Bild-Vergleich -----------------------------------------------
        "Linkes Bild öffnen": "Open left image",
        "Rechtes Bild öffnen": "Open right image",
        "Seiten tauschen": "Swap sides",
        "Bild auswählen": "Select image",
        "Bilder": "Images",
        "Alle Dateien": "All files",
        "Kein Bild geladen": "No image loaded",
        "Keine Datei geladen": "No file loaded",
        "Keine Datei geladen.": "No file loaded.",
        "LINKES BILD": "LEFT IMAGE",
        "RECHTES BILD": "RIGHT IMAGE",
        "Im Explorer zeigen": "Show in Explorer",
        "Bild konnte nicht gelesen werden.": "The image could not be read.",
        "Bild konnte nicht geladen werden:\n{error}":
            "The image could not be loaded:\n{error}",
        "Konnte Datei nicht öffnen:\n{error}": "Could not open the file:\n{error}",
        "Konnte Ordner nicht öffnen:\n{error}": "Could not open the folder:\n{error}",
        "Konnte nicht löschen:\n{error}": "Could not delete:\n{error}",
        "Geladen: {name}": "Loaded: {name}",
        "Gelöscht: {name}": "Deleted: {name}",
        "Datei wirklich {action}?\n\n{path}": "Really {action} this file?\n\n{path}",
        "Datei: {name}\nAuflösung: {res}     Größe: {size}     Format: {format}\n"
        "MD5: {md5}\n{path}":
            "File: {name}\nResolution: {res}     Size: {size}     Format: {format}\n"
            "MD5: {md5}\n{path}",

        # --- Trefferlisten (Duplikate / Ähnliche) -------------------------
        "Ordner scannen": "Scan folder",
        "Quellordner": "Source folder",
        "Quellordner wählen": "Choose source folder",
        "Ordner zum Scannen auswählen": "Select the folder to scan",
        "Bitte einen gültigen Quellordner wählen.":
            "Please choose a valid source folder.",
        "Scan starten": "Start scan",
        "Scanne ...": "Scanning ...",
        "Sammle Dateien ...": "Collecting files ...",
        "Prüfe Inhalte ... {done}/{total}": "Checking contents ... {done}/{total}",
        "Berechne Hashes ... {done}/{total}": "Computing hashes ... {done}/{total}",
        "Vergleiche Bilder ...": "Comparing images ...",
        "Gefundene Gruppen": "Groups found",
        "Noch nicht gescannt.": "Not scanned yet.",
        "Keine Treffer.": "No matches.",
        "Keine Treffer vorhanden.": "There are no matches.",
        "Alle Duplikate löschen": "Delete all duplicates",
        "Alle Duplikate verschieben": "Move all duplicates",
        "Alle Ähnlichen löschen": "Delete all similar",
        "Alle Ähnlichen verschieben": "Move all similar",
        "Ähnlichkeit:": "Similarity:",
        "Links im Vergleich öffnen": "Open on the left in comparison",
        "Rechts im Vergleich öffnen": "Open on the right in comparison",
        "Auswahl löschen ({count})": "Delete selection ({count})",
        "Auswahl verschieben ({count})": "Move selection ({count})",
        "Zielordner auswählen": "Select destination folder",
        "GRUPPE {no}  -  {name}  ({count} Dateien)":
            "GROUP {no}  -  {name}  ({count} files)",
        "[behalten]": "[keep]",
        "{groups} Gruppen - {files} Datei(en) über die jeweils erste hinaus. "
        "Rechtsklick für Optionen.":
            "{groups} groups - {files} file(s) beyond the first of each. "
            "Right-click for options.",
        "{count} Datei(en) {action}?": "{action} {count} file(s)?",
        "{done} gelöscht, {failed} fehlgeschlagen.": "{done} deleted, {failed} failed.",
        "{done} verschoben, {failed} fehlgeschlagen.": "{done} moved, {failed} failed.",
        "{done} Datei(en) gelöscht.\n{failed} fehlgeschlagen.":
            "{done} file(s) deleted.\n{failed} failed.",
        "{done} Datei(en) verschoben.\n{failed} fehlgeschlagen.":
            "{done} file(s) moved.\n{failed} failed.",
        "{scanned} Bilder geprüft, {groups} Duplikat-Gruppen "
        "({extra} überzählige Dateien).":
            "{scanned} images checked, {groups} duplicate groups "
            "({extra} surplus files).",
        "{scanned} Bilder verglichen, {groups} ähnliche Gruppen.":
            "{scanned} images compared, {groups} similar groups.",

        # --- Dimensions-Filter --------------------------------------------
        "Schwellwert in Pixel:": "Threshold in pixels:",
        "Treffer = Breite UND Höhe kleiner als dieser Wert":
            "Match = width AND height smaller than this value",
        "Aktion mit den Treffern": "What to do with the matches",
        "Verschieben nach": "Move to",
        "Zielordner": "Destination folder",
        "Zielordner wählen": "Choose destination folder",
        "Bitte einen Zielordner wählen.": "Please choose a destination folder.",
        "Zielordner existiert nicht!": "The destination folder does not exist!",
        "Kann Zielordner nicht anlegen:\n{error}":
            "Cannot create the destination folder:\n{error}",
        "Der Zielordner liegt innerhalb des Quellordners. Fortfahren?":
            "The destination folder is inside the source folder. Continue?",
        "Bitte einen Schwellwert als Ganzzahl > 0 eingeben.":
            "Please enter the threshold as a whole number greater than 0.",
        "Hinweis: 'send2trash' nicht installiert - Löschen erfolgt endgültig.  "
        "pip install send2trash":
            "Note: 'send2trash' is not installed - deleting is permanent.  "
            "pip install send2trash",
        "Scanne ... {count} Bilder geprüft": "Scanning ... {count} images checked",
        "{total} Bilder geprüft - {hits} Treffer (< {limit} px in Breite und Höhe).":
            "{total} images checked - {hits} matches (< {limit} px in width and height).",
        "  {count} Datei(en) nicht lesbar.": "  {count} file(s) unreadable.",
        "  ... und {count} weitere.": "  ... and {count} more.",
        "{count} Bild(er) verschieben nach:\n{target}":
            "Move {count} image(s) to:\n{target}",
        "{count} Bild(er) ENDGÜLTIG löschen?\n"
        "Das kann NICHT rückgängig gemacht werden.":
            "Delete {count} image(s) PERMANENTLY?\nThis CANNOT be undone.",
        "{count} Bild(er) in den Papierkorb verschieben?":
            "Move {count} image(s) to the recycle bin?",
        "FEHLER  {path}\n        {error}": "ERROR  {path}\n       {error}",
        "verschoben": "moved",
        "gelöscht": "deleted",
        "{done} {action}, {failed} fehlgeschlagen.": "{done} {action}, {failed} failed.",
        "{done} Datei(en) {action}.": "{done} file(s) {action}.",
        "{done} Datei(en) {action}.\n{failed} fehlgeschlagen.":
            "{done} file(s) {action}.\n{failed} failed.",

        # --- Batch-Umbenennung --------------------------------------------
        "Ordner und Muster": "Folder and pattern",
        "Ordner auswählen": "Select folder",
        "Start bei": "Start at",
        "Endung klein schreiben": "Lower-case extension",
        "Vorschau aktualisieren": "Refresh preview",
        "Noch kein Ordner gewählt.": "No folder chosen yet.",
        "Noch kein gültiger Ordner gewählt.": "No valid folder chosen yet.",
        "Keine Bilddateien in diesem Ordner.": "No image files in this folder.",
        "Muster ungültig: {error}": "Invalid pattern: {error}",
        "{count} Dateien werden umbenannt.": "{count} files will be renamed.",
        "{count} Datei(en) umbenennen?": "Rename {count} file(s)?",
        "{count} Dateien - ACHTUNG: {conflicts} doppelte Zielnamen. "
        "Bitte {{counter}} im Muster verwenden.":
            "{count} files - WARNING: {conflicts} duplicate target names. "
            "Please use {{counter}} in the pattern.",
        "{done} Dateien umbenannt, {failed} fehlgeschlagen.":
            "{done} files renamed, {failed} failed.",
        "{done} Datei(en) umbenannt.\n{failed} fehlgeschlagen.":
            "{done} file(s) renamed.\n{failed} failed.",
        "{counter}  fortlaufende Nummer (auch {counter:04d})   "
        "{name}  bisheriger Name   {date}  Datum JJJJMMTT   "
        "{w}/{h}  Breite/Höhe":
            "{counter}  running number (also {counter:04d})   "
            "{name}  previous name   {date}  date YYYYMMDD   "
            "{w}/{h}  width/height",

        # --- Statistiken ---------------------------------------------------
        "Ordner analysieren": "Analyse folder",
        "Analyse starten": "Start analysis",
        "Analysiere Ordner ...": "Analysing folder ...",
        "Analysiere ... {count} Bilder": "Analysing ... {count} images",
        "Bericht speichern ...": "Save report ...",
        "Bericht gespeichert: {path}": "Report saved: {path}",
        "Konnte Bericht nicht speichern:\n{error}": "Could not save the report:\n{error}",
        "Textdatei": "Text file",
        "Ordner wählen und Analyse starten.": "Choose a folder and start the analysis.",
        "Bitte einen gültigen Ordner wählen.": "Please choose a valid folder.",
        "ORDNER-ANALYSE": "FOLDER ANALYSIS",
        "%d.%m.%Y %H:%M": "%Y-%m-%d %H:%M",          # Datumsformat des Berichts
        "Keine lesbaren Bilddateien gefunden.": "No readable image files found.",
        "ALLGEMEIN": "GENERAL",
        "FORMATE": "FORMATS",
        "AUFLÖSUNGEN (Top 15)": "RESOLUTIONS (top 15)",
        "EXTREMWERTE": "EXTREMES",
        "Analyse abgeschlossen.": "Analysis complete.",
        "Analyse fertig: {count} Bilder.": "Analysis finished: {count} images.",
        "  Bilddateien          : {value}": "  Image files          : {value}",
        "  Gesamtgröße          : {value}": "  Total size           : {value}",
        "  Durchschnittsgröße   : {value}": "  Average size         : {value}",
        "  Gesamtpixel          : {value} Megapixel":
            "  Total pixels         : {value} megapixels",
        "  Größte Datei    : {name} ({size})": "  Largest file    : {name} ({size})",
        "  Kleinste Datei  : {name} ({size})": "  Smallest file   : {name} ({size})",
        "  Breitestes Bild : {name} ({value} px)": "  Widest image    : {name} ({value} px)",
        "  Höchstes Bild   : {name} ({value} px)": "  Tallest image   : {name} ({value} px)",
        "{count} Dateien": "{count} files",

        # --- Format-Konverter ----------------------------------------------
        "Einzelne Datei konvertieren ...": "Convert a single file ...",
        "(wirkt bei JPEG, WebP und AVIF)": "(applies to JPEG, WebP and AVIF)",
        "Batch-Konvertierung": "Batch conversion",
        "Batch konvertieren": "Convert batch",
        "Dateien hinzufügen": "Add files",
        "Ordner hinzufügen": "Add folder",
        "Auswahl entfernen": "Remove selection",
        "Liste leeren": "Clear list",
        "Dateien auswählen": "Select files",
        "Datei auswählen": "Select file",
        "Ausgabeordner auswählen": "Select output folder",
        "Ordner mit {format}-Dateien auswählen": "Select folder containing {format} files",
        "{format}-Dateien": "{format} files",
        "Keine passenden Dateien in diesem Ordner.": "No matching files in this folder.",
        "Keine Dateien ausgewählt!": "No files selected!",
        "Keine Dateien in der Liste.": "No files in the list.",
        "{count} Datei(en) bereit für die Konvertierung.":
            "{count} file(s) ready for conversion.",
        "Konvertiere ...": "Converting ...",
        "Konvertiere {done}/{total}: {name}": "Converting {done}/{total}: {name}",
        "Konvertierung fehlgeschlagen.": "Conversion failed.",
        "Konvertierung fehlgeschlagen:\n{error}": "Conversion failed:\n{error}",
        "Gespeichert: {path}": "Saved: {path}",
        "Datei gespeichert:\n{path}": "File saved:\n{path}",
        "Batch fertig: {done} konvertiert, {failed} fehlgeschlagen.":
            "Batch finished: {done} converted, {failed} failed.",
        "{done} konvertiert, {failed} fehlgeschlagen -> {target}":
            "{done} converted, {failed} failed -> {target}",
        "{done} Datei(en) konvertiert nach:\n{target}":
            "{done} file(s) converted to:\n{target}",
        "\n\nFehler:\n": "\n\nErrors:\n",
        "\n... und {count} weitere.": "\n... and {count} more.",

        # --- Icon-Extraktor -------------------------------------------------
        "Quelle und Ziel": "Source and destination",
        "Quell-Datei": "Source file",
        "Quelldatei auswählen": "Select source file",
        "Quelldatei existiert nicht!": "The source file does not exist!",
        "Bitte Quelldatei auswählen!": "Please select a source file!",
        "Bitte Zielordner angeben!": "Please specify a destination folder!",
        "Bitte erst die Vorschau laden!": "Please load the preview first!",
        "Ausgabe-Ordner": "Output folder",
        "Unterstützt: .exe, .dll, .sys, .ocx, .cpl, .scr sowie "
        ".ico, .png, .jpg, .bmp, .tif ...":
            "Supported: .exe, .dll, .sys, .ocx, .cpl, .scr as well as "
            ".ico, .png, .jpg, .bmp, .tif ...",
        "Vorschau laden": "Load preview",
        "Alle speichern": "Save all",
        "Zurücksetzen": "Reset",
        "Speichern als": "Save as",
        "Icon-Vorschau": "Icon preview",
        "Noch nichts geladen.": "Nothing loaded yet.",
        "Lade Icons ...": "Loading icons ...",
        "Keine Icons gefunden.": "No icons found.",
        "Keine Icons in dieser Datei gefunden!": "No icons found in this file!",
        "Modul 'icoextract' nicht installiert (pip install icoextract).":
            "Module 'icoextract' is not installed (pip install icoextract).",
        "Hinweis: Modul 'icoextract' fehlt - Icons aus EXE/DLL können nicht "
        "gelesen werden.  pip install icoextract":
            "Note: module 'icoextract' is missing - icons cannot be read from "
            "EXE/DLL files.  pip install icoextract",
        "{count} Icons geladen.": "{count} icons loaded.",
        "{count} Icons geladen - 'Alle speichern' zum Sichern.":
            "{count} icons loaded - use 'Save all' to store them.",
        "{done}/{total} Icons gespeichert.": "{done}/{total} icons saved.",
        "{done} von {total} Icons gespeichert in:\n{folder}":
            "{done} of {total} icons saved to:\n{folder}",
        "\n\nDetails: {error}": "\n\nDetails: {error}",
        "Gruppe {index}: {error}": "Group {index}: {error}",

        # --- Info & Hilfe ---------------------------------------------------
        "Die Module im Überblick": "The modules at a glance",
        "Über dieses Programm": "About this program",
        "Bilder lesen, schreiben und skalieren (Pflicht)":
            "Read, write and scale images (required)",
        "Löschen in den Papierkorb statt endgültig":
            "Delete to the recycle bin instead of permanently",
        "Icons aus EXE- und DLL-Dateien lesen": "Read icons from EXE and DLL files",
        "HEIC- und HEIF-Dateien öffnen": "Open HEIC and HEIF files",
        "Vereint die früheren Einzelprogramme Bildbetrachter Pro 2.0, "
        "Icon Extraktor, Universal Image Converter und Bild-Dimensions-Filter "
        "in einer Oberfläche.\n\n"
        "Tastatur: Strg+1 bis Strg+9 wechseln direkt zwischen den Modulen, "
        "Esc springt zurück zum Start.":
            "Combines the former separate programs Bildbetrachter Pro 2.0, "
            "Icon Extraktor, Universal Image Converter and Bild-Dimensions-Filter "
            "in a single interface.\n\n"
            "Keyboard: Ctrl+1 to Ctrl+9 switch straight between modules, "
            "Esc returns to the home screen.",
    },
}


# --------------------------------------------------------------------------

def main():
    root = tk.Tk()
    if not HAS_PIL:
        root.withdraw()
        messagebox.showerror(
            APP_NAME,
            _("Die Bibliothek 'Pillow' ist nicht installiert.\n\n"
            "Bitte ausführen:\n    pip install Pillow"))
        root.destroy()
        return
    try:
        ToolboxApp(root)
        root.mainloop()
    except Exception as e:
        logging.error(f"Kritischer Fehler: {e}\n{traceback.format_exc()}")
        messagebox.showerror(APP_NAME,
                             _("Kritischer Fehler:\n{error}").format(error=e))


if __name__ == "__main__":
    main()
