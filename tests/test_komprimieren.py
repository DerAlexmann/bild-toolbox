"""Prueft das Rechenwerk des Moduls Komprimieren - ohne Oberflaeche.

Geprueft wird, was beim Komprimieren tatsaechlich schiefgeht: eine
Zielgroesse, die nicht eingehalten oder unnoetig weit unterschritten wird,
eine unerreichbare Grenze, eine Kantenlaenge, die das Bild vergroessert,
verschwundene oder stehengebliebene Metadaten und ein Format, das keine
Komprimierung kennt. Die Oberflaeche selbst bauen die Fenstertests.
"""

import os
import threading
import types

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFilter


class Feld:
    """Ersatz fuer tk.StringVar - die Logiktests brauchen kein Fenster."""

    def __init__(self, wert):
        self.wert = wert

    def get(self):
        return self.wert

    def set(self, wert):
        self.wert = wert


@pytest.fixture
def modul(toolbox):
    """CompressModule ohne Oberflaeche, nur fuer die Logik seiner Methoden."""
    return toolbox.CompressModule.__new__(toolbox.CompressModule)


@pytest.fixture
def stapel(modul):
    """Modul so weit ausgestattet, dass _batch_worker synchron durchlaeuft."""
    ergebnisse = []
    modul.cancel_event = threading.Event()
    modul.ui = lambda func, *args: func(*args)
    modul.status = lambda _text: None
    modul.progress = types.SimpleNamespace(configure=lambda *_a, **_k: None)
    modul._batch_done = ergebnisse.append
    return modul, ergebnisse


def auftrag(**abweichend):
    einstellungen = {"quality": 70, "target_kb": 0, "max_edge": 0, "keep_metadata": False}
    einstellungen.update(abweichend)
    return einstellungen


