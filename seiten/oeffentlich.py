"""Öffentliche Seiten: Spieltag, Tabelle, Spielbericht, Vereine."""

from html import escape

import pandas as pd
import streamlit as st

import db
import ui


# ------------------------------------------------------------------ Spieltag (Startseite)

def _spieltage(staffel_id):
    return db.abfrage("""
        SELECT spieltag, min(anstoss_zeit) AS von, max(anstoss_zeit) AS bis,
               count(*) FILTER (WHERE status = 'gespielt') AS gespielt, count(*) AS spiele
        FROM v_spiel WHERE staffel_id = %s GROUP BY spieltag ORDER BY spieltag""", (staffel_id,))


def _bericht_oeffnen(spiel_id):
    st.session_state["bericht_spiel_id"] = int(spiel_id)
    st.switch_page(ui.SEITEN["spielbericht"])


def seite_spieltag():
    staffel_id = ui.staffel_waehler()
    tage = _spieltage(staffel_id)
    gespielte = tage.loc[tage["gespielt"] > 0, "spieltag"]
    standard = int(gespielte.max()) if not gespielte.empty else 1
    schluessel = f"spieltag_{staffel_id}"
    if schluessel not in st.session_state:
        st.session_state[schluessel] = standard
    nummern = [int(n) for n in tage["spieltag"]]

    kopf, wahl = st.columns([3, 2], vertical_alignment="bottom")
    nr = int(st.session_state[schluessel])
    zeile = tage[tage["spieltag"] == nr].iloc[0]
    with kopf:
        st.title(f"{nr}. Spieltag")
        von, bis = zeile["von"], zeile["bis"]
        st.caption(ui.staffel_name(staffel_id) + ", " + (ui.datum_lang(von) if von.date() == bis.date()
                   else f"{ui.datum_lang(von)} bis {ui.datum_lang(bis)}"))
    with wahl:
        st.select_slider("Spieltag", nummern, key=schluessel, format_func=lambda n: f"{n}.")

    spiele = db.abfrage("""
        SELECT spiel_id, anstoss_zeit, heim, gast, tore_heim, tore_gast, status, sportanlage, platz
        FROM v_spiel WHERE staffel_id = %s AND spieltag = %s ORDER BY anstoss_zeit, heim""", (staffel_id, nr))

    links, rechts = st.columns([5, 2], gap="large")
    with links:
        for _, spiel in spiele.iterrows():
            with st.container(border=True):
                text, knopf = st.columns([6, 1.3], vertical_alignment="center")
                text.markdown(ui.spielzeile(spiel), unsafe_allow_html=True)
                if spiel["status"] == "gespielt":
                    knopf.button("Spielbericht", key=f"b{spiel['spiel_id']}", width="stretch",
                                 on_click=_bericht_oeffnen, args=(spiel["spiel_id"],))
    with rechts:
        st.subheader("Tabelle")
        tabelle = db.abfrage("SELECT * FROM v_tabelle WHERE staffel_id = %s ORDER BY platz, mannschaft",
                             (staffel_id,))
        st.markdown(ui.tabelle_html(tabelle, kompakt=True), unsafe_allow_html=True)
        st.page_link(ui.SEITEN["tabelle"], label="Ganze Tabelle und Torjäger", icon=":material/table:")


# ------------------------------------------------------------------ Tabelle, Torjäger, Fairplay

