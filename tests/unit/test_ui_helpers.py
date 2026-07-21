"""Unit-Tests für reine Hilfsfunktionen der Oberfläche."""

from framework_mvp.ui.helpers import liste_als_mehrzeiliger_text, mehrzeiliger_text_als_liste


def test_mehrzeiliger_text_wird_in_liste_umgewandelt() -> None:
    """Jede befüllte Zeile ergibt einen bereinigten Eintrag."""
    assert mehrzeiliger_text_als_liste("Ada\nGrace") == ("Ada", "Grace")


def test_leere_zeilen_werden_entfernt() -> None:
    """Leere und nur aus Leerzeichen bestehende Zeilen entfallen."""
    assert mehrzeiliger_text_als_liste("Ada\n\n   \nGrace") == ("Ada", "Grace")


def test_reihenfolge_und_duplikate_bleiben_erhalten() -> None:
    """Die Eingabereihenfolge wird nicht sortiert oder dedupliziert."""
    assert mehrzeiliger_text_als_liste("Grace\nAda\nGrace") == (
        "Grace",
        "Ada",
        "Grace",
    )


def test_liste_wird_in_mehrzeiligen_text_umgewandelt() -> None:
    """Listeneinträge werden durch genau einen Zeilenumbruch verbunden."""
    assert liste_als_mehrzeiliger_text(("Ada", "Grace")) == "Ada\nGrace"


def test_roundtrip_von_liste_zu_text_zu_liste() -> None:
    """Eine bereinigte Liste übersteht beide Umwandlungen unverändert."""
    werte = ("Durchlaufzeit", "Bestand", "Durchlaufzeit")

    assert mehrzeiliger_text_als_liste(liste_als_mehrzeiliger_text(werte)) == werte
