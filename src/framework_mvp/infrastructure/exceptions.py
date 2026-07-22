"""Technische Ausnahmen der Infrastrukturschicht."""


class NichtUnterstuetzteSchemaversion(RuntimeError):
    """Die Datenbank verwendet eine neuere, nicht unterstützte Schemaversion."""


class Importintegritaetsfehler(RuntimeError):
    """Gespeicherte Importmetadaten und Artefakte sind nicht konsistent."""