def seite_tabelle():
    staffel_id = ui.staffel_waehler()
    st.title(ui.staffel_name(staffel_id))
    reiter = st.tabs(["Tabelle", "Torjäger", "Fairplay"])

    with reiter[0]:
        df = db.abfrage("SELECT * FROM v_tabelle WHERE staffel_id = %s ORDER BY platz, mannschaft", (staffel_id,))
        st.markdown(ui.tabelle_html(df), unsafe_allow_html=True)
        abzug = df[df["punkteabzug"] > 0]
        hinweise = [f"* {r['mannschaft']}: {r['punkteabzug']} Punkte Abzug" for _, r in abzug.iterrows()]
        st.caption("Form: die letzten fünf Spiele, das jüngste zuerst. " + " ".join(hinweise))
        ui.technik(
            "Die Tabelle wird berechnet, nicht gespeichert",
            "In `spiel` gibt es keine Ergebnisspalten. Die View `v_spiel` zählt die Tore je Mannschaft aus der "
            "Tabelle `tor`, `v_tabelle` rechnet daraus Punkte, Tordifferenz und Form und zieht den "
            "`punkteabzug` aus `staffel_teilnahme` ab. Ein Spiel zählt, sobald der Anstoß vorbei ist und ein "
            "Spielberichtsbogen vorliegt.",
            "SELECT platz, mannschaft, spiele, siege, unentschieden, niederlagen, tore, gegentore, punkte, form\n"
            "FROM v_tabelle WHERE staffel_id = :staffel ORDER BY platz;")

    with reiter[1]:
        df = db.abfrage("""SELECT platz, spieler, mannschaft, position, tore FROM v_torjaeger
                           WHERE staffel_id = %s AND platz <= 20 ORDER BY platz, spieler""", (staffel_id,))
        st.dataframe(df, hide_index=True, width="stretch", column_config={
            "platz": st.column_config.NumberColumn("Pl.", width="small"),
            "spieler": "Spieler", "mannschaft": "Mannschaft", "position": "Position",
            "tore": st.column_config.ProgressColumn("Tore", format="%d", min_value=0,
                                                    max_value=int(df["tore"].max()) if not df.empty else 1)})

    with reiter[2]:
        df = db.abfrage("""
            SELECT t.mannschaft,
                   count(*) FILTER (WHERE ka.art = 'Gelb')     AS gelb,
                   count(*) FILTER (WHERE ka.art = 'Gelb-Rot') AS gelb_rot,
                   count(*) FILTER (WHERE ka.art = 'Rot')      AS rot,
                   coalesce(sum(CASE ka.art WHEN 'Gelb' THEN 1 WHEN 'Gelb-Rot' THEN 3 WHEN 'Rot' THEN 5 END), 0) AS punkte
            FROM v_teilnahme t
            LEFT JOIN kader k           ON k.teilnahme_id = t.teilnahme_id
            LEFT JOIN spieltag_kader sk ON sk.kader_id = k.kader_id
            LEFT JOIN karte ka          ON ka.spieltag_kader_id = sk.spieltag_kader_id
            WHERE t.staffel_id = %s
            GROUP BY t.mannschaft ORDER BY punkte, t.mannschaft""", (staffel_id,))
        df.insert(0, "platz", df["punkte"].rank(method="min").astype(int))
        st.caption("Wenige Punkte bedeuten faires Spiel: Gelbe Karte 1, Gelb-Rote Karte 3, Rote Karte 5 Punkte.")
        st.dataframe(df, hide_index=True, width="stretch", column_config={
            "platz": st.column_config.NumberColumn("Pl.", width="small"), "mannschaft": "Mannschaft",
            "gelb": "Gelb", "gelb_rot": "Gelb-Rot", "rot": "Rot", "punkte": "Fairplay-Punkte"})


# ------------------------------------------------------------------ Spielbericht

def seite_spielbericht():
    # Aufruf aus dem Spieltag: Staffel, Spieltag und Spiel vorbelegen
    if "bericht_spiel_id" in st.session_state:
        sid = st.session_state.pop("bericht_spiel_id")
        info = db.abfrage("SELECT staffel_id, spieltag FROM v_spiel WHERE spiel_id = %s", (sid,))
        if not info.empty:
            st.session_state["staffel"] = int(info.at[0, "staffel_id"])
            st.session_state["bericht_spieltag"] = int(info.at[0, "spieltag"])
            st.session_state["bericht_spiel"] = sid

    staffel_id = ui.staffel_waehler()
    spiele = db.abfrage("""SELECT spiel_id, spieltag, heim, gast, anstoss_zeit, status FROM v_spiel
                           WHERE staffel_id = %s ORDER BY spieltag, anstoss_zeit, heim""", (staffel_id,))
    gespielt = spiele[spiele["status"] == "gespielt"]
    tage = sorted(spiele["spieltag"].unique().tolist())
    if st.session_state.get("bericht_spieltag") not in tage:
        st.session_state["bericht_spieltag"] = int(gespielt["spieltag"].max()) if not gespielt.empty else tage[0]

    a, b = st.columns([1, 3])
    nr = a.selectbox("Spieltag", tage, key="bericht_spieltag", format_func=lambda n: f"{n}. Spieltag")
    auswahl = spiele[spiele["spieltag"] == nr]
    ids = [int(i) for i in auswahl["spiel_id"]]
    namen = {int(r["spiel_id"]): f"{r['heim']} gegen {r['gast']}" for _, r in auswahl.iterrows()}
    if st.session_state.get("bericht_spiel") not in ids:
        st.session_state["bericht_spiel"] = ids[0]
    spiel_id = b.selectbox("Spiel", ids, key="bericht_spiel", format_func=namen.get)

    spiel = db.abfrage("SELECT * FROM v_spiel WHERE spiel_id = %s", (spiel_id,)).iloc[0]
    st.markdown(f'<div class="zl-kopf"><div class="team heim">{escape(spiel["heim"])}</div>'
                f'{ui.tafel(spiel, gross=True)}<div class="team">{escape(spiel["gast"])}</div></div>',
                unsafe_allow_html=True)
    sr = db.abfrage("""SELECT ss.rolle, p.vorname || ' ' || p.nachname AS name FROM spiel_schiedsrichter ss
                       JOIN person p ON p.person_id = ss.person_id WHERE ss.spiel_id = %s
                       ORDER BY CASE ss.rolle WHEN 'Schiedsrichter' THEN 0 ELSE 1 END, ss.rolle""", (spiel_id,))
    zeilen = [f"{ui.datum_lang(spiel['anstoss_zeit'])}, {ui.uhrzeit(spiel['anstoss_zeit'])} Uhr",
              f"{spiel['sportanlage']}, {spiel['platz']} ({spiel['belag']})"]
    if not sr.empty:
        zeilen.append(", ".join(f"{r['rolle']}: {r['name']}" for _, r in sr.iterrows()))
    st.markdown(f'<div class="zl-meta" style="text-align:center">{"<br>".join(escape(z) for z in zeilen)}</div>',
                unsafe_allow_html=True)

    if spiel["status"] in ("angesetzt", "bericht_fehlt"):
        st.info("Für dieses Spiel liegt noch kein Spielbericht vor." if spiel["status"] == "bericht_fehlt"
                else "Dieses Spiel ist noch nicht gespielt.", icon=":material/schedule:")
        return

    bogen, ereignisse = ui.spielbericht_daten(spiel_id)
    st.subheader("Spielverlauf")
    st.markdown(ui.verlauf_html(spiel, bogen, ereignisse), unsafe_allow_html=True)
    st.subheader("Aufstellungen")
    heim, gast = st.columns(2, gap="large")
    with heim:
        st.markdown(f"**{spiel['heim']}**")
        st.markdown(ui.aufstellung_html(bogen, ereignisse, int(spiel["heim_teilnahme_id"])), unsafe_allow_html=True)
    with gast:
        st.markdown(f"**{spiel['gast']}**")
        st.markdown(ui.aufstellung_html(bogen, ereignisse, int(spiel["gast_teilnahme_id"])), unsafe_allow_html=True)
    ui.technik(
        "Ereignisse als Spezialisierung",
        "Jedes Ereignis steht in `spielereignis` (Spiel und Minute) und genau einer der Tabellen `tor`, `karte` "
        "oder `wechsel`. Diese verweisen auf den Eintrag im Spielberichtsbogen (`spieltag_kader`), damit nur "
        "Spieler vorkommen, die für dieses Spiel gemeldet waren. Der Spielstand im Verlauf wird beim Lesen "
        "hochgezählt.")


