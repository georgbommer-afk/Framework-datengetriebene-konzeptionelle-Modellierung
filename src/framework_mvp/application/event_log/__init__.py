"""Öffentliche Funktionen des kanonischen Event-Log-Aufbaus."""

from framework_mvp.application.event_log.erzeugung import (
    EventLogErgebnis,
    erzeuge_event_log,
)

__all__ = ["EventLogErgebnis", "erzeuge_event_log"]
