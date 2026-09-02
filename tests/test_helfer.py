"""Prueft die kleinen Hilfsfunktionen, die ueberall benutzt werden."""

import pytest


@pytest.mark.parametrize(
    ("bytes_", "erwartet"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024 * 1024, "1.0 MB"),
        (1024 * 1024 * 1024, "1.0 GB"),
        (5 * 1024 * 1024 * 1024, "5.0 GB"),
    ],
)
def test_human_size(toolbox, bytes_, erwartet):
    assert toolbox.human_size(bytes_) == erwartet


def test_unique_path_laesst_freie_namen_unveraendert(toolbox, tmp_path):
    ziel = tmp_path / "bild.jpg"
    assert toolbox.unique_path(str(ziel)) == str(ziel)


def test_unique_path_zaehlt_hoch(toolbox, tmp_path):
    (tmp_path / "bild.jpg").write_bytes(b"")
    erster = toolbox.unique_path(str(tmp_path / "bild.jpg"))
    assert erster.endswith("bild_1.jpg")

    (tmp_path / "bild_1.jpg").write_bytes(b"")
    zweiter = toolbox.unique_path(str(tmp_path / "bild.jpg"))
    assert zweiter.endswith("bild_2.jpg")


def test_unique_path_erhaelt_die_endung(toolbox, tmp_path):
    (tmp_path / "archiv.tar.gz").write_bytes(b"")
    neu = toolbox.unique_path(str(tmp_path / "archiv.tar.gz"))
    assert neu.endswith("archiv.tar_1.gz")


@pytest.mark.parametrize(
    ("a", "b", "abstand"),
    [
        (0b0000, 0b0000, 0),
        (0b0001, 0b0000, 1),
        (0b1111, 0b0000, 4),
        (0b1010, 0b0101, 4),
        (0b1010, 0b1011, 1),
    ],
)
def test_hamming(toolbox, a, b, abstand):
    assert toolbox.hamming(a, b) == abstand


def test_md5_of_liest_die_datei(toolbox, tmp_path):
    datei = tmp_path / "inhalt.bin"
    datei.write_bytes(b"Bild-Toolbox")
    # Bekannter MD5 von b"Bild-Toolbox"
    import hashlib

    assert toolbox.md5_of(str(datei)) == hashlib.md5(b"Bild-Toolbox").hexdigest()


def test_md5_of_meldet_fehlende_dateien(toolbox, tmp_path):
    # md5_of reicht Datei-Fehler bewusst durch - die Aufrufer fangen sie ab.
    with pytest.raises(OSError):
        toolbox.md5_of(str(tmp_path / "gibt-es-nicht.bin"))


def test_md5_of_liest_grosse_dateien_blockweise(toolbox, tmp_path):
    import hashlib

    daten = b"x" * (3 * 1024 * 1024 + 17)
    datei = tmp_path / "gross.bin"
    datei.write_bytes(daten)
    assert toolbox.md5_of(str(datei)) == hashlib.md5(daten).hexdigest()


def test_config_wird_gelesen_und_geschrieben(toolbox, tmp_path, monkeypatch):
    ziel = tmp_path / "bild-toolbox.json"
    monkeypatch.setattr(toolbox, "config_path", lambda: str(ziel))

    assert toolbox.load_config() == {}
    toolbox.save_config({"language": "en", "theme": "dark"})
    assert toolbox.load_config() == {"language": "en", "theme": "dark"}


def test_kaputte_config_stuerzt_nicht_ab(toolbox, tmp_path, monkeypatch):
    ziel = tmp_path / "bild-toolbox.json"
    ziel.write_text("{kein gueltiges JSON", encoding="utf-8")
    monkeypatch.setattr(toolbox, "config_path", lambda: str(ziel))

    assert toolbox.load_config() == {}
