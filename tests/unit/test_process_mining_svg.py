"""Tests für sichere In-Memory-SVG-Verarbeitung und Streamlit-Übergabe."""

import pytest
from graphviz import Digraph

from framework_mvp.application.process_mining.svg import (
    UngueltigesSvg,
    validiere_svg_bytes,
    validiere_svg_text,
)
from framework_mvp.ui.pages import process_mining


def test_graphviz_pipe_liefert_dekodierbare_svg_bytes() -> None:
    """Der lokale Python-Graphviz-Aufruf liefert vollständiges UTF-8-SVG."""
    graph = Digraph()
    graph.edge("A", "B")
    svg_bytes = graph.pipe(format="svg")
    assert isinstance(svg_bytes, bytes)
    svg_text = validiere_svg_bytes(svg_bytes)
    assert isinstance(svg_text, str)
    assert "<svg" in svg_text


@pytest.mark.parametrize(
    "wert",
    (
        b"",
        b"\xff",
        b"digraph { A -> B }",
        b"<html></html>",
        b"<svg",
    ),
)
def test_ungueltige_svg_ausgaben_werden_abgelehnt(wert: bytes) -> None:
    """Leere, nicht dekodierbare, DOT- und unvollständige Ausgaben sind ungültig."""
    with pytest.raises(UngueltigesSvg):
        validiere_svg_bytes(wert)


def test_svg_text_wird_ohne_bytesio_an_interaktiven_viewer_uebergeben(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Die UI reicht validierten XML-Text und keinen Binärpuffer an st.image."""
    graph = Digraph()
    graph.node("A")
    erwartet = validiere_svg_bytes(graph.pipe(format="svg"))
    aufrufe: list[object] = []

    def viewer(wert: object, _beschriftung: str) -> None:
        aufrufe.append(wert)

    monkeypatch.setattr(process_mining, "svg_zoom_viewer", viewer)
    assert process_mining._zeige_svg(erwartet.encode(), "Testgrafik")
    assert aufrufe == [erwartet]
    assert isinstance(aufrufe[0], str)
    assert validiere_svg_text(aufrufe[0]) == erwartet
