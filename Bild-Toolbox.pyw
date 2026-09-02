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
APP_VERSION = "1.0"

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


def apply_theme(name):
    """Farbwerte des gewaehlten Schemas in die Modulvariablen schreiben."""
    global CURRENT_THEME
    CURRENT_THEME = name if name in THEMES else DEFAULT_THEME
    globals().update(THEMES[CURRENT_THEME])


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


class Translator:
    """Uebersetzt einen deutschen Quelltext in die eingestellte Sprache."""

    def __init__(self, language=SOURCE_LANGUAGE):
        self.language = language

    def __call__(self, text):
        if self.language == SOURCE_LANGUAGE:
            return text
        return TRANSLATIONS.get(self.language, {}).get(text, text)

    def available(self):
        """Sprachkuerzel -> Anzeigename, Quellsprache immer zuerst."""
        names = {SOURCE_LANGUAGE: LANGUAGE_NAMES[SOURCE_LANGUAGE]}
        for code in TRANSLATIONS:
            names[code] = LANGUAGE_NAMES.get(code, code)
        return names


_ = Translator()


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
            fmt = im.format or "Unbekannt"
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

class FlatButton(tk.Button):
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
        super().__init__(parent, text=text, command=command, bg=bg, fg=fg,
                         activebackground=hover, activeforeground=fg,
                         disabledforeground=BTN_DISABLED, relief="flat", bd=0,
                         highlightthickness=0, cursor="hand2", font=FONT_SMALL, **kw)
        self._bg, self._hover = bg, hover
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _enabled(self):
        return str(self["state"]) != "disabled"

    def _on_enter(self, _e):
        if self._enabled():
            self.configure(bg=self._hover)

    def _on_leave(self, _e):
        self.configure(bg=self._bg)


def make_card(parent, **pack_kw):
    """Weisse Karte mit dünnem Rahmen."""
    card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                    highlightcolor=BORDER, highlightthickness=1)
    if pack_kw:
        card.pack(**pack_kw)
    return card


def card_title(parent, text):
    tk.Label(parent, text=text, font=FONT_BOLD, bg=CARD, fg=TEXT,
             anchor="w").pack(fill="x", padx=14, pady=(12, 6))


def path_row(parent, label, var, browse_cmd, button_text="Durchsuchen ..."):
    """Zeile: Beschriftung + Eingabefeld + Durchsuchen-Button."""
    row = tk.Frame(parent, bg=CARD)
    row.pack(fill="x", padx=14, pady=4)
    tk.Label(row, text=label, font=FONT_SMALL, bg=CARD, fg=MUTED,
             width=16, anchor="w").pack(side="left")
    entry = ttk.Entry(row, textvariable=var)
    entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
    FlatButton(row, button_text, browse_cmd).pack(side="right")
    return entry


