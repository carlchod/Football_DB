import pandas as pd
import psycopg2
import streamlit as st

# Supabase Session-Pooler URI über st.secrets["DB_URI"]
DB_URI = st.secrets["DB_URI"]

st.set_page_config(page_title="ZLMV Berlin - Live Demo", layout="wide")
st.title(
    "⚽ ZLMV – Zentrales Ligamanagement- und Verbandssystem Berlin (Saison 2026/27)"
)


def run_query(query, params=None):
    with psycopg2.connect(DB_URI) as conn:
        return pd.read_sql_query(query, conn, params=params)


def execute_stmt(stmt, params):
    with psycopg2.connect(DB_URI) as conn:
        with conn.cursor() as cur:
            cur.execute(stmt, params)
            conn.commit()


tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📊 1. Live-Tabellen & Karten (Views)",
        "🏟️ 2. Platz-Konflikt (Exclusion Constraint)",
        "🚫 3. Spielersperren (Trigger)",
        "✅ 4. Konsistenz-Check (03_pruefungen.sql)",
    ]
)

# --- TAB 1: VIEWS ---
with tab1:
    st.subheader(
        "Live-Ligatabelle (100% dynamisch aus Einzel-Toren berechnet - 3NF)"
    )
    staffeln = run_query(
        "SELECT DISTINCT staffel_id, liga_name FROM v_ligatabelle ORDER BY staffel_id;"
    )

    if not staffeln.empty:
        auswahl = st.selectbox("Staffel auswählen:", staffeln["liga_name"])
        st_id = int(
            staffeln.loc[
                staffeln["liga_name"] == auswahl, "staffel_id"
            ].values[0]
        )

        df_tabelle = run_query(
            "SELECT platz, mannschaft, spiele, s, u, n, tore, punkteabzug, punkte FROM v_ligatabelle WHERE staffel_id = %s ORDER BY platz;",
            (st_id,),
        )
        st.dataframe(df_tabelle, use_container_width=True, hide_index=True)
    else:
        st.warning(
            "Noch keine Spieldaten vorhanden. Bitte 02_testdaten_2.sql laden."
        )

    st.subheader("Sportgerichtsurteile & Offene Rote Karten (View)")
    df_urteile = run_query("SELECT * FROM v_rote_karten_urteile;")
    st.dataframe(df_urteile, use_container_width=True, hide_index=True)

# --- TAB 2: EXCLUSION CONSTRAINT ---
with tab2:
    st.subheader("Live-Test: Kein Doppel-Platz (Exclusion Constraint)")
    st.info(
        "💡 **Vorführ-Tipp:** Spiel #97 findet am **08.11.2026 um 14:00 Uhr** auf **Platz 62** statt. Wenn du unten versuchst, ein Spiel um **14:30 Uhr** auf **Platz 62** anzusetzen, schlägt der PostgreSQL Exclusion Constraint (`excl_kein_doppel_platz`) sofort an!"
    )

    with st.form("form_doppel_platz"):
        col1, col2 = st.columns(2)
        with col1:
            platz_id = st.number_input("Platz ID", value=62)
            anstoss = st.text_input("Anstoßzeit", value="2026-11-08 14:30:00")
            spieltag_id = st.number_input("Spieltag ID", value=13)
        with col2:
            heim_id = st.number_input("Heim-Teilnahme ID", value=1)
            gast_id = st.number_input("Gast-Teilnahme ID", value=2)

        if st.form_submit_button("Spiel in Datenbank eintragen"):
            try:
                execute_stmt(
                    "INSERT INTO spiel (anstoss_zeit, heim_teilnahme_id, gast_teilnahme_id, platz_id, spieltag_id) VALUES (%s, %s, %s, %s, %s);",
                    (anstoss, heim_id, gast_id, platz_id, spieltag_id),
                )
                st.success("✅ Spiel erfolgreich eingetragen!")
            except psycopg2.Error as e:
                st.error(f"🛑 PostgreSQL Constraint-Blockade:\n\n{e.pgerror}")

# --- TAB 3: TRIGGER ---
with tab3:
    st.subheader("Live-Test: Gesperrte Spieler blockieren (Trigger)")
    df_sperren = run_query("SELECT * FROM v_aktive_sperren;")
    st.write(
        "**Spieler mit aktiver Sportgerichtssperre zum Stichtag 02.11.2026 (dürfen im nächsten Spiel nicht aufgestellt werden):**"
    )
    st.dataframe(df_sperren, use_container_width=True, hide_index=True)

    default_kader = (
        int(df_sperren["kader_id"].iloc[0]) if not df_sperren.empty else 1
    )
    default_spiel = (
        int(df_sperren["naechstes_spiel_id"].iloc[0])
        if not df_sperren.empty
        else 97
    )

    with st.form("form_sperre_testen"):
        st.caption(
            "Die Werte des ersten gesperrten Spielers aus der Tabelle oben sind bereits voreingestellt:"
        )
        kader_id_in = st.number_input("Kader ID", value=default_kader)
        spiel_id_in = st.number_input("Nächstes Spiel ID", value=default_spiel)
        startelf_in = st.checkbox("In die Startelf stellen", value=True)

        if st.form_submit_button("Spieler trotzdem nominieren (Trigger-Test)"):
            try:
                execute_stmt(
                    "INSERT INTO spieltag_kader (startelf, spiel_id, kader_id) VALUES (%s, %s, %s);",
                    (startelf_in, spiel_id_in, kader_id_in),
                )
                st.success("✅ Spieler wurde aufgestellt!")
            except psycopg2.Error as e:
                st.error(f"🛑 PostgreSQL Trigger-Blockade:\n\n{e.pgerror}")

# --- TAB 4: DATENKONSISTENZ ---
with tab4:
    st.subheader("Live-Datenbank-Kennzahlen")
    df_stats = run_query("""
        SELECT 
            (SELECT count(*) FROM verein) AS vereine,
            (SELECT count(*) FROM spieler) AS spieler,
            (SELECT count(*) FROM spiel) AS spiele_gesamt,
            (SELECT count(DISTINCT spiel_id) FROM spieltag_kader) AS spiele_gespielt,
            (SELECT count(*) FROM tor) AS tore_gesamt,
            (SELECT count(*) FROM karte) AS karten_gesamt,
            (SELECT count(*) FROM urteil) AS urteile_gesamt;
    """)
    st.dataframe(df_stats, use_container_width=True, hide_index=True)