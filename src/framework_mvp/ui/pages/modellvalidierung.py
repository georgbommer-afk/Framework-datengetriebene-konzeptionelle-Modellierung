"""Framework-Schritt 9: K mit Domänenwissen ergänzen und fachlich validieren."""

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import streamlit as st

from framework_mvp.application.modellvalidierung_service import (
    ModellvalidierungService,
    Validierungsarbeitsfassung,
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


def _signatur(wert: Any) -> str:
    return hashlib.sha256(
        json.dumps(wert, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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
                st.caption(
                    f"Artefakt `{information['herkunftsartefakt_id']}` · "
                    f"SHA-256 `{information['herkunftsartefakt_sha256']}`"
                )


def _sichtbare_aktivitaeten(k: dict[str, Any]) -> tuple[str, ...]:
    for bestandteil in k.get("modellbestandteile", []):
        if bestandteil.get("bestandteil_id") != ModellbestandteilId.AKTIVITAETEN.value:
            continue
        for information in bestandteil.get("informationen", []):
            if information.get("strukturreferenz") == "sichtbare_aktivitaeten":
                return tuple(str(wert) for wert in information.get("wert", []) if str(wert))
    return ()


def _hat_kanonische_ressourceninformation(k: dict[str, Any]) -> bool:
    return any(
        information.get("herkunftsartefakt") == "E*"
        and information.get("strukturreferenz") == "schema.resource"
        for bestandteil in k.get("modellbestandteile", [])
        if bestandteil.get("bestandteil_id") == ModellbestandteilId.RESSOURCEN.value
        for information in bestandteil.get("informationen", [])
    )


def _ressourcenzuordnung_eingeben(
    k: dict[str, Any], offen: dict[str, Any], *, widget_praefix: str
) -> tuple[BehandlungOffenerEintrag | None, dict[str, Any]]:
    """Erfasst die bewusst menschliche Aktivität-Ressourcen-Zuordnung reproduzierbar."""
    zuordnungen: list[dict[str, Any]] = []
    vollstaendig = True
    for aktivitaet in _sichtbare_aktivitaeten(k):
        schluessel = hashlib.sha256(aktivitaet.encode()).hexdigest()[:12]
        entscheidung = st.radio(
            f"{aktivitaet}",
            ["zuordnen", "offen_lassen"],
            key=f"{widget_praefix}_ressource_status_{schluessel}",
            format_func=lambda wert: {
                "zuordnen": "Ressourcen zuordnen",
                "offen_lassen": "Bewusst offen lassen",
            }[wert],
            horizontal=True,
        )
        ressourcen: list[str] = []
        if entscheidung == "zuordnen":
            rohwert = st.text_input(
                f"Ressourcen für {aktivitaet} (kommagetrennt)",
                key=f"{widget_praefix}_ressourcen_{schluessel}",
            )
            ressourcen = list(
                dict.fromkeys(wert.strip() for wert in rohwert.split(",") if wert.strip())
            )
            vollstaendig = vollstaendig and bool(ressourcen)
        zuordnungen.append(
            {
                "aktivitaet": aktivitaet,
                "ressourcen": ressourcen,
                "status": "zugeordnet" if ressourcen else "bewusst_offen",
                "menschliche_entscheidung": True,
            }
        )
    dokumentation = {"aktivitaet_ressourcen": zuordnungen}
    if not zuordnungen or not vollstaendig:
        return None, dokumentation
    return (
        BehandlungOffenerEintrag(
            offen["offener_eintrag_id"],
            ModellbestandteilId.RESSOURCEN,
            Offenheitskategorie(offen["kategorie"]),
            offen["begruendung"],
            Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST,
            json.dumps(dokumentation, ensure_ascii=False, sort_keys=True),
        ),
        dokumentation,
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
        if offen[
            "bestandteil_id"
        ] == ModellbestandteilId.RESSOURCEN.value and not _hat_kanonische_ressourceninformation(k):
            behandlung, dokumentation = _ressourcenzuordnung_eingeben(
                k, offen, widget_praefix=widget_praefix
            )
            roh_behandlungen.append(
                {
                    "offener_eintrag_id": offen["offener_eintrag_id"],
                    "entscheidung": (
                        Offenheitsentscheidung.ERGAENZT_ODER_ANGEPASST.value
                        if behandlung
                        else "noch_nicht_behandelt"
                    ),
                    "ergaenzung": json.dumps(dokumentation, ensure_ascii=False, sort_keys=True),
                }
            )
            if behandlung is not None:
                behandlungen.append(behandlung)
            continue
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
    st.success(f"K* ist fachlich validiert und gespeichert: `{k_stern['k_stern_id']}`.")
    st.download_button(
        "Validiertes konzeptionelles Modell K* herunterladen",
        service.k_stern_download_laden(validierungslauf_id),
        f"{validierung.k_stern_id}.k-star.json",
        "application/json",
    )
    if st.button("Weiter zu Schritt 10: Konzeptionelles Modell ausgeben", type="primary"):
        framework_bereich_oeffnen(schritt=10, projekt_id=projekt_id)


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
        f"K `{basis.ableitung.k_id}` und O `{basis.ableitung.o_id}` wurden einschließlich "
        "Projektbindung, Versionen, Prüfsummen und gegenseitiger Referenz erneut validiert."
    )
    st.caption(
        f"Modellableitung `{modellableitungs_id}` · Eingabefingerabdruck "
        f"`{basis.eingabefingerabdruck}`"
    )
    _bestandteile_anzeigen(basis.k)
    behandlungen, anpassungen, status, vermerk, roh = _menschliche_eingaben(
        basis.k,
        basis.o,
        widget_praefix=f"schritt9_{projekt_id}_{modellableitungs_id}",
    )
    aktuelle_signatur = _signatur(
        {"eingabe": basis.eingabefingerabdruck, "menschliche_eingaben": roh}
    )
    if st.button("Arbeitsfassung prüfen"):
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
            st.session_state.schritt9_arbeitsfassung = arbeitsfassung
            st.session_state.schritt9_arbeitsfassung_signatur = aktuelle_signatur
        except (Domaenenfehler, Importintegritaetsfehler) as fehler:
            st.error(f"Die Arbeitsfassung ist ungültig: {fehler}")
    arbeitsfassung = st.session_state.get("schritt9_arbeitsfassung")
    if isinstance(arbeitsfassung, Validierungsarbeitsfassung):
        veraltet = st.session_state.get("schritt9_arbeitsfassung_signatur") != aktuelle_signatur
        if veraltet:
            st.warning(
                "K, O oder menschliche Eingaben haben sich geändert. Die ungespeicherte "
                "Arbeitsfassung ist ungültig und muss erneut geprüft werden."
            )
        st.subheader("5. Speicherung von K* und Übergabe an Schritt 10")
        if arbeitsfassung.unbehandelte_offene_eintrag_ids:
            st.warning(
                f"Noch unbehandelte Einträge aus O: "
                f"{len(arbeitsfassung.unbehandelte_offene_eintrag_ids)}"
            )
        elif arbeitsfassung.gesamtvalidierungsstatus is Gesamtvalidierungsstatus.ANPASSUNGSBEDARF:
            st.warning("Es besteht Anpassungsbedarf. Eine erneute fachliche Validierung ist nötig.")
        else:
            st.success("Alle O-Einträge sind behandelt und die Arbeitsfassung ist finalisierbar.")
        bestaetigt = st.checkbox(
            "Ich bestätige die fachliche Gesamtvalidierung und die Erzeugung von K*.",
            key="schritt9_fachlich_bestaetigt",
        )
        if st.button(
            "K* speichern und zu Schritt 10",
            disabled=veraltet or not arbeitsfassung.finalisierbar or not bestaetigt,
            type="primary",
        ):
            try:
                validierung = service.speichern(
                    arbeitsfassung,
                    validierungslauf_id=uuid4(),
                    k_stern_id=uuid4(),
                    fachlich_bestaetigt=bestaetigt,
                )
                st.session_state.aktuelle_validierungslauf_id = str(validierung.validierungslauf_id)
                st.session_state.aktuelle_k_stern_id = str(validierung.k_stern_id)
                framework_bereich_oeffnen(schritt=10, projekt_id=projekt_id)
            except (Domaenenfehler, Importintegritaetsfehler) as fehler:
                st.error(f"K* konnte nicht gespeichert werden: {fehler}")
    gespeicherte_id = st.session_state.get("aktuelle_validierungslauf_id")
    if gespeicherte_id:
        try:
            _gespeichertes_k_stern(service, UUID(str(gespeicherte_id)), projekt_id)
        except (ValueError, Domaenenfehler, Importintegritaetsfehler, KeyError) as fehler:
            st.error(f"Das gespeicherte K* ist nicht mehr gültig: {fehler}")