class NavButton(tk.Frame):
    """Eintrag in der linken Navigationsleiste."""

    def __init__(self, parent, icon, text, command):
        super().__init__(parent, bg=SIDEBAR, cursor="hand2")
        self.command = command
        self.active = False

        self.bar = tk.Frame(self, bg=SIDEBAR, width=3)
        self.bar.pack(side="left", fill="y")
        self.icon = tk.Label(self, text=icon, bg=SIDEBAR, fg=SIDEBAR_TEXT,
                             font=("Segoe UI Emoji", 11), width=3)
        self.icon.pack(side="left", pady=5)
        self.label = tk.Label(self, text=text, bg=SIDEBAR, fg=SIDEBAR_TEXT,
                              font=FONT_SMALL, anchor="w")
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
        wrap = tk.Frame(self.body, bg=BG)
        wrap.pack(fill="both", expand=True)

        cards = tk.Frame(wrap, bg=BG)
        cards.pack(fill="both", expand=True)
        for col in range(3):
            cards.columnconfigure(col, weight=1, uniform="cards")

        entries = [m for m in self.app.module_classes if m.key != "home"]
        for index, cls in enumerate(entries):
            self._make_tile(cards, cls, index // 3, index % 3)

        hint = tk.Frame(wrap, bg=BG)
        hint.pack(fill="x", pady=(14, 0))
        missing = self.app.missing_dependencies()
        if missing:
            text = _("Optionale Zusatzmodule fehlen: {list}  -  Details unter "
                     "'Info & Hilfe'.").format(list=", ".join(missing))
            tk.Label(hint, text=text, bg=BG, fg=WARN, font=FONT_SMALL,
                     anchor="w").pack(fill="x")
        else:
            tk.Label(hint, text=_("Alle optionalen Zusatzmodule sind installiert."),
                     bg=BG, fg=OK, font=FONT_SMALL, anchor="w").pack(fill="x")

    def _make_tile(self, parent, cls, row, col):
        tile = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                        highlightcolor=BORDER, highlightthickness=1, cursor="hand2")
        tile.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)

        icon = tk.Label(tile, text=cls.icon, bg=CARD, fg=ACCENT,
                        font=("Segoe UI Emoji", 20), anchor="w")
        icon.pack(fill="x", padx=16, pady=(14, 2))
        title = tk.Label(tile, text=_(cls.title), bg=CARD, fg=TEXT, font=FONT_H2,
                         anchor="w")
        title.pack(fill="x", padx=16)
        desc = tk.Label(tile, text=_(cls.description), bg=CARD, fg=MUTED,
                        font=FONT_SMALL, anchor="w", justify="left",
                        wraplength=250)
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
        self.infos = {}
        self._resize_job = None
        self.use_trash = tk.BooleanVar(value=HAS_TRASH)

        bar = make_card(self.body, fill="x")
        row = tk.Frame(bar, bg=CARD)
        row.pack(fill="x", padx=14, pady=10)
        FlatButton(row, _("Linkes Bild öffnen"), lambda: self.open("left"),
                   kind="primary").pack(side="left", padx=(0, 6))
        FlatButton(row, _("Rechtes Bild öffnen"), lambda: self.open("right"),
                   kind="primary").pack(side="left", padx=6)
        FlatButton(row, _("Seiten tauschen"), self.swap).pack(side="left", padx=6)
        tk.Checkbutton(row, text=_("in den Papierkorb"), variable=self.use_trash,
                       bg=CARD, fg=MUTED, font=FONT_SMALL, activebackground=CARD,
                       state="normal" if HAS_TRASH else "disabled",
                       selectcolor=CARD).pack(side="right")

        panes = tk.Frame(self.body, bg=BG)
        panes.pack(fill="both", expand=True, pady=(10, 0))
        panes.columnconfigure(0, weight=1, uniform="panes")
        panes.columnconfigure(1, weight=1, uniform="panes")
        panes.rowconfigure(0, weight=1)

        self._make_pane(panes, "left", "LINKES BILD", 0)
        self._make_pane(panes, "right", "RECHTES BILD", 1)

    def _make_pane(self, parent, side, caption, column):
        pane = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                        highlightcolor=BORDER, highlightthickness=1)
        pane.grid(row=0, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (6, 0))

        tk.Label(pane, text=_(caption), font=FONT_BOLD, bg=CARD, fg=TEXT).pack(pady=(10, 6))

        canvas = tk.Label(pane, bg=VIEWER_BG, text=_("Kein Bild geladen"),
                          fg=VIEWER_TEXT, font=FONT_SMALL)
        canvas.pack(fill="both", expand=True, padx=12)
        canvas.bind("<Configure>", lambda _e, s=side: self._schedule_fit(s))
        canvas.bind("<Double-Button-1>", lambda _e, s=side: self.open(s))
        self.labels[side] = canvas

        info = tk.Label(pane, text=_("Keine Datei geladen"), font=FONT_SMALL, bg=CARD,
                        fg=MUTED, justify="left", anchor="w", wraplength=420)
        info.pack(fill="x", padx=12, pady=8)
        self.infos[side] = info

        actions = tk.Frame(pane, bg=CARD)
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
            self.infos[side].configure(
                text=_("Datei: {name}\n"
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
        if self.images[side] is None:
            return
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(150, lambda: self._fit(side))

    def _fit(self, side):
        image = self.images[side]
        label = self.labels[side]
        if image is None:
            return
        width = max(label.winfo_width() - 8, 100)
        height = max(label.winfo_height() - 8, 100)
        try:
            thumb = image.copy()
            thumb.thumbnail((width, height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            self.photos[side] = photo
            label.configure(image=photo, text="")
        except Exception as e:
            logging.error(f"Fehler beim Skalieren: {e}")

    # ---------------------------------------------------------------- Aktionen
    def swap(self):
        self.paths["left"], self.paths["right"] = self.paths["right"], self.paths["left"]
        self.images["left"], self.images["right"] = self.images["right"], self.images["left"]
        for side in ("left", "right"):
            if self.paths[side]:
                self.load(side, self.paths[side])
            else:
                self.clear(side)

    def clear(self, side):
        self.paths[side] = None
        self.images[side] = None
        self.photos[side] = None
        self.labels[side].configure(image="", text=_("Kein Bild geladen"))
        self.infos[side].configure(text=_("Keine Datei geladen"), fg=MUTED)

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
        wrap = tk.Frame(parent, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        columns = ("res", "size")
        self.tree = ttk.Treeview(wrap, columns=columns, show="tree headings",
                                 selectmode="extended")
        self.tree.heading("#0", text=_(self.tree_heading))
        self.tree.heading("res", text=_("Auflösung"))
        self.tree.heading("size", text=_("Größe"))
        self.tree.column("#0", width=520, stretch=True)
        self.tree.column("res", width=110, anchor="center", stretch=False)
        self.tree.column("size", width=90, anchor="e", stretch=False)

        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.tag_configure("group", font=FONT_BOLD)
        self.tree.tag_configure("keep", foreground=OK)
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<Double-Button-1>", self._on_double_click)

    def visible_groups(self):
        """Gruppen, die angezeigt und bearbeitet werden (Filter-Hook)."""
        return self.groups

    def render_groups(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.thumbnails.clear()

        groups = self.visible_groups()
        if not groups:
            self.set_summary(_("Keine Treffer."))
            return

        thumb_budget = MAX_THUMBS
        for index, (caption, entries) in enumerate(groups, 1):
            parent = self.tree.insert(
                "", "end",
                text=_("GRUPPE {no}  -  {name}  ({count} Dateien)").format(
                    no=index, name=caption, count=len(entries)),
                open=True, tags=("group",))
            for position, entry in enumerate(entries):
                path = entry["path"]
                thumb = None
                if thumb_budget > 0:
                    thumb = self._thumbnail(path)
                    if thumb is not None:
                        thumb_budget -= 1
                marker = "  [behalten]" if position == 0 else ""
                tags = (path, "keep") if position == 0 else (path,)
                self.tree.insert(parent, "end",
                                 text=f" {os.path.basename(path)}{marker}",
                                 values=(entry.get("resolution", "?"),
                                         entry.get("size", "?")),
                                 image=thumb if thumb else "",
                                 tags=tags)
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
        self.summary.configure(text=text)

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

        options = tk.Frame(card, bg=CARD)
        options.pack(fill="x", padx=14, pady=(4, 4))
        tk.Checkbutton(options, text=_("Unterordner einbeziehen"), variable=self.recursive,
                       bg=CARD, fg=TEXT, font=FONT_SMALL, activebackground=CARD,
                       selectcolor=CARD).pack(side="left")
        tk.Label(options, text=_("Pixel min.:"), bg=CARD, fg=MUTED,
                 font=FONT_SMALL).pack(side="left", padx=(20, 4))
        ttk.Entry(options, textvariable=self.min_px, width=12).pack(side="left")
        tk.Label(options, text=_("max.:"), bg=CARD, fg=MUTED,
                 font=FONT_SMALL).pack(side="left", padx=(10, 4))
        ttk.Entry(options, textvariable=self.max_px, width=12).pack(side="left")
        FlatButton(options, _("Filter anwenden"), self.render_groups).pack(side="left", padx=10)

        actions = tk.Frame(card, bg=CARD)
        actions.pack(fill="x", padx=14, pady=(6, 12))
        self.scan_btn = FlatButton(actions, _("Scan starten"), self.start_scan, kind="primary")
        self.scan_btn.pack(side="left")
        self.cancel_btn = FlatButton(actions, _("Abbrechen"), self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        FlatButton(actions, _("Alle Duplikate löschen"), self.delete_all_extra,
                   kind="danger").pack(side="left", padx=(20, 6))
        FlatButton(actions, _("Alle Duplikate verschieben"), self.move_all_extra,
                   kind="warn").pack(side="left")
        tk.Checkbutton(actions, text=_("in den Papierkorb"), variable=self.use_trash,
                       bg=CARD, fg=MUTED, font=FONT_SMALL, activebackground=CARD,
                       state="normal" if HAS_TRASH else "disabled",
                       selectcolor=CARD).pack(side="right")

        self.progress = ttk.Progressbar(card, mode="determinate")
        self.progress.pack(fill="x", padx=14, pady=(0, 12))

        result = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(result, _("Gefundene Gruppen"))
        self.summary = tk.Label(result, text=_("Noch nicht gescannt."), bg=CARD, fg=MUTED,
                                font=FONT_SMALL, anchor="w")
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

        options = tk.Frame(card, bg=CARD)
        options.pack(fill="x", padx=14, pady=(4, 4))
        tk.Checkbutton(options, text=_("Unterordner einbeziehen"), variable=self.recursive,
                       bg=CARD, fg=TEXT, font=FONT_SMALL, activebackground=CARD,
                       selectcolor=CARD).pack(side="left")
        tk.Label(options, text=_("Ähnlichkeit:"), bg=CARD, fg=MUTED,
                 font=FONT_SMALL).pack(side="left", padx=(20, 6))
        scale = ttk.Scale(options, from_=50, to=100, orient="horizontal", length=220)
        scale.pack(side="left")
        self.similarity_label = tk.Label(options, text="90 %", bg=CARD, fg=TEXT,
                                         font=FONT_BOLD, width=6)
        self.similarity_label.pack(side="left", padx=6)
        scale.set(90)                       # erst jetzt - Label muss existieren
        scale.configure(command=self._on_scale)

        actions = tk.Frame(card, bg=CARD)
        actions.pack(fill="x", padx=14, pady=(6, 12))
        self.scan_btn = FlatButton(actions, _("Scan starten"), self.start_scan, kind="primary")
        self.scan_btn.pack(side="left")
        self.cancel_btn = FlatButton(actions, _("Abbrechen"), self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        FlatButton(actions, _("Alle Ähnlichen löschen"), self.delete_all_extra,
                   kind="danger").pack(side="left", padx=(20, 6))
        FlatButton(actions, _("Alle Ähnlichen verschieben"), self.move_all_extra,
                   kind="warn").pack(side="left")
        tk.Checkbutton(actions, text=_("in den Papierkorb"), variable=self.use_trash,
                       bg=CARD, fg=MUTED, font=FONT_SMALL, activebackground=CARD,
                       state="normal" if HAS_TRASH else "disabled",
                       selectcolor=CARD).pack(side="right")

        self.progress = ttk.Progressbar(card, mode="determinate")
        self.progress.pack(fill="x", padx=14, pady=(0, 12))

        result = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(result, _("Gefundene Gruppen"))
        self.summary = tk.Label(result, text=_("Noch nicht gescannt."), bg=CARD, fg=MUTED,
                                font=FONT_SMALL, anchor="w")
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

        options = tk.Frame(card, bg=CARD)
        options.pack(fill="x", padx=14, pady=4)
        tk.Checkbutton(options, text=_("Unterordner einbeziehen"), variable=self.recursive,
                       bg=CARD, fg=TEXT, font=FONT_SMALL, activebackground=CARD,
                       selectcolor=CARD).pack(side="left")
        tk.Label(options, text=_("Schwellwert in Pixel:"), bg=CARD, fg=MUTED,
                 font=FONT_SMALL).pack(side="left", padx=(20, 6))
        ttk.Spinbox(options, from_=1, to=200000, width=8,
                    textvariable=self.threshold).pack(side="left")
        tk.Label(options, text=_("Treffer = Breite UND Höhe kleiner als dieser Wert"),
                 bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=8)

        scan_row = tk.Frame(card, bg=CARD)
        scan_row.pack(fill="x", padx=14, pady=(6, 12))
        self.scan_btn = FlatButton(scan_row, _("Scannen"), self.start_scan, kind="primary")
        self.scan_btn.pack(side="left")
        self.cancel_btn = FlatButton(scan_row, _("Abbrechen"), self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        self.summary = tk.Label(scan_row, text=_("Noch nicht gescannt."), bg=CARD,
                                fg=MUTED, font=FONT_SMALL)
        self.summary.pack(side="left", padx=12)

        action_card = make_card(self.body, fill="x", pady=(10, 0))
        card_title(action_card, _("Aktion mit den Treffern"))

        move_row = tk.Frame(action_card, bg=CARD)
        move_row.pack(fill="x", padx=14, pady=2)
        tk.Radiobutton(move_row, text=_("Verschieben nach"), variable=self.action,
                       value="move", command=self._sync, bg=CARD, fg=TEXT,
                       font=FONT_SMALL, activebackground=CARD, selectcolor=CARD,
                       width=16, anchor="w").pack(side="left")
        self.target_entry = ttk.Entry(move_row, textvariable=self.target)
        self.target_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.target_btn = FlatButton(move_row, _("Durchsuchen ..."),
                                     lambda: self.ask_dir(_("Zielordner wählen"), self.target))
        self.target_btn.pack(side="right")

        del_row = tk.Frame(action_card, bg=CARD)
        del_row.pack(fill="x", padx=14, pady=2)
        tk.Radiobutton(del_row, text=_("Löschen"), variable=self.action, value="delete",
                       command=self._sync, bg=CARD, fg=TEXT, font=FONT_SMALL,
                       activebackground=CARD, selectcolor=CARD, width=16,
                       anchor="w").pack(side="left")
        self.perm_chk = tk.Checkbutton(
            del_row, text=_("endgültig löschen (ohne Haken: in den Papierkorb)"),
            variable=self.permanent, bg=CARD, fg=TEXT, font=FONT_SMALL,
            activebackground=CARD, selectcolor=CARD)
        self.perm_chk.pack(side="left")

        run_row = tk.Frame(action_card, bg=CARD)
        run_row.pack(fill="x", padx=14, pady=(8, 12))
        self.run_btn = FlatButton(run_row, _("Ausführen"), self.start_action,
                                  kind="danger", state="disabled")
        self.run_btn.pack(side="left")
        self.progress = ttk.Progressbar(run_row, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

        log_card = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(log_card, _("Protokoll"))
        log_wrap = tk.Frame(log_card, bg=CARD)
        log_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.log = tk.Text(log_wrap, height=10, wrap="none", font=FONT_MONO,
                           bg=CARD_ALT, fg=TEXT, insertbackground=TEXT, relief="flat",
                           highlightbackground=BORDER, highlightthickness=1)
        yscroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        if not HAS_TRASH:
            self._log(_("Hinweis: 'send2trash' nicht installiert - Löschen erfolgt "
                      "endgültig.  pip install send2trash"))
        self._sync()

    # ------------------------------------------------------------------ Helfer
    def _log(self, message):
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
        self.summary.configure(text=_("Scanne ..."))
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
        self.summary.configure(text=message, fg=OK if candidates else MUTED)
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
        self.summary.configure(text=summary)
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

        pattern_row = tk.Frame(card, bg=CARD)
        pattern_row.pack(fill="x", padx=14, pady=4)
        tk.Label(pattern_row, text=_("Muster"), font=FONT_SMALL, bg=CARD, fg=MUTED,
                 width=16, anchor="w").pack(side="left")
        entry = ttk.Entry(pattern_row, textvariable=self.pattern)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        entry.bind("<KeyRelease>", lambda _e: self.preview())
        tk.Label(pattern_row, text=_("Start bei"), font=FONT_SMALL, bg=CARD,
                 fg=MUTED).pack(side="left", padx=(0, 4))
        start_entry = ttk.Entry(pattern_row, textvariable=self.start_number, width=6)
        start_entry.pack(side="left")
        start_entry.bind("<KeyRelease>", lambda _e: self.preview())

        tk.Label(card, text=_(self.PLACEHOLDERS), bg=CARD, fg=MUTED, font=FONT_TINY,
                 anchor="w", justify="left", wraplength=900).pack(fill="x", padx=14, pady=(2, 4))

        actions = tk.Frame(card, bg=CARD)
        actions.pack(fill="x", padx=14, pady=(4, 12))
        tk.Checkbutton(actions, text=_("Endung klein schreiben"), variable=self.lower_ext,
                       command=self.preview, bg=CARD, fg=TEXT, font=FONT_SMALL,
                       activebackground=CARD, selectcolor=CARD).pack(side="left")
        FlatButton(actions, _("Vorschau aktualisieren"), self.preview).pack(side="left", padx=10)
        self.run_btn = FlatButton(actions, _("Umbenennen"), self.rename, kind="primary",
                                  state="disabled")
        self.run_btn.pack(side="right")

        preview_card = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(preview_card, _("Vorschau"))
        self.summary = tk.Label(preview_card, text=_("Noch kein Ordner gewählt."), bg=CARD,
                                fg=MUTED, font=FONT_SMALL, anchor="w")
        self.summary.pack(fill="x", padx=14, pady=(0, 6))

        wrap = tk.Frame(preview_card, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.tree = ttk.Treeview(wrap, columns=("new",), show="headings")
        self.tree.heading("#1", text=_("neuer Name"))
        self.tree.column("#1", width=300)
        self.tree["columns"] = ("old", "new")
        self.tree.heading("old", text=_("bisher"))
        self.tree.heading("new", text=_("neu"))
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
            self.summary.configure(text=_("Noch kein gültiger Ordner gewählt."), fg=MUTED)
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
                self.summary.configure(
                    text=_("Muster ungültig: {error}").format(error=e), fg=DANGER)
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
            self.summary.configure(text=_("Keine Bilddateien in diesem Ordner."), fg=MUTED)
            return
        if conflicts:
            self.summary.configure(
                text=_("{count} Dateien - ACHTUNG: {conflicts} doppelte Zielnamen. "
                       "Bitte {{counter}} im Muster verwenden.").format(
                    count=len(self.plan), conflicts=conflicts), fg=DANGER)
            return

        self.summary.configure(
            text=_("{count} Dateien werden umbenannt.").format(count=len(self.plan)),
            fg=OK)
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

        actions = tk.Frame(card, bg=CARD)
        actions.pack(fill="x", padx=14, pady=(4, 12))
        tk.Checkbutton(actions, text=_("Unterordner einbeziehen"), variable=self.recursive,
                       bg=CARD, fg=TEXT, font=FONT_SMALL, activebackground=CARD,
                       selectcolor=CARD).pack(side="left")
        self.run_btn = FlatButton(actions, _("Analyse starten"), self.start, kind="primary")
        self.run_btn.pack(side="left", padx=12)
        FlatButton(actions, _("Bericht speichern ..."), self.save_report).pack(side="left")
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.pack(side="right")

        result = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(result, _("Ergebnis"))
        wrap = tk.Frame(result, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.text = tk.Text(wrap, wrap="none", font=FONT_MONO, bg=CARD_ALT, fg=TEXT,
                            insertbackground=TEXT,
                            relief="flat", highlightbackground=BORDER, highlightthickness=1)
        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.insert("end", _("Ordner wählen und Analyse starten."))
        self.text.configure(state="disabled")

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

        line = "-" * 66
        stamp = datetime.now().strftime(_("%d.%m.%Y %H:%M"))
        out = [_("ORDNER-ANALYSE") + "   " + stamp, folder, line, ""]
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

        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "\n".join(out))
        self.text.configure(state="disabled")
        self.status(_("Analyse fertig: {count} Bilder.").format(
            count=stats["files"]))

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
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text=_("Von"), font=FONT_SMALL, bg=CARD, fg=MUTED,
                 width=16, anchor="w").pack(side="left")
        ttk.Combobox(row, textvariable=self.input_format,
                     values=list(self.SUPPORTED_FORMATS), state="readonly",
                     width=14).pack(side="left")
        tk.Label(row, text=_("nach"), font=FONT_SMALL, bg=CARD,
                 fg=MUTED).pack(side="left", padx=10)
        ttk.Combobox(row, textvariable=self.output_format,
                     values=list(self.SUPPORTED_FORMATS), state="readonly",
                     width=14).pack(side="left")
        FlatButton(row, _("Einzelne Datei konvertieren ..."), self.convert_single,
                   kind="secondary").pack(side="right")

        quality_row = tk.Frame(card, bg=CARD)
        quality_row.pack(fill="x", padx=14, pady=(4, 12))
        tk.Label(quality_row, text=_("Qualität"), font=FONT_SMALL, bg=CARD, fg=MUTED,
                 width=16, anchor="w").pack(side="left")
        scale = ttk.Scale(quality_row, from_=1, to=100, orient="horizontal", length=260)
        scale.pack(side="left")
        self.quality_label = tk.Label(quality_row, text="95 %", bg=CARD, fg=TEXT,
                                      font=FONT_BOLD, width=6)
        self.quality_label.pack(side="left", padx=8)
        scale.set(95)                       # erst jetzt - Label muss existieren
        scale.configure(command=self._on_quality)
        tk.Label(quality_row, text=_("(wirkt bei JPEG, WebP und AVIF)"), bg=CARD,
                 fg=MUTED, font=FONT_SMALL).pack(side="left")

        batch = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(batch, _("Batch-Konvertierung"))
        buttons = tk.Frame(batch, bg=CARD)
        buttons.pack(fill="x", padx=14, pady=4)
        FlatButton(buttons, _("Dateien hinzufügen"), self.add_files).pack(side="left")
        FlatButton(buttons, _("Ordner hinzufügen"), self.add_folder).pack(side="left", padx=6)
        FlatButton(buttons, _("Auswahl entfernen"), self.remove_selected).pack(side="left")
        FlatButton(buttons, _("Liste leeren"), self.clear_list).pack(side="left", padx=6)
        self.run_btn = FlatButton(buttons, _("Batch konvertieren"), self.start_batch,
                                  kind="primary")
        self.run_btn.pack(side="right")

        wrap = tk.Frame(batch, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=14, pady=(6, 6))
        self.listbox = tk.Listbox(wrap, selectmode="extended", font=FONT_SMALL,
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
        self.summary = tk.Label(batch, text=_("Keine Dateien in der Liste."), bg=CARD,
                                fg=MUTED, font=FONT_SMALL, anchor="w")
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
        self.summary.configure(
            text=_("Keine Dateien in der Liste.") if not count
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
        self.summary.configure(
            text=_("{done} konvertiert, {failed} fehlgeschlagen -> {target}").format(
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

        tk.Label(card, text=_("Unterstützt: .exe, .dll, .sys, .ocx, .cpl, .scr sowie "
                            ".ico, .png, .jpg, .bmp, .tif ..."),
                 bg=CARD, fg=MUTED, font=FONT_TINY, anchor="w").pack(fill="x", padx=14)

        actions = tk.Frame(card, bg=CARD)
        actions.pack(fill="x", padx=14, pady=(8, 12))
        FlatButton(actions, _("Vorschau laden"), self.load_preview,
                   kind="primary").pack(side="left")
        FlatButton(actions, _("Alle speichern"), self.save_icons,
                   kind="success").pack(side="left", padx=6)
        FlatButton(actions, _("Zurücksetzen"), self.reset).pack(side="left")
        tk.Label(actions, text=_("Speichern als"), bg=CARD, fg=MUTED,
                 font=FONT_SMALL).pack(side="left", padx=(20, 6))
        ttk.Combobox(actions, textvariable=self.save_format, values=["ICO", "PNG"],
                     state="readonly", width=8).pack(side="left")

        self.progress = ttk.Progressbar(card, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=14, pady=(0, 12))

        preview = make_card(self.body, fill="both", expand=True, pady=(10, 0))
        card_title(preview, _("Icon-Vorschau"))
        self.summary = tk.Label(preview, text=_("Noch nichts geladen."), bg=CARD, fg=MUTED,
                                font=FONT_SMALL, anchor="w")
        self.summary.pack(fill="x", padx=14, pady=(0, 6))

        wrap = tk.Frame(preview, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        yscroll = ttk.Scrollbar(wrap, orient="vertical")
        yscroll.pack(side="right", fill="y")
        self.canvas = tk.Canvas(wrap, bg=CARD_ALT, highlightbackground=BORDER,
                                highlightthickness=1, yscrollcommand=yscroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        yscroll.configure(command=self.canvas.yview)
        self.grid_frame = tk.Frame(self.canvas, bg=CARD_ALT)
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))

        if not HAS_ICOEXTRACT:
            tk.Label(preview, text=_("Hinweis: Modul 'icoextract' fehlt - Icons aus EXE/DLL "
                                   "können nicht gelesen werden.  pip install icoextract"),
                     bg=CARD, fg=WARN, font=FONT_SMALL,
                     anchor="w").pack(fill="x", padx=14, pady=(0, 10))

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
                    self._last_error = f"Gruppe {index}: {e}"
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
            self.summary.configure(
                text=_("{count} Icons geladen - 'Alle speichern' zum Sichern.").format(
                    count=len(self.icons)), fg=OK)
            self.status(_("{count} Icons geladen.").format(count=len(self.icons)))
        else:
            message = _("Keine Icons in dieser Datei gefunden!")
            if self._last_error:
                message += _("\n\nDetails: {error}").format(error=self._last_error)
            self.summary.configure(text=_("Keine Icons gefunden."), fg=DANGER)
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

                cell = tk.Frame(self.grid_frame, bg=CARD, highlightbackground=BORDER,
                                highlightthickness=1)
                cell.grid(row=index // 8, column=index % 8, padx=6, pady=6)
                tk.Label(cell, image=photo, bg=CARD, width=70, height=70).pack()
                tk.Label(cell, text=f"{icon.width}x{icon.height}", bg=CARD, fg=MUTED,
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
        self.summary.configure(text=saved_text, fg=OK)
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
        self.summary.configure(text=_("Noch nichts geladen."), fg=MUTED)
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
        help_card = make_card(self.body, fill="x")
        card_title(help_card, _("Die Module im Überblick"))
        for cls in self.app.module_classes:
            if cls.key in ("home", "info"):
                continue
            row = tk.Frame(help_card, bg=CARD)
            row.pack(fill="x", padx=14, pady=3)
            tk.Label(row, text=cls.icon, bg=CARD, fg=ACCENT,
                     font=("Segoe UI Emoji", 11), width=3).pack(side="left")
            tk.Label(row, text=_(cls.title), bg=CARD, fg=TEXT, font=FONT_BOLD,
                     width=20, anchor="w").pack(side="left")
            tk.Label(row, text=_(cls.description), bg=CARD, fg=MUTED, font=FONT_SMALL,
                     anchor="w", justify="left").pack(side="left", fill="x", expand=True)
        tk.Frame(help_card, bg=CARD, height=8).pack()

        deps_card = make_card(self.body, fill="x", pady=(10, 0))
        card_title(deps_card, _("Bibliotheken"))
        for name, installed, purpose, command in self.app.dependency_table():
            row = tk.Frame(deps_card, bg=CARD)
            row.pack(fill="x", padx=14, pady=3)
            tk.Label(row, text="●", bg=CARD, fg=OK if installed else WARN,
                     font=FONT_SMALL, width=3).pack(side="left")
            tk.Label(row, text=name, bg=CARD, fg=TEXT, font=FONT_BOLD, width=20,
                     anchor="w").pack(side="left")
            tk.Label(row, text=purpose, bg=CARD, fg=MUTED, font=FONT_SMALL,
                     anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(row, text=_("installiert") if installed else command, bg=CARD,
                     fg=OK if installed else WARN, font=FONT_SMALL).pack(side="right")
        tk.Frame(deps_card, bg=CARD, height=8).pack()

        about_card = make_card(self.body, fill="both", expand=True, pady=(10, 0))
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
        tk.Label(about_card, text=about, bg=CARD, fg=TEXT, font=FONT_SMALL,
                 justify="left", anchor="nw", wraplength=900).pack(
            fill="both", expand=True, padx=14, pady=(0, 14))


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
        self.root.geometry("1400x900")
        self.root.minsize(1080, 700)

        self.pages = {}          # key -> (page_frame, module_instance oder None)
        self.nav_buttons = {}
        self.current = None
        self.event_queue = queue.Queue()
        self._pump_job = None

        # Sprache und Farbschema stehen fest, bevor das erste Widget entsteht
        _.language = startup_language()
        apply_theme(startup_theme())
        self.root.configure(bg=BG)

        self._setup_style()
        self._build_layout()
        self.show("home")
        self._bind_keys()
        self._pump()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------------ Style
    def _setup_style(self):
        style = ttk.Style()
        try:
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
        # Klappliste der Auswahlfelder ist ein klassisches Listenfeld
        self.root.option_add("*TCombobox*Listbox.background", FIELD_BG)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", ON_ACCENT)
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
        outer = self.outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)

        # --- Sidebar ---
        sidebar = tk.Frame(outer, bg=SIDEBAR, width=250)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand = tk.Frame(sidebar, bg=SIDEBAR)
        brand.pack(fill="x", pady=(14, 8), padx=16)
        tk.Label(brand, text=APP_NAME, bg=SIDEBAR, fg=SIDEBAR_TITLE,
                 font=("Segoe UI", 15, "bold"), anchor="w").pack(fill="x")
        tk.Label(brand, text=_("Version {version}").format(version=APP_VERSION),
                 bg=SIDEBAR, fg=SIDEBAR_GROUP,
                 font=FONT_TINY, anchor="w").pack(fill="x")

        # Fusszeile und Sprachauswahl zuerst packen - so bleiben sie auch bei
        # kleiner Fensterhoehe sichtbar und die Navigation weicht darueber aus.
        footer = tk.Label(sidebar, text=_("MIT License\nCopyright 2026\nAlexander Unverhau"),
                          bg=SIDEBAR, fg=SIDEBAR_GROUP, font=FONT_TINY, justify="left")
        footer.pack(side="bottom", anchor="w", padx=18, pady=(6, 12))

        lang_frame = tk.Frame(sidebar, bg=SIDEBAR)
        tk.Label(lang_frame, text=_("Sprache & Darstellung"), bg=SIDEBAR,
                 fg=SIDEBAR_GROUP, font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x")
        row = tk.Frame(lang_frame, bg=SIDEBAR)
        row.pack(fill="x", pady=(3, 0))

        self.language_names = _.available()
        self.language_box = ttk.Combobox(
            row, state="readonly", font=FONT_SMALL,
            values=list(self.language_names.values()))
        self.language_box.set(self.language_names[_.language])
        self.language_box.pack(side="left", fill="x", expand=True)
        self.language_box.bind("<<ComboboxSelected>>", self._on_language_selected)

        self.dark_var = tk.BooleanVar(value=CURRENT_THEME == "dark")
        tk.Checkbutton(row, text=_("Dunkel"), variable=self.dark_var,
                       command=self._on_theme_toggled, bg=SIDEBAR, fg=SIDEBAR_TEXT,
                       activebackground=SIDEBAR, activeforeground=SIDEBAR_TITLE,
                       selectcolor=SIDEBAR_HOVER, font=FONT_SMALL,
                       highlightthickness=0, bd=0, cursor="hand2").pack(
            side="right", padx=(6, 0))

        lang_frame.pack(side="bottom", fill="x", padx=18, pady=(0, 4))

        current_group = None
        for cls in self.module_classes:
            if cls.group and cls.group != current_group:
                current_group = cls.group
                tk.Label(sidebar, text=_(cls.group).upper(), bg=SIDEBAR, fg=SIDEBAR_GROUP,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(
                    fill="x", padx=18, pady=(9, 2))
            button = NavButton(sidebar, cls.icon, _(cls.title),
                               lambda key=cls.key: self.show(key))
            button.pack(fill="x")
            self.nav_buttons[cls.key] = button

        # --- Inhalt ---
        right = tk.Frame(outer, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        header = tk.Frame(right, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 8))
        self.header_title = tk.Label(header, text="", bg=BG, fg=TEXT, font=FONT_H1,
                                     anchor="w")
        self.header_title.pack(fill="x")
        self.header_subtitle = tk.Label(header, text="", bg=BG, fg=MUTED, font=FONT_SMALL,
                                        anchor="w", justify="left")
        self.header_subtitle.pack(fill="x", pady=(2, 0))

        self.content = tk.Frame(right, bg=BG)
        self.content.pack(fill="both", expand=True, padx=24, pady=(6, 12))

        # --- Statusleiste ---
        status_bar = self.status_bar = tk.Frame(self.root, bg=STATUS_BG, height=26)
        status_bar.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value=_("Bereit"))
        tk.Label(status_bar, textvariable=self.status_var, bg=STATUS_BG, fg=MUTED,
                 font=FONT_SMALL, anchor="w").pack(side="left", padx=14, pady=3)
        tk.Label(status_bar, text=(_("Papierkorb aktiv") if HAS_TRASH
                                   else _("ohne Papierkorb (send2trash fehlt)")),
                 bg=STATUS_BG, fg=OK if HAS_TRASH else WARN, font=FONT_TINY,
                 anchor="e").pack(side="right", padx=14)

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
        if self._pump_job is not None:
            try:
                self.root.after_cancel(self._pump_job)
            except tk.TclError:
                pass
            self._pump_job = None
        self.root.destroy()

    def _bind_keys(self):
        for index, cls in enumerate(self.module_classes[:9], 1):
            self.root.bind(f"<Control-Key-{index}>",
                           lambda _e, key=cls.key: self.show(key))
        self.root.bind("<Escape>", lambda _e: self.show("home"))

    # ------------------------------------------------------------ Navigation
    def show(self, key):
        cls = next((c for c in self.module_classes if c.key == key), None)
        if cls is None:
            return
        if self.current == key:
            return

        if self.current and self.current in self.pages:
            self.pages[self.current][0].pack_forget()

        if key not in self.pages:
            page = tk.Frame(self.content, bg=BG)
            module = cls(self, page)
            self.pages[key] = (page, module)
        page, _module = self.pages[key]
        page.pack(fill="both", expand=True)

        self.header_title.configure(text=f"{cls.icon}   {_(cls.title)}")
        self.header_subtitle.configure(text=_(cls.subtitle))
        for nav_key, button in self.nav_buttons.items():
            button.set_active(nav_key == key)
        self.current = key
        self.set_status(_("Bereit"))

    # ------------------------------------------- Sprache und Farbschema
    def _busy(self):
        """Laeuft gerade ein Scan oder eine Umwandlung?"""
        return any(module.busy for _page, module in self.pages.values() if module)

    def _rebuild(self):
        """Oberflaeche komplett neu aufbauen (nach Sprache oder Farbschema)."""
        while not self.event_queue.empty():      # veraltete Auftraege verwerfen
            self.event_queue.get_nowait()

        current = self.current or "home"
        for page, _module in self.pages.values():
            page.destroy()
        self.pages.clear()
        self.nav_buttons.clear()
        self.current = None
        self.outer.destroy()
        self.status_bar.destroy()

        self.root.configure(bg=BG)
        self._setup_style()
        self._build_layout()
        self.show(current)

    def _on_language_selected(self, _event=None):
        chosen = self.language_box.get()
        for code, name in self.language_names.items():
            if name == chosen:
                self.set_language(code)
                return

    def set_language(self, code):
        """Sprache umstellen und die Oberflaeche neu aufbauen."""
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
        self._rebuild()

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
        self._rebuild()

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
        self.status_var.set(text)

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
        "Format": "Format",
        "Auflösung": "Resolution",
        "Größe": "Size",
        "Qualität": "Quality",
        "Von": "From",
        "nach": "to",
        "bisher": "current",
        "neu": "new",
        "neuer Name": "new name",
        "max.:": "max.:",
        "Pixel min.:": "Pixels min.:",
        "Suche": "Search",
        "Protokoll": "Log",
        "Ergebnis": "Result",
        "Bibliotheken": "Libraries",
        "installiert": "installed",
        "MIT License\nCopyright 2026\nAlexander Unverhau":
            "MIT License\nCopyright 2026\nAlexander Unverhau",
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
