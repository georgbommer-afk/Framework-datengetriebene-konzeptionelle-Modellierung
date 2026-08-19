"""Framework-Schritt 9: K mit Domänenwissen ergänzen und fachlich validieren."""

from typing import Any
from uuid import UUID, uuid4

import streamlit as st

from framework_mvp.application.modellvalidierung_service import (
    ModellvalidierungService,
)
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    BehandlungOffenerEintrag,
    Gesamtvalidierungsstatus,
    ModellbestandteilId,
    Offenheitsentscheidung,
    Offenheitskategorie,
    ZusaetzlicheModellanpassung,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.navigation import framework_bereich_oeffnen


def _aktive_ids() -> tuple[UUID, UUID, UUID, UUID] | None:
    try:
        return (
            UUID(str(st.session_state.get("aktuelles_projekt_id"))),
            UUID(str(st.session_state.get("aktuelle_modellableitungs_id"))),
            UUID(str(st.session_state.get("aktuelle_k_id"))),
            UUID(str(st.session_state.get("aktuelle_o_id"))),
        )
    except (TypeError, ValueError, AttributeError):
        return None


def _bestandteile_anzeigen(k: dict[str, Any]) -> None:
    st.subheader("2. Übersicht der elf Modellbestandteile")
    st.caption(
        "Die datengetrieben übernommenen Informationen aus K bleiben unverändert und "
        "schreibgeschützt sichtbar."
    )
    for index, bestandteil in enumerate(k["modellbestandteile"], 1):
        with st.expander(f"{index}. {bestandteil['bezeichnung']}"):
            st.write(f"**Status in K:** {bestandteil['status']}")
            st.write(
                "**Quellen:** " + (", ".join(bestandteil.get("verwendete_quellen", [])) or "keine")
            )
            if not bestandteil.get("informationen"):
                st.info("Keine direkt aus den Eingangsartefakten übernommene Information.")
            for information in bestandteil.get("informationen", []):
                st.markdown(
                    f"**{information['herkunftsartefakt']} · `{information['strukturreferenz']}`**"
                )
                st.json(information["wert"], expanded=False)


def _technische_details(basis: Any) -> None:
    with st.expander("Technische Details", expanded=False):
        st.json(
            {
                "modellableitungs_id": str(basis.ableitung.modellableitungs_id),
                "projekt_id": str(basis.ableitung.projekt_id),
                "k_id": str(basis.ableitung.k_id),
                "k_sha256": basis.ableitung.k_sha256,
                "o_id": str(basis.ableitung.o_id),
                "o_sha256": basis.ableitung.o_sha256,
                "eingabefingerabdruck": basis.eingabefingerabdruck,
            },
            expanded=False,
        )


