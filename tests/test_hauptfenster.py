"""Seitenleiste und Statusleiste behalten ihre Groesse, egal welcher Reiter offen ist.

Tk verteilt den Platz eines Fensters in der Reihenfolge, in der gepackt wurde.
Wurde der Inhaltsbereich vor der Statusleiste gepackt, bekam ein Reiter, der
mehr Hoehe verlangte als vorhanden, diese zuerst. Die Statusleiste schrumpfte
dann (Icon-Extraktor) oder verschwand ganz (Duplikat-Finder, Aehnliche Bilder,
Batch-Umbenennung), und die Seitenleiste wurde laenger.

Die Oberflaeche selbst laesst sich in der CI nicht bauen - dort gibt es keinen
Bildschirm. Geprueft wird deshalb die Pack-Reihenfolge im Quelltext.
"""

import re
from pathlib import Path

QUELLE = Path(__file__).resolve().parent.parent / "Bild-Toolbox.pyw"


def test_statusleiste_wird_vor_dem_inhalt_gepackt():
    text = QUELLE.read_text(encoding="utf-8")
    beginn = text.index("    def _build_layout(")
    layout = text[beginn:text.index("\n    def ", beginn + 1)]

    aufruf = re.search(r"status_bar\.pack\(([^)]*)\)", layout)
    assert aufruf, "Die Statusleiste wird in _build_layout nicht mehr gepackt?"
    assert "before=outer" in aufruf.group(1), (
        "Die Statusleiste muss mit before=outer vor dem Inhaltsbereich gepackt "
        "werden - sonst draengt ein hoher Reiter sie aus dem Fenster."
    )
