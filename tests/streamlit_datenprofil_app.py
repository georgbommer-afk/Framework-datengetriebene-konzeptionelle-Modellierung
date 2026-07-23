"""Kleine Streamlit-Testanwendung für die Profilvisualisierung."""

import numpy as np
import pandas as pd

from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.ui.components.datenprofil_visualisierung import zeige_datenprofil

DATEN = pd.DataFrame(
    {
        "Numerisch": [1.0, 2.0, 3.0, 100.0, np.nan, 2.0, 3.0, 4.0, 5.0, 6.0],
        "Kategorie": ["A", "A", "B", "NULL", "C", "A", "B", "C", "D", "E"],
        "Zeit": [f"2024-01-{tag:02d}" for tag in range(1, 10)] + ["ungültig"],
        "Leer": [None] * 10,
    }
)

zeige_datenprofil(DatenimportService().profil_erstellen(DATEN), session_key="detailspalte")
