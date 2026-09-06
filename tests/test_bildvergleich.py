"""Schuetzt die Korrekturen am Bild-Vergleich.

Diese Tests lesen den Quelltext, statt eine Oberflaeche zu bauen: Tk braucht
dafuer einen Bildschirm, und die CI laeuft auch auf Linux- und macOS-Laeufern
ohne einen solchen. Geprueft wird deshalb, dass die Konstruktion erhalten
bleibt, an der der Fehler hing.
"""

from pathlib import Path

import pytest

QUELLE = Path(__file__).resolve().parent.parent / "Bild-Toolbox.pyw"


@pytest.fixture(scope="module")
def vergleich_quelltext():
    """Nur der Abschnitt der Klasse CompareModule."""
    text = QUELLE.read_text(encoding="utf-8")
    start = text.index("class CompareModule")
    ende = text.index("\nclass ", start + 1)
    return text[start:ende]


def test_bildflaeche_gibt_ihre_groesse_nicht_nach_oben_weiter(vergleich_quelltext):
    # Ein tk.Label fordert so viel Platz an, wie sein Bild gross ist. Ohne den
    # Halterahmen mit abgeschalteter Weitergabe wandert diese Anforderung nach
    # oben und draengt die Statusleiste aus dem Fenster - beim Tauschen
    # schaukelte sich das mit jedem Wechsel weiter auf.
    assert "holder.pack_propagate(False)" in vergleich_quelltext, (
        "Der Halterahmen um das Bild-Label muss pack_propagate(False) behalten, "
        "sonst waechst der Rahmen mit jedem Bild und die Statusleiste "
        "verschwindet aus dem sichtbaren Bereich."
    )


def test_groesse_wird_am_halterahmen_gemessen(vergleich_quelltext):
    fit = vergleich_quelltext[vergleich_quelltext.index("def _fit("):]
    fit = fit[:fit.index("\n    def ", 1)]
    assert "holder.winfo_width()" in fit and "holder.winfo_height()" in fit, (
        "_fit muss den Halterahmen messen. Das Label darin traegt die Groesse "
        "seines eigenen Bildes und wuerde sich selbst messen."
    )
    assert "label.winfo_width()" not in fit, (
        "_fit darf nicht mehr das Bild-Label messen - dessen Groesse haengt am "
        "zuletzt gesetzten Bild."
    )


def test_nachskalieren_wird_je_seite_geplant(vergleich_quelltext):
    # Ein gemeinsamer Auftrag fuer beide Seiten hob sich gegenseitig auf:
    # meldete rechts eine Groessenaenderung, verfiel der Auftrag von links.
    assert "_resize_jobs" in vergleich_quelltext
    assert "self._resize_job " not in vergleich_quelltext, (
        "Der gemeinsame Auftrag _resize_job ist durch _resize_jobs je Seite ersetzt."
    )


def test_tauschen_liest_die_dateien_nicht_neu(vergleich_quelltext):
    swap = vergleich_quelltext[vergleich_quelltext.index("def swap("):]
    swap = swap[:swap.index("\n    def ", 1)]
    assert "self.load(" not in swap, (
        "swap() darf nicht load() aufrufen: Das las jede Datei neu von der "
        "Platte und berechnete die MD5-Summe erneut."
    )
    assert "_fit" in swap, "swap() muss die Anzeige neu einpassen."


def test_statusmeldung_beim_tauschen_ist_uebersetzt(toolbox):
    uebersetzer = toolbox.Translator("en")
    assert uebersetzer("Seiten getauscht.") == "Sides swapped."


@pytest.mark.parametrize("methode", ["_fit", "_schedule_fit", "swap", "clear", "load"])
def test_methoden_sind_vorhanden(toolbox, methode):
    assert hasattr(toolbox.CompareModule, methode)
