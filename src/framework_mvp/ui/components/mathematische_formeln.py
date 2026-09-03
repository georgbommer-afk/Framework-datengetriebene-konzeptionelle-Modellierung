"""Zentrale LaTeX-Darstellungen unveränderter Gleichungen aus Schritt 7."""

import streamlit as st

DT_LATEX = r"d_T(c,a)=t_{\mathrm{Ist,Ende}}(c,a)-t_{\mathrm{Plan,Ende}}(c,a)"
DB_LATEX = (
    r"d_B(c,a)=\left(t_{\mathrm{Ist,Ende}}-t_{\mathrm{Ist,Start}}\right)"
    r"-\left(t_{\mathrm{Plan,Ende}}-t_{\mathrm{Plan,Start}}\right)"
)
BUSY_RATIO_LATEX = r"BR(r,i)=\frac{t_{\mathrm{Bearb}}(r,i)}{t_{\mathrm{ZA}}(r,i+1)}"
TOKEN_FITNESS_LATEX = (
    r"Fitness=\frac{1}{2}\left(1-\frac{m_T}{c_T}\right)"
    r"+\frac{1}{2}\left(1-\frac{r_T}{p_T}\right)"
)


def zeige_performance_formeln() -> None:
    """Zeigt die drei Performancegleichungen ohne ihre Berechnungslogik zu duplizieren."""
    with st.expander("Mathematische Definitionen", expanded=False):
        st.latex(DT_LATEX)
        st.latex(DB_LATEX)
        st.latex(BUSY_RATIO_LATEX)


def zeige_token_fitness_formel() -> None:
    """Zeigt die fest definierte Token-Fitness nach Gleichung 3.13."""
    st.latex(TOKEN_FITNESS_LATEX)
