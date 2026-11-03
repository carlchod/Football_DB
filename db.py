"""Datenbankzugriff: Verbindungspool, gecachte Leseabfragen, Transaktionen, verständliche Fehlertexte."""

from contextlib import contextmanager

import pandas as pd
import psycopg2
import psycopg2.pool
import streamlit as st

# NUMERIC als float lesen: pandas, Altair und Streamlit-Spalten rechnen nicht mit Decimal
psycopg2.extensions.register_type(psycopg2.extensions.new_type(
    psycopg2.extensions.DECIMAL.values, "NUMERIC_ALS_FLOAT",
    lambda wert, cur: float(wert) if wert is not None else None))

BENOETIGTE_VIEWS = ["v_staffel", "v_teilnahme", "v_spiel", "v_tabelle", "v_torjaeger",
                    "v_spielerstatistik", "v_sperre_quelle", "v_sperren_aktuell", "v_datenpruefung"]


@st.cache_resource(show_spinner=False)
def _pool():
    return psycopg2.pool.ThreadedConnectionPool(1, 6, st.secrets["DB_URI"])


@contextmanager
def _verbindung():
    pool = _pool()
    conn = pool.getconn()
    kaputt = False
    try:
        yield conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        kaputt = True
        raise
    finally:
        pool.putconn(conn, close=kaputt or conn.closed != 0)


def _mit_wiederholung(arbeit):
    """Führt arbeit(conn) aus; eine vom Server getrennte Verbindung wird einmal ersetzt."""
    for versuch in range(2):
        try:
            with _verbindung() as conn:
                return arbeit(conn)
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            if versuch == 1:
                raise


@st.cache_data(ttl=60, show_spinner=False)
def abfrage(sql: str, params: tuple | dict | None = None) -> pd.DataFrame:
    """Leseabfrage, 60 Sekunden gecacht. Nach jedem Schreibvorgang wird der Cache geleert."""
    def arbeit(conn):
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                spalten = [d[0] for d in cur.description]
                return pd.DataFrame(cur.fetchall(), columns=spalten)
        finally:
            conn.rollback()
    return _mit_wiederholung(arbeit)


def wert(sql: str, params=None):
    df = abfrage(sql, params)
    return None if df.empty else df.iat[0, 0]


def transaktion(arbeit):
    """Führt arbeit(cursor) in einer Transaktion aus.

    Rückgabe: (True, Ergebnis) oder (False, psycopg2.Error). Bei Erfolg wird der Lese-Cache geleert,
    damit alle Seiten sofort den neuen Stand zeigen.
    """
    def ausfuehren(conn):
        try:
            with conn.cursor() as cur:
                ergebnis = arbeit(cur)
            conn.commit()
            return True, ergebnis
        except psycopg2.Error as fehler:
            conn.rollback()
            return False, fehler
    ok, ergebnis = _mit_wiederholung(ausfuehren)
    if ok:
        st.cache_data.clear()
    return ok, ergebnis


def jetzt():
    """Aktuelle Zeit in Berlin, so wie die Views sie verwenden."""
    return wert("SELECT (now() AT TIME ZONE 'Europe/Berlin')::timestamp")


def fehlende_views() -> list[str]:
    df = abfrage("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                 "WHERE n.nspname = 'public' AND c.relkind = 'v'")
    vorhanden = set(df["relname"]) if not df.empty else set()
    return [v for v in BENOETIGTE_VIEWS if v not in vorhanden]


# Constraint-Namen aus 01_schema.sql -> Erklärung für Nutzer
_CONSTRAINTS = {
    "excl_kein_doppel_platz": "Der Platz ist zu dieser Zeit schon belegt. Jedes Spiel belegt seinen Platz zwei Stunden lang.",
    "exclude_kein_doppelpass": "Der Spieler hat in diesem Zeitraum schon einen gültigen Pass. Pässe dürfen sich nicht überschneiden.",
    "check_pass_daten": "Das Ende der Gültigkeit liegt vor ihrem Beginn.",
    "chk_unterschiedliche_teams": "Heim- und Gastmannschaft müssen verschieden sein.",
    "chk_wechsel_spieler": "Ein Spieler kann nicht für sich selbst eingewechselt werden.",
    "spielereignis_minute_check": "Die Spielminute muss zwischen 1 und 130 liegen.",
    "spieltag_kader_spiel_id_kader_id_key": "Der Spieler steht für dieses Spiel schon auf dem Spielberichtsbogen.",
    "spiel_schiedsrichter_pkey": "Diese Person ist für das Spiel schon eingeteilt.",
    "urteil_spielereignis_id_key": "Zu dieser Karte gibt es schon ein Urteil.",
    # erst nach sql/erweiterung_vorschlag.sql
    "uq_spiel_rolle": "Diese Rolle ist in diesem Spiel schon besetzt.",
    "chk_rolle": "Erlaubt sind die Rollen Schiedsrichter, Assistent 1 und Assistent 2.",
    "chk_wertung_vollstaendig": "Eine Wertung braucht Tore für beide Mannschaften.",
    "chk_spielberechtigt_im_pass": "Der Beginn der Spielberechtigung muss im Gültigkeitszeitraum des Passes liegen.",
}


def fehlertext(fehler: psycopg2.Error) -> str:
    """Übersetzt eine Datenbankmeldung in einen Satz für Nutzer."""
    diag = getattr(fehler, "diag", None)
    constraint = getattr(diag, "constraint_name", None)
    meldung = getattr(diag, "message_primary", None) or str(fehler)
    if constraint in _CONSTRAINTS:
        return _CONSTRAINTS[constraint]
    code = getattr(fehler, "pgcode", None)
    if code == "P0001":                       # RAISE EXCEPTION aus einem Trigger
        return meldung
    if code == "23503":
        return "Der Eintrag wird an anderer Stelle noch verwendet und kann deshalb nicht geändert werden."
    if code == "23505":
        return "Diesen Eintrag gibt es schon."
    if code == "23514":
        return "Die Eingabe verletzt eine Prüfregel der Datenbank."
    return "Die Datenbank hat den Vorgang abgelehnt."


def fehler_anzeigen(fehler: psycopg2.Error, titel: str = "Nicht gespeichert"):
    st.error(f"**{titel}.** {fehlertext(fehler)}", icon=":material/block:")
    diag = getattr(fehler, "diag", None)
    with st.expander("Meldung der Datenbank"):
        zeilen = [f"SQLSTATE {getattr(fehler, 'pgcode', '–')}"]
        if getattr(diag, "constraint_name", None):
            zeilen.append(f"Regel: {diag.constraint_name}")
        if getattr(diag, "table_name", None):
            zeilen.append(f"Tabelle: {diag.table_name}")
        st.code("\n".join(zeilen) + "\n\n" + (getattr(diag, "message_primary", None) or str(fehler)), language=None)