def _menschliche_eingaben(
    k: dict[str, Any], o: dict[str, Any], *, widget_praefix: str
) -> tuple[
    tuple[BehandlungOffenerEintrag, ...],
    tuple[ZusaetzlicheModellanpassung, ...],
    Gesamtvalidierungsstatus,
    str,
    dict[str, Any],
]:
    st.subheader("3. Offene oder fachlich unsichere Punkte bearbeiten")
    behandlungen: list[BehandlungOffenerEintrag] = []
    roh_behandlungen: list[dict[str, str]] = []
    entscheidungsoptionen = [
        "noch_nicht_behandelt",
        *[wert.value for wert in Offenheitsentscheidung],
    ]
    for index, offen in enumerate(o.get("offene_eintraege", []), 1):
        st.markdown(
            f"**{index}. {offen['bestandteil_id']} · {offen['kategorie']}**  \n"
            f"{offen['begruendung']}"
        )
        entscheidung = st.selectbox(
            "Fachliche Entscheidung",
            entscheidungsoptionen,
            key=(f"{widget_praefix}_schritt9_entscheidung_{offen['offener_eintrag_id']}"),
            format_func=lambda wert: {
                "noch_nicht_behandelt": "Noch nicht behandelt",
                "bestätigt": "bestätigt",
                "ergänzt_oder_angepasst": "ergänzt oder angepasst",
                "nicht_anwendbar": "nicht anwendbar",
            }[wert],
        )
        ergaenzung = st.text_area(
            "Fachliche Ergänzung beziehungsweise Begründung",
            key=(f"{widget_praefix}_schritt9_ergaenzung_{offen['offener_eintrag_id']}"),
        ).strip()
        roh_behandlungen.append(
            {
                "offener_eintrag_id": offen["offener_eintrag_id"],
                "entscheidung": entscheidung,
                "ergaenzung": ergaenzung,
            }
        )
        if entscheidung != "noch_nicht_behandelt" and ergaenzung:
            behandlungen.append(
                BehandlungOffenerEintrag(
                    offen["offener_eintrag_id"],
                    ModellbestandteilId(offen["bestandteil_id"]),
                    Offenheitskategorie(offen["kategorie"]),
                    offen["begruendung"],
                    Offenheitsentscheidung(entscheidung),
                    ergaenzung,
                )
            )
    if not o.get("offene_eintraege"):
        st.success("O enthält keine offenen Einträge; es ist keine Einzelbehandlung erforderlich.")

    st.subheader("4. Fachliche Gesamtvalidierung")
    bezeichnungen = {
        wert["bestandteil_id"]: wert["bezeichnung"] for wert in k["modellbestandteile"]
    }
    angepasste_ids = st.multiselect(
        "Zusätzlich fachlich anzupassende Bestandteile",
        list(bezeichnungen),
        format_func=lambda wert: bezeichnungen[wert],
        key=f"{widget_praefix}_zusaetzliche_bestandteile",
        help=(
            "Hier können bei Anpassungsbedarf auch zuvor nicht offene Bestandteile ergänzt "
            "werden. K selbst wird dadurch nicht überschrieben."
        ),
    )
    anpassungen: list[ZusaetzlicheModellanpassung] = []
    roh_anpassungen: list[dict[str, str]] = []
    for bestandteil_id in angepasste_ids:
        inhalt = st.text_area(
            f"Fachlicher Inhalt · {bezeichnungen[bestandteil_id]}",
            key=f"schritt9_anpassung_inhalt_{bestandteil_id}",
        ).strip()
        begruendung = st.text_input(
            f"Begründung · {bezeichnungen[bestandteil_id]}",
            key=f"schritt9_anpassung_begruendung_{bestandteil_id}",
        ).strip()
        roh_anpassungen.append(
            {"bestandteil_id": bestandteil_id, "inhalt": inhalt, "begruendung": begruendung}
        )
        if inhalt and begruendung:
            anpassungen.append(
                ZusaetzlicheModellanpassung(
                    ModellbestandteilId(bestandteil_id), inhalt, begruendung
                )
            )
    status = Gesamtvalidierungsstatus(
        st.radio(
            "Status der fachlichen Gesamtvalidierung",
            [
                Gesamtvalidierungsstatus.ANPASSUNGSBEDARF.value,
                Gesamtvalidierungsstatus.FACHLICH_VALIDIERT.value,
            ],
            format_func=lambda wert: {
                "anpassungsbedarf": "Anpassungsbedarf",
                "fachlich_validiert": "fachlich validiert",
            }[wert],
        )
    )
    vermerk = st.text_area("Optionaler Validierungsvermerk").strip()
    roh = {
        "behandlungen": roh_behandlungen,
        "anpassungen": roh_anpassungen,
        "gesamtvalidierungsstatus": status.value,
        "validierungsvermerk": vermerk,
    }
    return tuple(behandlungen), tuple(anpassungen), status, vermerk, roh


def _gespeichertes_k_stern(
    service: ModellvalidierungService,
    validierungslauf_id: UUID,
    projekt_id: UUID,
) -> None:
    validierung, k_stern = service.laden(validierungslauf_id)
    if validierung.projekt_id != projekt_id:
        raise Domaenenfehler("Der aktive Validierungslauf gehört nicht zum aktiven Projekt.")
    st.success("K* ist fachlich validiert und gespeichert.")
    st.download_button(
        "Validiertes konzeptionelles Modell K* herunterladen",
        service.k_stern_download_laden(validierungslauf_id),
        "validiertes-konzeptionelles-modell-k-stern.json",
        "application/json",
    )


def _fehlende_pflichtentscheidungen(
    k: dict[str, Any], o: dict[str, Any], roh: dict[str, Any]
) -> list[str]:
    """Benennt unvollständige fachliche Eingaben mit ihrem sichtbaren Feldnamen."""
    fehlend: list[str] = []
    offene_eintraege = o.get("offene_eintraege", [])
    for index, (offen, behandlung) in enumerate(
        zip(offene_eintraege, roh["behandlungen"], strict=True), 1
    ):
        bezug = f"Offener Punkt {index} ({offen['bestandteil_id']})"
        if behandlung["entscheidung"] == "noch_nicht_behandelt":
            fehlend.append(f"{bezug}: Fachliche Entscheidung")
        if not behandlung["ergaenzung"]:
            fehlend.append(f"{bezug}: Fachliche Ergänzung beziehungsweise Begründung")
    bezeichnungen = {
        wert["bestandteil_id"]: wert["bezeichnung"] for wert in k["modellbestandteile"]
    }
    for anpassung in roh["anpassungen"]:
        bezeichnung = bezeichnungen.get(anpassung["bestandteil_id"], anpassung["bestandteil_id"])
        if not anpassung["inhalt"]:
            fehlend.append(f"{bezeichnung}: Fachlicher Inhalt")
        if not anpassung["begruendung"]:
            fehlend.append(f"{bezeichnung}: Begründung")
    if roh["gesamtvalidierungsstatus"] != Gesamtvalidierungsstatus.FACHLICH_VALIDIERT.value:
        fehlend.append("Status der fachlichen Gesamtvalidierung: fachlich validiert")
    return fehlend


