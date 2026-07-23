"""Validierung und Dekodierung von Graphviz-SVG-Ausgaben."""

from xml.etree import ElementTree


class UngueltigesSvg(ValueError):
    """Technischer Fehler für eine unbrauchbare SVG-Ausgabe."""


def validiere_svg_bytes(svg_bytes: bytes) -> str:
    """Dekodiert vollständige SVG-Bytes und prüft das XML-Wurzelelement."""
    if not svg_bytes:
        raise UngueltigesSvg("Die SVG-Ausgabe ist leer.")
    try:
        svg_text = svg_bytes.decode("utf-8")
    except UnicodeDecodeError as fehler:
        raise UngueltigesSvg("Die SVG-Ausgabe ist nicht als UTF-8 dekodierbar.") from fehler
    return validiere_svg_text(svg_text)


def validiere_svg_text(svg_text: str) -> str:
    """Prüft SVG-Text unabhängig von einer optionalen XML-Deklaration."""
    bereinigt = svg_text.lstrip()
    if not bereinigt:
        raise UngueltigesSvg("Die SVG-Ausgabe ist leer.")
    if bereinigt.lower().startswith(("digraph ", "graph ")):
        raise UngueltigesSvg("Die Ausgabe enthält DOT-Quelltext statt SVG.")
    try:
        wurzel = ElementTree.fromstring(bereinigt)
    except ElementTree.ParseError as fehler:
        raise UngueltigesSvg("Die SVG-Ausgabe ist kein vollständiges XML-Dokument.") from fehler
    if wurzel.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise UngueltigesSvg("Die XML-Ausgabe besitzt kein SVG-Wurzelelement.")
    return svg_text