# ------------------------------------------------------------------ Vereine

def _verein_setzen(verein_id):
    st.session_state["verein"] = verein_id
    st.session_state.pop("verein_tabelle", None)


def _verzeichnis(vereine):
    st.title("Vereine")
    st.caption(f"{len(vereine)} Vereine aus {vereine['bezirk'].nunique()} Berliner Bezirken. "
               "Klicke einen Verein in der Liste an, um Mannschaften, Spiele und Kader zu sehen.")
    a, b = st.columns([3, 2])
    suche = a.text_input("Suche", placeholder="Vereinsname", key="verein_suche", icon=":material/search:")
    bezirk = b.selectbox("Bezirk", ["Alle Bezirke"] + sorted(vereine["bezirk"].unique()), key="verein_bezirk")
    df = vereine
    if suche.strip():
        df = df[df["name"].str.contains(suche.strip(), case=False, regex=False)]
    if bezirk != "Alle Bezirke":
        df = df[df["bezirk"] == bezirk]
    df = df.reset_index(drop=True)
    if df.empty:
        st.info("Kein Verein passt zur Suche.", icon=":material/search_off:")
        return
    auswahl = st.dataframe(
        df[["name", "bezirk", "hoechste", "mannschaften", "gruendungsjahr"]], hide_index=True,
        width="stretch", height=min(38 + 35 * len(df), 640), on_select="rerun",
        selection_mode="single-row", key="verein_tabelle",
        column_config={"name": st.column_config.TextColumn("Verein", width="large"), "bezirk": "Bezirk",
                       "hoechste": "Erste Mannschaft spielt in", "mannschaften": "Mannschaften",
                       "gruendungsjahr": st.column_config.NumberColumn("Gegründet", format="%d")})
    if auswahl.selection.rows:
        st.session_state["verein"] = int(df.iloc[auswahl.selection.rows[0]]["verein_id"])
        st.rerun()