def zeige_modellvalidierung_seite(
    projekt_service: ProjektService, service: ModellvalidierungService
) -> None:
    """Setzt Algorithmus 9 ausschließlich mit K, O und menschlichem Domänenwissen um."""
    st.header("9 Modell ergänzen und validieren")
    ids = _aktive_ids()
    if ids is None:
        st.error("Schritt 9 benötigt die aktiven IDs des gespeicherten K/O-Paars aus Schritt 8.")
        if st.button("Zurück zu Schritt 8: Modellbestandteile ableiten"):
            framework_bereich_oeffnen(schritt=8)
        return
    projekt_id, modellableitungs_id, k_id, o_id = ids
    if projekt_service.projekt_laden(projekt_id) is None:
        st.error("Das aktive Projekt wurde nicht gefunden.")
        return
    gespeicherte_id = st.session_state.get("aktuelle_validierungslauf_id")
    if gespeicherte_id:
        try:
            _gespeichertes_k_stern(service, UUID(str(gespeicherte_id)), projekt_id)
        except (ValueError, Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            st.error(f"Das gespeicherte K* ist nicht mehr gültig: {fehler}")
        return
    try:
        basis = service.grundlage_laden(
            projekt_id,
            modellableitungs_id,
            erwartete_k_id=k_id,
            erwartete_o_id=o_id,
        )
    except (Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
        st.error(f"K und O sind nicht mehr gültig: {fehler}")
        if st.button("Zurück zu Schritt 8: Modellbestandteile ableiten"):
            framework_bereich_oeffnen(schritt=8, projekt_id=projekt_id)
        return
    st.subheader("1. Validierte Eingaben K und O")
    st.success(
        "K und O wurden einschließlich Projektbindung, Versionen, Prüfsummen und "
        "gegenseitiger Referenz erneut validiert."
    )
    _bestandteile_anzeigen(basis.k)
    _technische_details(basis)
    behandlungen, anpassungen, status, vermerk, roh = _menschliche_eingaben(
        basis.k,
        basis.o,
        widget_praefix=f"schritt9_{projekt_id}_{modellableitungs_id}",
    )
    st.subheader("5. K* speichern und zu Schritt 10")
    if st.button(
        "Eingaben validieren, K* speichern und zu Schritt 10",
        type="primary",
    ):
        fehlend = _fehlende_pflichtentscheidungen(basis.k, basis.o, roh)
        if fehlend:
            st.error("Bitte vervollständigen Sie folgende Pflichtentscheidungen:")
            for feld in fehlend:
                st.write(f"- {feld}")
            return
        try:
            arbeitsfassung = service.arbeitsfassung_erstellen(
                projekt_id=projekt_id,
                modellableitungs_id=modellableitungs_id,
                erwartete_k_id=k_id,
                erwartete_o_id=o_id,
                behandlungen=behandlungen,
                zusaetzliche_anpassungen=anpassungen,
                gesamtvalidierungsstatus=status,
                validierungsvermerk=vermerk,
            )
            if not arbeitsfassung.finalisierbar:
                st.error(
                    "Die Eingaben sind noch nicht finalisierbar. Prüfen Sie alle offenen "
                    "Punkte und den Status der fachlichen Gesamtvalidierung."
                )
                return
            validierung = service.speichern(
                arbeitsfassung,
                validierungslauf_id=uuid4(),
                k_stern_id=uuid4(),
                fachlich_bestaetigt=True,
            )
            st.session_state.aktuelle_validierungslauf_id = str(validierung.validierungslauf_id)
            st.session_state.aktuelle_k_stern_id = str(validierung.k_stern_id)
            st.session_state.pop("schritt10_ausgabe", None)
            st.session_state.pop("schritt10_ausgabe_signatur", None)
            framework_bereich_oeffnen(schritt=10, projekt_id=projekt_id)
        except (ValueError, Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            st.error(f"K* konnte nicht gespeichert werden: {fehler}")
