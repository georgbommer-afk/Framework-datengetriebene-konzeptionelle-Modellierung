"""Fachliche Ausnahmen der Projektverwaltung."""


class Domaenenfehler(ValueError):
    """Basisklasse für ungültige fachliche Eingaben."""


class UngueltigeProjektbezeichnung(Domaenenfehler):
    """Die Projektbezeichnung ist nach der Bereinigung leer."""


class UngueltigerBetrachtungszeitraum(Domaenenfehler):
    """Das Ende des Betrachtungszeitraums liegt vor dessen Beginn."""


class UnvollstaendigerUntersuchungsauftrag(Domaenenfehler):
    """Ein unvollständiger Auftrag wurde mit einem unzulässigen Status kombiniert."""


class UngueltigerZeitstempel(Domaenenfehler):
    """Ein Projektzeitstempel ist nicht zeitzonenbewusst oder zeitlich inkonsistent."""


class ProjektNichtGefunden(Domaenenfehler):
    """Das angeforderte Projekt ist nicht vorhanden."""
