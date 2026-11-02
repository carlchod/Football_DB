import streamlit as st
import psycopg2
import pandas as pd

# Hier eure Supabase Session-Pooler URI eintragen (oder über st.secrets laden)
DB_URI = "postgresql://postgres.xxxx:DEIN_PASSWORT@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"

st.set_page_config(page_title="ZLMV Berlin - Backend Demo", layout="wide")
st.title("⚽ ZLMV – Zentrales Ligamanagement- und Verbandssystem Berlin")

def run_query(query, params=None):
    with psycopg2.connect(DB_URI) as conn:
        return pd.read_sql_query(query, conn, params=params)

def execute_stmt(stmt, params):
    with psycopg2.connect(DB_URI) as conn:
        with conn.cursor() as cur:
            cur.execute(stmt, params)
            conn.commit()

tab1, tab2, tab3 = st.tabs([
    "📊 1. Live-Views (Ergebnisse & Karten)", 
    "🏟️ 2. Exclusion Constraints (Platz & Pass)", 
    "🚫 3. Trigger-Test (Sperren durchsetzen)"
])

# --- TAB 1: VIEWS ---
with tab1:
    st.subheader("Live-Spielstände (Dynamisch berechnet aus Tabelle TOR - 3NF)")
    df_spiele = run_query("SELECT * FROM v_spiel_ergebnisse ORDER BY anstoss_zeit;")
    st.dataframe(df_spiele, use_container_width=True)

    st.subheader("Karten- & Sportgerichts-Übersicht (View)")
    df_karten = run_query("SELECT * FROM v_karten_strafen;")
    st.dataframe(df_karten, use_container_width=True)

# --- TAB 2: EXCLUSION CONSTRAINTS ---
with tab2:
    st.subheader("Use-Case: Kein Doppel-Platz (Zeitfenster-Prüfung)")
    st.caption("Versucht man, zwei Spiele innerhalb von 120 Minuten auf demselben Platz anzusetzen, blockiert PostgreSQL den Eintrag.")

    with st.form("form_spiel_anlegen"):
        col1, col2 = st.columns(2)
        with col1:
            spieltag_id = st.number_input("Spieltag ID", min_value=1, value=1)
            platz_id = st.number_input("Platz ID", min_value=1, value=1)
            anstoss = st.text_input("Anstoßzeit (YYYY-MM-DD HH:MM:SS)", value="2026-05-10 14:00:00")
        with col2:
            heim_id = st.number_input("Heim-Teilnahme ID", min_value=1, value=1)
            gast_id = st.number_input("Gast-Teilnahme ID", min_value=1, value=2)

        submitted = st.form_submit_button("Spiel in Datenbank anlegen")
        if submitted:
            try:
                execute_stmt(
                    """INSERT INTO spiel (anstoss_zeit, heim_teilnahme_id, gast_teilnahme_id, platz_id, spieltag_id)
                       VALUES (%s, %s, %s, %s, %s);""",
                    (anstoss, heim_id, gast_id, platz_id, spieltag_id)
                )
                st.success("✅ Spiel erfolgreich angesetzt!")
            except psycopg2.Error as e:
                st.error(f"🛑 PostgreSQL Constraint-Blockade:\n\n{e.pgerror}")

# --- TAB 3: TRIGGER ---
with tab3:
    st.subheader("Use-Case: Spielersperren in der Aufstellung durchsetzen")
    st.caption("Feuert BEFORE INSERT auf SPIELTAG_KADER und prüft in Echtzeit die Tabelle URTEIL.")

    with st.form("form_aufstellung"):
        spiel_id_auf = st.number_input("Spiel ID", min_value=1, value=1)
        kader_id_auf = st.number_input("Kader ID des Spielers", min_value=1, value=1)
        startelf = st.checkbox("Startelf", value=True)

        sub_aufstellung = st.form_submit_button("Spieler für Spieltag nominieren")
        if sub_aufstellung:
            try:
                execute_stmt(
                    "INSERT INTO spieltag_kader (spiel_id, kader_id, startelf) VALUES (%s, %s, %s);",
                    (spiel_id_auf, kader_id_auf, startelf)
                )
                st.success("✅ Spieler erfolgreich für den Spieltagskader nominiert!")
            except psycopg2.Error as e:
                st.error(f"🛑 PostgreSQL Trigger-Blockade:\n\n{e.pgerror}")