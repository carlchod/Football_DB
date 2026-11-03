"""ZLMV – Berliner Amateurfußball. Einstieg und Navigation.

Start:  streamlit run app.py
Voraussetzung: sql/views.sql ist einmal in der Datenbank ausgeführt, DB_URI steht in .streamlit/secrets.toml.
"""

import importlib

import streamlit as st

import db
import ui

# Über importlib statt "from seiten import ...", damit Streamlit geänderte Seiten beim Speichern neu lädt
oeffentlich, verein, staffelleitung, sportgericht, verband = (
    importlib.import_module(f"seiten.{name}")
    for name in ("oeffentlich", "verein", "staffelleitung", "sportgericht", "verband"))

st.set_page_config(page_title="ZLMV Berlin", page_icon=":material/sports_soccer:", layout="wide")
ui.stil()

# Seitenübergreifende Auswahl behalten (Streamlit verwirft sonst Widget-Werte beim Seitenwechsel)
for schluessel in ("staffel", "verein"):
    if schluessel in st.session_state:
        st.session_state[schluessel] = st.session_state[schluessel]

seiten = {
    "Spielbetrieb": [
        st.Page(oeffentlich.seite_spieltag, title="Spieltag", icon=":material/sports_soccer:", url_path="spieltag", default=True),
        st.Page(oeffentlich.seite_tabelle, title="Tabelle und Torjäger", icon=":material/table:", url_path="tabelle"),
        st.Page(oeffentlich.seite_spielbericht, title="Spielbericht", icon=":material/article:", url_path="spielbericht"),
        st.Page(oeffentlich.seite_vereine, title="Vereine", icon=":material/shield:", url_path="vereine"),
    ],
    "Verein": [
        st.Page(verein.seite_aufstellung, title="Aufstellung melden", icon=":material/groups:", url_path="aufstellung"),
        st.Page(verein.seite_paesse, title="Spielerpass", icon=":material/badge:", url_path="spielerpass"),
    ],
    "Staffelleitung": [
        st.Page(staffelleitung.seite_bericht_erfassen, title="Spielbericht erfassen", icon=":material/edit_note:", url_path="erfassen"),
        st.Page(staffelleitung.seite_verlegen, title="Spiel verlegen", icon=":material/event:", url_path="verlegen"),
        st.Page(staffelleitung.seite_schiedsrichter, title="Schiedsrichter einteilen", icon=":material/sports:", url_path="schiedsrichter"),
    ],
    "Sportgericht": [
        st.Page(sportgericht.seite_sportgericht, title="Verfahren und Sperren", icon=":material/gavel:", url_path="sportgericht"),
    ],
    "Verband": [
        st.Page(verband.seite_verband, title="Saison im Überblick", icon=":material/monitoring:", url_path="verband"),
    ],
}
ui.SEITEN.update({"spieltag": seiten["Spielbetrieb"][0], "tabelle": seiten["Spielbetrieb"][1],
                  "spielbericht": seiten["Spielbetrieb"][2]})

navigation = st.navigation(seiten, position="sidebar")

if "DB_URI" not in st.secrets:
    st.error("Es fehlt die Datenbankverbindung. Trage `DB_URI` in `.streamlit/secrets.toml` ein (siehe README).")
    st.stop()
try:
    fehlend = db.fehlende_views()
except Exception as fehler:                       # Verbindung oder Zugangsdaten
    st.error("Die Datenbank ist nicht erreichbar. Prüfe `DB_URI` in den Secrets.")
    st.exception(fehler)
    st.stop()
if fehlend:
    st.error("In der Datenbank fehlen Views, die die App braucht: " + ", ".join(fehlend)
             + ". Führe einmal `sql/views.sql` aus (SQL-Editor in Supabase oder psql).")
    st.stop()

saison = db.wert("SELECT bezeichnung FROM saison ORDER BY beginn DESC LIMIT 1")
st.sidebar.markdown(
    '<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700;font-size:1.6rem;line-height:1">ZLMV</div>'
    f'<div style="font-size:.875rem;opacity:.8">Berliner Amateurfußball<br>Saison {saison}</div>',
    unsafe_allow_html=True)

navigation.run()