def seite_vereine():
    vereine = db.abfrage("""
        SELECT v.verein_id, v.name, b.name AS bezirk, v.gruendungsjahr, count(t.teilnahme_id) AS mannschaften,
               (array_agg(s.kurzname ORDER BY s.ebene, s.nummer, t.nummer))[1] AS hoechste
        FROM verein v JOIN bezirk b ON b.bezirk_id = v.bezirk_id
        LEFT JOIN v_teilnahme t ON t.verein_id = v.verein_id
        LEFT JOIN v_staffel s   ON s.staffel_id = t.staffel_id
        GROUP BY v.verein_id, v.name, b.name, v.gruendungsjahr ORDER BY v.name""")
    verein_id = st.session_state.get("verein")
    if verein_id not in set(vereine["verein_id"].astype(int)):
        _verzeichnis(vereine)
        return

    v = vereine[vereine["verein_id"] == verein_id].iloc[0]
    st.button("Alle Vereine", icon=":material/arrow_back:", type="tertiary", on_click=_verein_setzen, args=(None,))
    st.title(v["name"])
    gegruendet = f", gegründet {int(v['gruendungsjahr'])}" if pd.notna(v["gruendungsjahr"]) else ""
    anlagen = db.abfrage("SELECT DISTINCT sportanlage FROM v_spiel WHERE heim_verein_id = %s ORDER BY 1", (verein_id,))
    st.caption(f"Bezirk {v['bezirk']}{gegruendet}. Heimspiele: {', '.join(anlagen['sportanlage']) or 'keine'}.")

    teams = db.abfrage("""SELECT t.teilnahme_id, t.mannschaft, s.name AS staffel FROM v_teilnahme t
                          JOIN v_staffel s ON s.staffel_id = t.staffel_id WHERE t.verein_id = %s
                          ORDER BY t.nummer""", (verein_id,))
    if teams.empty:
        st.info("Der Verein hat in dieser Saison keine Mannschaft gemeldet.")
        return
    reiter = st.tabs(list(teams["mannschaft"])) if len(teams) > 1 else [st.container()]
    for (_, team), bereich in zip(teams.iterrows(), reiter):
        with bereich:
            _mannschaft(int(team["teilnahme_id"]), team["staffel"])


def _mannschaft(teilnahme_id: int, staffel: str):
    platz = db.abfrage("SELECT * FROM v_tabelle WHERE teilnahme_id = %s", (teilnahme_id,)).iloc[0]
    a, b, c, d = st.columns(4)
    a.metric("Platz", f"{platz['platz']}.", help=staffel)
    b.metric("Punkte", int(platz["punkte"]))
    c.metric("Tore", f"{platz['tore']}:{platz['gegentore']}")
    d.metric("Bilanz", f"{platz['siege']}-{platz['unentschieden']}-{platz['niederlagen']}",
             help="Siege, Unentschieden, Niederlagen")
    st.caption(staffel)

    spiele, kader = st.columns([2, 3], gap="large")
    with spiele:
        st.subheader("Letzte Spiele")
        letzte = db.abfrage("""SELECT * FROM v_spiel WHERE %s IN (heim_teilnahme_id, gast_teilnahme_id)
                               AND status = 'gespielt' ORDER BY anstoss_zeit DESC LIMIT 4""", (teilnahme_id,))
        for _, s in letzte.iterrows():
            st.markdown(ui.spielzeile(s), unsafe_allow_html=True)
            st.write("")
        st.subheader("Nächste Spiele")
        naechste = db.abfrage("""SELECT * FROM v_spiel WHERE %s IN (heim_teilnahme_id, gast_teilnahme_id)
                                 AND status IN ('angesetzt', 'aufgestellt') ORDER BY anstoss_zeit LIMIT 3""",
                              (teilnahme_id,))
        for _, s in naechste.iterrows():
            st.markdown(ui.spielzeile(s), unsafe_allow_html=True)
            st.write("")
    with kader:
        st.subheader("Kader")
        df = db.abfrage("""
            SELECT s.rueckennummer AS nr, s.spieler, s.position, extract(year FROM s.geburtsdatum)::int AS jahrgang,
                   s.einsaetze, s.tore, s.gelb, s.gelb_rot + s.rot AS platzverweise,
                   (SELECT string_agg(a.art || ', noch ' || a.offen
                                      || CASE WHEN a.offen = 1 THEN ' Spiel' ELSE ' Spiele' END, '; ')
                      FROM v_sperren_aktuell a WHERE a.kader_id = s.kader_id) AS gesperrt
            FROM v_spielerstatistik s WHERE s.teilnahme_id = %s
            ORDER BY CASE s.position WHEN 'Tor' THEN 1 WHEN 'Abwehr' THEN 2 WHEN 'Mittelfeld' THEN 3 ELSE 4 END,
                     s.rueckennummer""", (teilnahme_id,))
        st.dataframe(df, hide_index=True, width="stretch", height=min(38 + 35 * len(df), 820),
                     column_config={
                         "nr": st.column_config.NumberColumn("Nr.", width="small"), "spieler": "Spieler",
                         "position": "Position", "jahrgang": st.column_config.NumberColumn("Jg.", format="%d"),
                         "einsaetze": "Einsätze", "tore": "Tore", "gelb": "Gelb",
                         "platzverweise": "Platzverw.", "gesperrt": "Gesperrt"})