def foto(groesse=(900, 700)):
    """Bild mit Struktur - eine einfarbige Flaeche waere unrealistisch klein."""
    bild = Image.radial_gradient("L").resize(groesse).convert("RGB")
    stift = ImageDraw.Draw(bild)
    for x in range(0, groesse[0], 40):
        stift.line([(x, 0), (x // 2, groesse[1])],
                   fill=(x % 256, (x * 7) % 256, 255 - x % 256), width=2)
    return bild.filter(ImageFilter.GaussianBlur(0.4))


@pytest.fixture
def jpeg(tmp_path):
    pfad = tmp_path / "quelle.jpg"
    foto().save(pfad, "JPEG", quality=95)
    return pfad


# ------------------------------------------------------------------ Zielgroesse

def test_zielgroesse_wird_eingehalten_und_ausgenutzt(toolbox, jpeg, tmp_path):
    grenze = 60
    ziel = tmp_path / "klein.jpg"
    vorher, nachher, qualitaet, erreicht = toolbox.compress_file(
        str(jpeg), str(ziel), target_kb=grenze)

    assert vorher == jpeg.stat().st_size
    assert erreicht
    assert nachher <= grenze * 1024
    # Nicht einfach die kleinste Qualitaet nehmen: Wer 40 KB erlaubt, will
    # keine 8-KB-Datei mit sichtbaren Bloecken.
    assert nachher > grenze * 1024 * 0.5, f"nur {nachher} von {grenze * 1024} Byte genutzt"
    assert toolbox.QUALITY_MIN <= qualitaet <= toolbox.QUALITY_MAX


def test_unerreichbare_zielgroesse_nimmt_die_kleinste_qualitaet(toolbox, jpeg, tmp_path):
    ziel = tmp_path / "winzig.jpg"
    _vorher, _nachher, qualitaet, erreicht = toolbox.compress_file(
        str(jpeg), str(ziel), target_kb=1)

    assert not erreicht, "1 KB ist fuer dieses Bild nicht zu halten"
    assert qualitaet == toolbox.QUALITY_MIN
    assert ziel.is_file(), "gespeichert wird trotzdem - mit der kleinsten Qualitaet"


def test_grosszuegige_zielgroesse_behaelt_die_beste_qualitaet(toolbox, jpeg, tmp_path):
    ziel = tmp_path / "gross.jpg"
    _vorher, _nachher, qualitaet, erreicht = toolbox.compress_file(
        str(jpeg), str(ziel), target_kb=100000)

    assert erreicht
    assert qualitaet == toolbox.QUALITY_MAX


def test_suche_bleibt_bei_wenigen_durchlaeufen(toolbox, jpeg, tmp_path, monkeypatch):
    # Jeder Durchlauf kodiert das ganze Bild noch einmal. Bei einem Stapel
    # entscheidet diese Zahl darueber, ob der Lauf Minuten oder Stunden dauert.
    echte = toolbox.encoded_size
    versuchte = []

    def gezaehlt(image, fmt, quality, metadata):
        versuchte.append(quality)
        return echte(image, fmt, quality, metadata)

    monkeypatch.setattr(toolbox, "encoded_size", gezaehlt)
    toolbox.compress_file(str(jpeg), str(tmp_path / "klein.jpg"), target_kb=60)

    assert len(versuchte) <= toolbox.TARGET_STEPS + 2, versuchte


def test_zielformate_kennen_eine_qualitaetszahl(toolbox):
    assert set(toolbox.TARGET_FORMATS) <= set(toolbox.QUALITY_FORMATS)


def test_webp_wird_als_zielformat_erkannt(toolbox, tmp_path):
    # Image.format liefert WEBP, nicht WebP. Ein Tippfehler in TARGET_FORMATS
    # wuerde die Zielgroessensuche bei WebP still ueberspringen.
    quelle = tmp_path / "quelle.webp"
    foto((400, 300)).save(quelle, "WebP", quality=95)
    with Image.open(quelle) as bild:
        assert bild.format in toolbox.TARGET_FORMATS


# ----------------------------------------------------------------- Kantenlaenge

def test_kante_wird_nur_verkleinert(toolbox):
    bild = Image.new("RGB", (800, 600))
    assert toolbox.shrink_to_edge(bild, 400).size == (400, 300)
    assert toolbox.shrink_to_edge(bild, 2000) is bild, "kein Vergroessern"
    assert toolbox.shrink_to_edge(bild, 0) is bild, "0 heisst unveraendert"


def test_kantenlaenge_wirkt_auf_die_gespeicherte_datei(toolbox, jpeg, tmp_path):
    ziel = tmp_path / "schmal.jpg"
    toolbox.compress_file(str(jpeg), str(ziel), max_edge=300)
    with Image.open(ziel) as bild:
        assert max(bild.size) == 300


# -------------------------------------------------------------------- Metadaten

def test_metadaten_fallen_ohne_haken_weg(toolbox, tmp_path):
    quelle = tmp_path / "mit_exif.jpg"
    bild = foto((200, 150))
    exif = bild.getexif()
    exif[271] = "Testkamera"
    bild.save(quelle, "JPEG", quality=90, exif=exif)

    ohne = tmp_path / "ohne.jpg"
    toolbox.compress_file(str(quelle), str(ohne), quality=85)
    with Image.open(ohne) as ergebnis:
        assert not ergebnis.getexif(), "Pillow schreibt EXIF nur auf Verlangen mit"

    mit = tmp_path / "mit.jpg"
    toolbox.compress_file(str(quelle), str(mit), quality=85, keep_metadata=True)
    with Image.open(mit) as ergebnis:
        assert ergebnis.getexif().get(271) == "Testkamera"


def test_aufnahmerichtung_wandert_in_die_bildpunkte(toolbox, tmp_path):
    # Ein Hochformat aus dem Telefon ist quer gespeichert und traegt die
    # Drehung nur als EXIF-Marke. Faellt die Marke weg, ohne dass das Bild
    # gedreht wird, liegt es hinterher sichtbar falsch.
    quelle = tmp_path / "hochformat.jpg"
    vorlage = foto((400, 200))
    exif = vorlage.getexif()
    exif[274] = 6                       # 90 Grad im Uhrzeigersinn
    vorlage.save(quelle, "JPEG", quality=95, exif=exif)

    ohne = tmp_path / "ohne.jpg"
    toolbox.compress_file(str(quelle), str(ohne), quality=90)
    with Image.open(ohne) as ergebnis:
        assert not ergebnis.getexif(), "ohne Haken fallen die Metadaten weg"
        assert ergebnis.size == (200, 400), "die Drehung steckt jetzt in den Bildpunkten"

    mit = tmp_path / "mit.jpg"
    toolbox.compress_file(str(quelle), str(mit), quality=90, keep_metadata=True)
    with Image.open(mit) as ergebnis:
        # Mit Metadaten bleibt die Marke - dann darf nicht zusaetzlich gedreht
        # werden, sonst stimmt es zweimal nicht.
        assert ergebnis.getexif().get(274) == 6
        assert ergebnis.size == (400, 200)


# ---------------------------------------------------------- Verlustfreie Formate

def test_png_bleibt_bildpunktgleich(toolbox, tmp_path):
    quelle = tmp_path / "quelle.png"
    vorlage = foto((300, 200))
    vorlage.save(quelle, "PNG")

    ziel = tmp_path / "klein.png"
    toolbox.compress_file(str(quelle), str(ziel), quality=40)
    with Image.open(ziel) as ergebnis:
        assert ergebnis.format == "PNG", "das Format wechselt nie"
        unterschied = ImageChops.difference(ergebnis.convert("RGB"), vorlage)
        assert unterschied.getbbox() is None, "PNG darf keinen Bildpunkt veraendern"


def test_zielgroesse_bei_png_wird_nur_gemeldet(toolbox, tmp_path):
    # PNG kennt keine Qualitaetszahl, die Grenze laesst sich nicht erzwingen.
    # Das Ergebnis sagt das, statt eine Einhaltung zu behaupten.
    quelle = tmp_path / "quelle.png"
    foto((600, 500)).save(quelle, "PNG")

    ziel = tmp_path / "klein.png"
    _vorher, nachher, _qualitaet, erreicht = toolbox.compress_file(
        str(quelle), str(ziel), target_kb=1)

    assert nachher > 1024
    assert not erreicht


def test_speicheroptionen_setzen_qualitaet_nur_wo_sie_wirkt(toolbox):
    assert toolbox.save_options("JPEG", 70, {})["quality"] == 70
    assert toolbox.save_options("JPEG", 70, {})["optimize"] is True
    assert "quality" not in toolbox.save_options("PNG", 70, {})
    assert toolbox.save_options("PNG", 70, {})["optimize"] is True


# ------------------------------------------------------------------- Fehlerwege

def test_format_ohne_komprimierung_wird_gemeldet(toolbox, tmp_path):
    quelle = tmp_path / "quelle.bmp"
    foto((120, 90)).save(quelle, "BMP")
    with pytest.raises(toolbox.UnsupportedFormat):
        toolbox.compress_file(str(quelle), str(tmp_path / "ziel.bmp"))


def test_kaputte_datei_bricht_nicht_still_ab(toolbox, tmp_path):
    quelle = tmp_path / "kaputt.jpg"
    quelle.write_bytes(b"das ist kein Bild")
    with pytest.raises(Exception):  # noqa: B017 - Pillow meldet je Format anders
        toolbox.compress_file(str(quelle), str(tmp_path / "ziel.jpg"))


@pytest.mark.parametrize(("vorher", "nachher", "erwartet"),
                         [(1000, 100, "-90 %"),
                          (1000, 1000, "+0 %"),
                          (100, 150, "+50 %"),
                          (0, 0, "+0 %")])
def test_ersparnis_wird_mit_vorzeichen_angezeigt(toolbox, vorher, nachher, erwartet):
    assert toolbox.delta_text(vorher, nachher) == erwartet


# ------------------------------------------------------------------ Einordnung

def test_modul_steht_hinter_dem_konverter(toolbox):
    # Die Gruppenueberschrift entsteht beim Wechsel von cls.group. Stuende
    # "Komprimieren" nicht direkt hinter dem Konverter, erschiene "Umwandeln"
    # zweimal in der Seitenleiste.
    schluessel = [cls.key for cls in toolbox.ToolboxApp.module_classes]
    assert "compress" in schluessel
    assert schluessel.index("compress") == schluessel.index("convert") + 1


# ------------------------------------------- Mehrere Bilder in einer Datei

def test_animation_wird_nicht_still_verstuemmelt(toolbox, tmp_path):
    # Ohne save_all speichert Pillow nur das erste Bild. Der Dialog meldete
    # dann eine grosse Ersparnis, die aus den fehlenden Bildern stammt.
    quelle = tmp_path / "anim.webp"
    # Die Bilder muessen sich unterscheiden - gleiche fasst Pillow zu einem
    # zusammen, und dann ist es keine Animation mehr.
    zweites = foto((200, 150))
    ImageDraw.Draw(zweites).rectangle((0, 0, 199, 149), fill=(0, 200, 0))
    foto((200, 150)).save(quelle, "WebP", save_all=True, duration=100,
                          append_images=[zweites])

    with Image.open(quelle) as bild:
        assert bild.n_frames == 2, "das Testbild ist keine Animation"
    with pytest.raises(toolbox.MultiFrameImage):
        toolbox.compress_file(str(quelle), str(tmp_path / "ziel.webp"))


def test_mehrseitiges_tiff_wird_uebergangen(toolbox, tmp_path):
    quelle = tmp_path / "scan.tif"
    foto((200, 150)).save(quelle, "TIFF", save_all=True,
                          append_images=[foto((200, 150))])
    with pytest.raises(toolbox.MultiFrameImage):
        toolbox.compress_file(str(quelle), str(tmp_path / "ziel.tif"))


# ----------------------------------------------- Weitere Formate und Zahlen

def test_webp_haelt_die_zielgroesse(toolbox, tmp_path):
    quelle = tmp_path / "quelle.webp"
    foto((900, 700)).save(quelle, "WebP", quality=98)
    ziel = tmp_path / "klein.webp"
    _vorher, nachher, _qualitaet, erreicht = toolbox.compress_file(
        str(quelle), str(ziel), target_kb=25)
    assert erreicht
    assert nachher <= 25 * 1024


def test_tiff_wird_verlustfrei_kleiner(toolbox, tmp_path):
    quelle = tmp_path / "quelle.tif"
    vorlage = foto((600, 450))
    vorlage.save(quelle, "TIFF")                    # ohne Kompression
    ziel = tmp_path / "klein.tif"
    vorher, nachher, _qualitaet, _erreicht = toolbox.compress_file(str(quelle), str(ziel))

    assert nachher < vorher, "LZW sollte etwas bringen"
    with Image.open(ziel) as ergebnis:
        assert ergebnis.info.get("compression") == "tiff_lzw"
        unterschied = ImageChops.difference(ergebnis.convert("RGB"), vorlage)
        assert unterschied.getbbox() is None


def test_jpeg_wird_progressiv_gespeichert(toolbox, tmp_path):
    quelle = tmp_path / "quelle.jpg"
    foto((400, 300)).save(quelle, "JPEG", quality=95)
    ziel = tmp_path / "klein.jpg"
    toolbox.compress_file(str(quelle), str(ziel), quality=80)
    with Image.open(ziel) as bild:
        assert bild.info.get("progressive"), "progressive JPEGs sind etwas kleiner"


def test_png_meldet_keine_qualitaetszahl(toolbox, tmp_path):
    # Sonst stuende im Erfolgsdialog eine Zahl, die nichts bewirkt hat.
    quelle = tmp_path / "quelle.png"
    foto((200, 150)).save(quelle, "PNG")
    _vorher, _nachher, qualitaet, _erreicht = toolbox.compress_file(
        str(quelle), str(tmp_path / "ziel.png"))
    assert qualitaet is None


def test_png_mit_grosszuegiger_grenze_gilt_als_erreicht(toolbox, tmp_path):
    quelle = tmp_path / "quelle.png"
    foto((200, 150)).save(quelle, "PNG")
    _vorher, _nachher, _qualitaet, erreicht = toolbox.compress_file(
        str(quelle), str(tmp_path / "ziel.png"), target_kb=100000)
    assert erreicht


def test_suche_findet_die_hoechste_passende_qualitaet(toolbox, jpeg, tmp_path):
    grenze = 60 * 1024
    _vorher, nachher, qualitaet, _erreicht = toolbox.compress_file(
        str(jpeg), str(tmp_path / "klein.jpg"), target_kb=60)

    assert nachher <= grenze
    if qualitaet < toolbox.QUALITY_MAX:
        # Eine Stufe hoeher darf nicht mehr passen, sonst war die Suche zu
        # zaghaft - genau das war mit sechs Halbierungen gelegentlich so.
        with Image.open(jpeg) as bild:
            groesser = toolbox.encoded_size(bild, "JPEG", qualitaet + 1, {})
        assert groesser > grenze, f"Qualität {qualitaet + 1} hätte auch gepasst"


def test_zielgroesse_rechnet_die_metadaten_mit(toolbox, tmp_path):
    # EXIF und Farbprofil zaehlen zur Dateigroesse. Werden sie bei der Suche
    # vergessen, sprengt die gespeicherte Datei die Grenze.
    quelle = tmp_path / "mit_exif.jpg"
    vorlage = foto((700, 500))
    exif = vorlage.getexif()
    exif[270] = "X" * 10000                         # ImageDescription, kuenstlich gross
    vorlage.save(quelle, "JPEG", quality=95, exif=exif)

    _vorher, nachher, _qualitaet, erreicht = toolbox.compress_file(
        str(quelle), str(tmp_path / "klein.jpg"), target_kb=50, keep_metadata=True)
    assert erreicht
    assert nachher <= 50 * 1024


def test_palettenbild_wird_nicht_grob_verkleinert(toolbox):
    bild = foto((800, 600)).convert("P", palette=Image.Palette.ADAPTIVE)
    klein = toolbox.shrink_to_edge(bild, 400)
    assert klein.mode in ("RGB", "RGBA"), (
        "Pillow verkleinert Palettenbilder sonst stillschweigend mit NEAREST")
    assert klein.size == (400, 300)


# ------------------------------------------------------- Schutz des Originals

def test_gleiche_datei_wird_auch_bei_anderer_schreibweise_erkannt(toolbox, tmp_path):
    datei = tmp_path / "Foto.jpg"
    foto((80, 60)).save(datei, "JPEG")

    assert toolbox.same_file(str(datei), str(datei))
    assert not toolbox.same_file(str(datei), str(tmp_path / "gibt_es_nicht.jpg"))
    if os.path.normcase("A") == os.path.normcase("a"):          # Windows
        anders = str(tmp_path).upper() + os.sep + "FOTO.JPG"
        assert toolbox.same_file(str(datei), anders), (
            "ein reiner Zeichenvergleich wuerde das Original ueberschreiben lassen")


def test_stapel_laesst_die_originale_in_ruhe(toolbox, stapel, tmp_path):
    # Ausgabeordner gleich Quellordner - der haeufigste Griff daneben.
    modul, ergebnisse = stapel
    quelle = tmp_path / "foto.jpg"
    foto((500, 400)).save(quelle, "JPEG", quality=95)
    vorher = quelle.read_bytes()

    modul._batch_worker([str(quelle)], str(tmp_path), auftrag(quality=60))

    assert quelle.read_bytes() == vorher, "das Original wurde angefasst"
    assert (tmp_path / "foto_1.jpg").is_file()
    assert ergebnisse[0]["done"] == 1


# ------------------------------------------------------------ Stapel und Zahlen

def test_stapel_zaehlt_uebersprungen_und_fehlgeschlagen(toolbox, stapel, tmp_path):
    modul, ergebnisse = stapel
    ziel = tmp_path / "ziel"
    ziel.mkdir()
    gut = tmp_path / "gut.jpg"
    foto((400, 300)).save(gut, "JPEG", quality=95)
    bmp = tmp_path / "alt.bmp"
    foto((100, 80)).save(bmp, "BMP")
    kaputt = tmp_path / "kaputt.jpg"
    kaputt.write_bytes(b"das ist kein Bild")

    modul._batch_worker([str(gut), str(bmp), str(kaputt)], str(ziel), auftrag())

    ergebnis = ergebnisse[0]
    assert (ergebnis["done"], ergebnis["skipped"], ergebnis["failed"]) == (1, 1, 1)
    assert len(ergebnis["errors"]) == 2
    assert ergebnis["before"] == gut.stat().st_size, "nur Gelungenes wird summiert"


def test_abbruch_merkt_sich_die_offenen_dateien(toolbox, stapel, tmp_path):
    modul, ergebnisse = stapel
    ziel = tmp_path / "ziel"
    ziel.mkdir()
    dateien = []
    for nummer in range(3):
        pfad = tmp_path / f"bild{nummer}.jpg"
        foto((300, 200)).save(pfad, "JPEG", quality=95)
        dateien.append(str(pfad))
    modul.cancel_event.set()

    modul._batch_worker(dateien, str(ziel), auftrag())

    ergebnis = ergebnisse[0]
    assert ergebnis["cancelled"]
    assert ergebnis["remaining"] == 3
    assert ergebnis["done"] == 0


def test_abbruch_meldet_sich_nicht_als_erfolg(toolbox, modul, monkeypatch):
    gezeigt = []
    monkeypatch.setattr(toolbox.messagebox, "showinfo",
                        lambda titel, text: gezeigt.append(("info", titel, text)))
    monkeypatch.setattr(toolbox.messagebox, "showwarning",
                        lambda titel, text: gezeigt.append(("warnung", titel, text)))
    monkeypatch.setattr(toolbox, "set_text", lambda _widget, text, *a, **k: text)
    modul._set_busy = lambda _busy: None
    modul.progress = types.SimpleNamespace(configure=lambda *_a, **_k: None)
    modul.summary = None
    modul.status = lambda _text: None

    modul._batch_done({"done": 1, "skipped": 0, "failed": 0, "missed": 0, "grown": 0,
                       "before": 2000, "after": 1000, "errors": [],
                       "target": "C:/ziel", "cancelled": True, "remaining": 2})

    art, _titel, text = gezeigt[0]
    assert art == "warnung", "ein abgebrochener Lauf ist kein Erfolg"
    assert "2" in text, "die Zahl der offenen Dateien gehoert in die Meldung"


@pytest.mark.parametrize("eingabe", ["abc", "", "   ", "0", "-5", "nan", "inf", "1e999"])
def test_unbrauchbare_zahl_meldet_sich(toolbox, modul, monkeypatch, eingabe):
    # "inf" und "1e999" werfen OverflowError, nicht ValueError - ohne den
    # zweiten Zweig passierte beim Klick gar nichts.
    meldungen = []
    monkeypatch.setattr(toolbox.messagebox, "showerror",
                        lambda titel, text: meldungen.append(titel))
    assert modul._positive_number(Feld(eingabe), "egal") is None
    assert len(meldungen) == 1


@pytest.mark.parametrize(("eingabe", "erwartet"), [("1", 1), ("12", 12), ("12.9", 12)])
def test_brauchbare_zahl_kommt_durch(toolbox, modul, eingabe, erwartet):
    assert modul._positive_number(Feld(eingabe), "egal") == erwartet


def test_einstellungen_ignorieren_felder_ohne_haken(toolbox, modul):
    modul.use_target, modul.limit_edge = Feld(False), Feld(False)
    modul.target_kb, modul.max_edge = Feld("Unsinn"), Feld("auch Unsinn")
    modul.quality, modul.keep_metadata = Feld(80), Feld(False)

    assert modul._settings() == {"quality": 80, "target_kb": 0, "max_edge": 0,
                                 "keep_metadata": False}


def test_einstellungen_brechen_bei_fehleingabe_ab(toolbox, modul, monkeypatch):
    meldungen = []
    monkeypatch.setattr(toolbox.messagebox, "showerror",
                        lambda titel, text: meldungen.append(titel))
    modul.use_target, modul.limit_edge = Feld(True), Feld(True)
    modul.target_kb, modul.max_edge = Feld("abc"), Feld("auch Unsinn")
    modul.quality, modul.keep_metadata = Feld(80), Feld(False)

    assert modul._settings() is None
    assert len(meldungen) == 1, "nach dem ersten Fehler wird nicht weitergeprueft"
