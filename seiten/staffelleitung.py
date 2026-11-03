"""Seiten für die Staffelleitung: Spielbericht erfassen, Spiel verlegen, Schiedsrichter einteilen."""

import datetime as dt
from html import escape

import streamlit as st

import db
import ui

# Kurzname für die Auswahl -> (Subtyp-Tabelle, Kartenart, Name in Meldungen)
ARTEN = {"Tor": ("tor", None, "Tor"), "Gelb": ("karte", "Gelb", "Gelbe Karte"),
         "Gelb-Rot": ("karte", "Gelb-Rot", "Gelb-Rote Karte"), "Rot": ("karte", "Rot", "Rote Karte"),
         "Wechsel": ("wechsel", None, "Auswechslung")}
WECHSEL_MAX = 5


def _spielauswahl(staffel_id, bedingung, schluessel, absteigend=False, leer="Keine passenden Spiele.",
                  markiert=(), zusatz=""):
    """Auswahl eines Spiels. `markiert` sind Spiel-IDs, die zuerst gewählt und mit `zusatz` beschriftet werden."""
    spiele = db.abfrage(f"""SELECT * FROM v_spiel WHERE staffel_id = %s AND {bedingung}
                            ORDER BY anstoss_zeit {'DESC' if absteigend else ''}, heim LIMIT 60""", (staffel_id,))
    if spiele.empty:
        st.info(leer)
        return None, spiele
    markiert = set(markiert)
    texte = {int(r["spiel_id"]): f"{r['spieltag']}. Spieltag, {ui.datum_kurz(r['anstoss_zeit'])} "
                                 f"{ui.uhrzeit(r['anstoss_zeit'])}: {r['heim']} gegen {r['gast']}"
                                 + (f" ({zusatz})" if int(r["spiel_id"]) in markiert else "")
             for _, r in spiele.iterrows()}
    ids = list(texte)
    spiel_id = ui.stabile_auswahl(st.selectbox, "Spiel", ids, texte.get, merk=schluessel,
                                  standard=next((i for i in ids if i in markiert), ids[0]))
    return spiel_id, spiele[spiele["spiel_id"] == spiel_id].iloc[0]


# ------------------------------------------------------------------ Spielbericht erfassen

def seite_bericht_erfassen():
    st.title("Spielbericht erfassen")
    ui.meldung_zeigen()
    staffel_id = ui.staffel_waehler()

    fehlend = db.abfrage("""SELECT spieltag, heim, gast, anstoss_zeit FROM v_spiel
                            WHERE staffel_id = %s AND status = 'bericht_fehlt' ORDER BY anstoss_zeit""", (staffel_id,))
    if not fehlend.empty:
        st.warning(f"{len(fehlend)} Spiele ohne Spielbericht. Melde zuerst die Aufstellungen.",
                   icon=":material/assignment_late:")
        st.dataframe(fehlend, hide_index=True, column_config={
            "spieltag": "Spieltag", "heim": "Heim", "gast": "Gast",
            "anstoss_zeit": st.column_config.DatetimeColumn("Anstoß", format="DD.MM.YYYY HH:mm")})

    spiel_id, spiel = _spielauswahl(staffel_id, "status = 'gespielt'", f"erfassen_{staffel_id}", absteigend=True,
                                    leer="In dieser Staffel gibt es noch kein Spiel mit Aufstellung.")
    if spiel_id is None:
        return
    bogen, ereignisse = ui.spielbericht_daten(spiel_id)

    st.markdown(f'<div class="zl-kopf"><div class="team heim">{escape(spiel["heim"])}</div>{ui.tafel(spiel, gross=True)}'
                f'<div class="team">{escape(spiel["gast"])}</div></div>', unsafe_allow_html=True)

    eingabe, verlauf = st.columns([2, 3], gap="large")
    with verlauf:
        st.subheader("Spielverlauf")
        st.markdown(ui.verlauf_html(spiel, bogen, ereignisse), unsafe_allow_html=True)
        eigene = st.session_state.setdefault("eigene_ereignisse", [])
        letzte = [e for e in eigene if e in set(ereignisse["id"].astype(int))]
        if letzte and st.button("Zuletzt erfasstes Ereignis löschen", icon=":material/undo:"):
            eid = letzte[-1]

            def loeschen(cur):
                for tabelle in ("tor", "karte", "wechsel"):
                    cur.execute(f"DELETE FROM {tabelle} WHERE spielereignis_id = %s", (eid,))
                cur.execute("DELETE FROM spielereignis WHERE spielereignis_id = %s", (eid,))
            ok, fehler = db.transaktion(loeschen)
            if ok:
                eigene.remove(eid)
                ui.melden("Ereignis gelöscht.")
            else:
                db.fehler_anzeigen(fehler, "Ereignis nicht gelöscht")

    with eingabe:
        st.subheader("Ereignis eintragen")
        art = st.pills("Was ist passiert?", list(ARTEN), default="Tor", key="ereignis_art")
        art = art or "Tor"
        teams = {int(spiel["heim_teilnahme_id"]): spiel["heim"], int(spiel["gast_teilnahme_id"]): spiel["gast"]}
        team = st.radio("Mannschaft", list(teams), format_func=teams.get, horizontal=True, key="ereignis_team")
        minute = st.number_input("Minute", min_value=1, max_value=130, value=45, step=1, key="ereignis_minute",
                                 help="Nachspielzeit zählt weiter: 90+3 ist Minute 93.")
        namen = {int(r["skid"]): f"{r['nr']} {r['spieler']}" for _, r in bogen.iterrows()}
        drin = ui.auf_dem_platz(bogen, ereignisse, team, minute)
        typ, karte, art_name = ARTEN[art]

        if typ == "wechsel":
            team_bogen = bogen[bogen["teilnahme_id"] == team]
            schon_rein = set(ereignisse.loc[ereignisse["typ"] == "wechsel", "skid_rein"].dropna().astype(int))
            bank = [int(s) for s in team_bogen.loc[~team_bogen["startelf"], "skid"] if int(s) not in schon_rein]
            wechsel_bisher = sum(1 for _, e in ereignisse.iterrows()
                                 if e["typ"] == "wechsel" and int(e["skid"]) in set(team_bogen["skid"].astype(int)))
            raus = st.selectbox("Ausgewechselt", sorted(drin, key=namen.get), format_func=namen.get, index=None,
                                placeholder="Spieler auf dem Platz")
            rein = st.selectbox("Eingewechselt", bank, format_func=namen.get, index=None, placeholder="Spieler von der Bank")
            hinweis = None
            if wechsel_bisher >= WECHSEL_MAX:
                hinweis = f"Die Mannschaft hat schon {WECHSEL_MAX} Mal gewechselt."
            bereit = raus is not None and rein is not None and hinweis is None
        else:
            spieler = st.selectbox("Spieler", sorted(drin, key=namen.get), format_func=namen.get, index=None,
                                   placeholder=f"Spieler, die in Minute {minute} auf dem Platz stehen")
            hinweis = None
            bereit = spieler is not None
        if hinweis:
            st.error(hinweis, icon=":material/error:")

        if st.button("Ereignis speichern", type="primary", disabled=not bereit, width="stretch"):
            def eintragen(cur):
                cur.execute("INSERT INTO spielereignis (minute, spiel_id) VALUES (%s, %s) RETURNING spielereignis_id",
                            (minute, spiel_id))
                eid = cur.fetchone()[0]
                if typ == "tor":
                    cur.execute("INSERT INTO tor (spielereignis_id, spieltag_kader_id) VALUES (%s, %s)", (eid, spieler))
                elif typ == "karte":
                    cur.execute("INSERT INTO karte (spielereignis_id, art, spieltag_kader_id) VALUES (%s, %s, %s)",
                                (eid, karte, spieler))
                else:
                    cur.execute("INSERT INTO wechsel (spielereignis_id, spieltag_kader_id_raus, spieltag_kader_id_rein) "
                                "VALUES (%s, %s, %s)", (eid, raus, rein))
                return eid
            ok, ergebnis = db.transaktion(eintragen)
            if ok:
                st.session_state.setdefault("eigene_ereignisse", []).append(int(ergebnis))
                ui.melden(f"{art_name} in Minute {minute} gespeichert.")
            else:
                db.fehler_anzeigen(ergebnis, "Ereignis nicht gespeichert")

    ui.technik(
        "Ein Ereignis, zwei Tabellen, eine Transaktion",
        "Ein Tor wird als Zeile in `spielereignis` (Spiel, Minute) angelegt; mit der zurückgegebenen ID entsteht "
        "die Zeile im Subtyp `tor`, `karte` oder `wechsel`. Beides passiert in einer Transaktion. Das Ergebnis in "
        "der Tabelle ändert sich sofort, weil es aus den Toren berechnet wird. Die Auswahl zeigt nur Spieler, die "
        "laut Spielberichtsbogen zur gewählten Minute auf dem Platz stehen.",
        "INSERT INTO spielereignis (minute, spiel_id) VALUES (:minute, :spiel) RETURNING spielereignis_id;\n"
        "INSERT INTO tor (spielereignis_id, spieltag_kader_id) VALUES (:neue_id, :spieler);")


# ------------------------------------------------------------------ Spiel verlegen

def seite_verlegen():
    st.title("Spiel verlegen")
    ui.meldung_zeigen()
    staffel_id = ui.staffel_waehler()
    spiel_id, spiel = _spielauswahl(staffel_id, "status IN ('angesetzt', 'aufgestellt')", f"verlegen_{staffel_id}",
                                    leer="In dieser Staffel steht kein Spiel mehr an.")
    if spiel_id is None:
        return
    st.caption(f"Bisher: {ui.datum_lang(spiel['anstoss_zeit'])}, {ui.uhrzeit(spiel['anstoss_zeit'])} Uhr, "
               f"{spiel['sportanlage']}, {spiel['platz']}.")

    anlagen = db.abfrage("SELECT sportanlage_id, name FROM sportanlage ORDER BY name")
    anamen = dict(zip(anlagen["sportanlage_id"].astype(int), anlagen["name"]))
    heute = db.jetzt().date()

    eingabe, belegung = st.columns([2, 3], gap="large")
    with eingabe:
        datum = st.date_input("Neues Datum", value=spiel["anstoss_zeit"].date(), min_value=heute, format="DD.MM.YYYY",
                              key=f"v_datum_{spiel_id}")
        bisher = spiel["anstoss_zeit"].time().replace(second=0, microsecond=0)
        zeiten = sorted({dt.time(h, m) for h in range(9, 21) for m in (0, 15, 30, 45)} | {bisher})
        zeit = st.selectbox("Anstoß", zeiten, index=zeiten.index(bisher), format_func=lambda t: f"{t:%H:%M} Uhr",
                            key=f"v_zeit_{spiel_id}")
        anlage = st.selectbox("Sportanlage", list(anamen), format_func=anamen.get,
                              index=list(anamen).index(int(spiel["sportanlage_id"])), key=f"v_anlage_{spiel_id}")
        plaetze = db.abfrage("SELECT platz_id, name || ' (' || belag || ')' AS name FROM platz "
                             "WHERE sportanlage_id = %s ORDER BY name", (anlage,))
        pnamen = dict(zip(plaetze["platz_id"].astype(int), plaetze["name"]))
        start = list(pnamen).index(int(spiel["platz_id"])) if int(spiel["platz_id"]) in pnamen else 0
        platz = st.selectbox("Platz", list(pnamen), format_func=pnamen.get, index=start, key=f"v_platz_{spiel_id}_{anlage}")
        neu = dt.datetime.combine(datum, zeit)

        konflikt = db.abfrage("""SELECT heim, gast, anstoss_zeit FROM v_spiel
                                 WHERE spiel_id <> %(s)s AND anstoss_zeit::date = %(d)s
                                   AND (heim_teilnahme_id IN (%(h)s, %(g)s) OR gast_teilnahme_id IN (%(h)s, %(g)s))""",
                              {"s": spiel_id, "d": datum, "h": int(spiel["heim_teilnahme_id"]),
                               "g": int(spiel["gast_teilnahme_id"])})
        if not konflikt.empty:
            st.warning("Eine der Mannschaften spielt an diesem Tag schon: " + "; ".join(
                f"{r['heim']} gegen {r['gast']} um {ui.uhrzeit(r['anstoss_zeit'])} Uhr" for _, r in konflikt.iterrows()),
                icon=":material/warning:")
        if st.button("Spiel verlegen", type="primary", width="stretch",
                     disabled=neu == spiel["anstoss_zeit"] and platz == int(spiel["platz_id"])):
            ok, fehler = db.transaktion(lambda cur: cur.execute(
                "UPDATE spiel SET anstoss_zeit = %s, platz_id = %s WHERE spiel_id = %s", (neu, platz, spiel_id)))
            if ok:
                ui.melden(f"Spiel verlegt auf {ui.datum_lang(neu)}, {ui.uhrzeit(neu)} Uhr, {pnamen[platz]}.")
            else:
                db.fehler_anzeigen(fehler, "Spiel nicht verlegt")

    with belegung:
        st.subheader(f"Belegung am {datum:%d.%m.%Y}")
        belegt = db.abfrage("""SELECT anstoss_zeit, anstoss_zeit + interval '2 hours' AS bis, heim, gast, spiel_id
                               FROM v_spiel WHERE platz_id = %s AND anstoss_zeit::date = %s ORDER BY anstoss_zeit""",
                            (platz, datum))
        if belegt.empty:
            st.caption(f"{pnamen[platz]} ist an diesem Tag frei.")
        else:
            belegt["zeit"] = belegt.apply(lambda r: f"{ui.uhrzeit(r['anstoss_zeit'])} bis {ui.uhrzeit(r['bis'])}", axis=1)
            belegt["spiel"] = belegt.apply(lambda r: f"{r['heim']} gegen {r['gast']}"
                                           + (" (dieses Spiel)" if r["spiel_id"] == spiel_id else ""), axis=1)
            st.dataframe(belegt[["zeit", "spiel"]], hide_index=True, width="stretch",
                         column_config={"zeit": "Belegt", "spiel": "Spiel"})

    ui.technik(
        "Exclusion Constraint excl_kein_doppel_platz",
        "Ein Spiel belegt seinen Platz von `anstoss_zeit` an zwei Stunden. Der Constraint lässt keine zwei Spiele "
        "zu, deren Zeiträume sich auf demselben Platz überschneiden. Die App prüft das nicht selbst: Wähle eine "
        "belegte Zeit, und die Datenbank lehnt die Verlegung ab.",
        "UPDATE spiel SET anstoss_zeit = :neu, platz_id = :platz WHERE spiel_id = :spiel;\n\n"
        "-- im Schema\nEXCLUDE USING gist (platz_id WITH =,\n"
        "  tsrange(anstoss_zeit, anstoss_zeit + interval '120 minutes') WITH &&)")


# ------------------------------------------------------------------ Schiedsrichter einteilen

ROLLEN = ["Schiedsrichter", "Assistent 1", "Assistent 2"]


def seite_schiedsrichter():
    st.title("Schiedsrichter einteilen")
    ui.meldung_zeigen()
    staffel_id = ui.staffel_waehler()
    ebene = int(db.wert("SELECT ebene FROM v_staffel WHERE staffel_id = %s", (staffel_id,)))
    offen = db.abfrage("""
        SELECT s.spiel_id FROM v_spiel s
        WHERE s.staffel_id = %s AND s.status IN ('angesetzt', 'aufgestellt')
          AND NOT EXISTS (SELECT 1 FROM spiel_schiedsrichter x WHERE x.spiel_id = s.spiel_id AND x.rolle = 'Schiedsrichter')
        """, (staffel_id,))
    anzahl = len(offen)
    st.caption((f"{anzahl} anstehende Spiele dieser Staffel haben noch keinen Schiedsrichter; sie stehen in der "
                f"Auswahl zuerst. " if anzahl else "Alle anstehenden Spiele dieser Staffel haben einen Schiedsrichter. ")
               + f"In dieser Spielklasse (Ebene {ebene}) dürfen Schiedsrichter mit Freigabe bis Ebene {ebene} pfeifen.")
    spiel_id, spiel = _spielauswahl(staffel_id, "status IN ('angesetzt', 'aufgestellt')", f"sr_{staffel_id}",
                                    leer="In dieser Staffel steht kein Spiel mehr an.",
                                    markiert=offen["spiel_id"].astype(int), zusatz="ohne Schiedsrichter")
    if spiel_id is None:
        return

    eingeteilt = db.abfrage("""SELECT ss.person_id, ss.rolle, p.vorname || ' ' || p.nachname AS name, v.name AS verein
                               FROM spiel_schiedsrichter ss JOIN person p ON p.person_id = ss.person_id
                               JOIN schiedsrichter sr ON sr.person_id = ss.person_id
                               JOIN verein v ON v.verein_id = sr.stammverein_id
                               WHERE ss.spiel_id = %s
                               ORDER BY CASE ss.rolle WHEN 'Schiedsrichter' THEN 0 ELSE 1 END, ss.rolle""", (spiel_id,))
    links, rechts = st.columns([2, 3], gap="large")
    with links:
        st.subheader("Eingeteilt")
        if eingeteilt.empty:
            st.caption("Noch niemand.")
        for _, r in eingeteilt.iterrows():
            with st.container(border=True):
                a, b = st.columns([3, 2], vertical_alignment="center")
                a.markdown(f"**{r['name']}**  \n{r['rolle']}, {r['verein']}")
                weg = b.button("Entfernen", key=f"weg_{r['person_id']}", icon=":material/close:",
                               width="stretch")
            if weg:
                ok, fehler = db.transaktion(lambda cur, pid=int(r["person_id"]): cur.execute(
                    "DELETE FROM spiel_schiedsrichter WHERE spiel_id = %s AND person_id = %s", (spiel_id, pid)))
                if ok:
                    ui.melden(f"{r['name']} ist nicht mehr eingeteilt.", f"sr_tabelle_{spiel_id}")
                else:
                    db.fehler_anzeigen(fehler)

    with rechts:
        freie_rollen = [r for r in ROLLEN if r not in set(eingeteilt["rolle"])]
        st.subheader("Verfügbar")
        kandidaten = db.abfrage("""
            SELECT sr.person_id, p.vorname || ' ' || p.nachname AS name, v.name AS verein, sr.hoechste_ebene,
                   (SELECT count(*) FROM spiel_schiedsrichter x JOIN spiel s2 ON s2.spiel_id = x.spiel_id
                     WHERE x.person_id = sr.person_id AND s2.anstoss_zeit <= (now() AT TIME ZONE 'Europe/Berlin'))::int AS einsaetze
            FROM schiedsrichter sr
            JOIN person p ON p.person_id = sr.person_id
            JOIN verein v ON v.verein_id = sr.stammverein_id
            WHERE sr.hoechste_ebene <= %(ebene)s
              AND sr.stammverein_id NOT IN (%(hv)s, %(gv)s)
              AND NOT EXISTS (SELECT 1 FROM spiel_schiedsrichter x JOIN spiel s2 ON s2.spiel_id = x.spiel_id
                              WHERE x.person_id = sr.person_id AND s2.anstoss_zeit::date = %(tag)s)
            ORDER BY einsaetze, name""",
            {"ebene": ebene, "hv": int(spiel["heim_verein_id"]), "gv": int(spiel["gast_verein_id"]),
             "tag": spiel["anstoss_zeit"].date()})
        st.caption("Neutral, mit passender Freigabe und an diesem Tag noch frei. Wer bisher wenig gepfiffen hat, steht oben.")
        if not freie_rollen:
            st.info("Alle Rollen sind besetzt.")
            return
        auswahl = st.dataframe(kandidaten[["name", "verein", "hoechste_ebene", "einsaetze"]], hide_index=True,
                               width="stretch", height=320, on_select="rerun", selection_mode="single-row",
                               key=ui.schluessel(f"sr_tabelle_{spiel_id}"),
                               column_config={"name": "Name", "verein": "Stammverein",
                                              "hoechste_ebene": st.column_config.NumberColumn("Freigabe", help="Höchste Ebene, die die Person pfeifen darf"),
                                              "einsaetze": "Einsätze"})
        zeilen = auswahl.selection.rows
        rolle = st.selectbox("Rolle", freie_rollen, key=f"rolle_{spiel_id}")
        gewaehlt = kandidaten.iloc[zeilen[0]] if zeilen else None
        if st.button(f"{gewaehlt['name']} einteilen" if gewaehlt is not None else "Person in der Liste wählen",
                     type="primary", disabled=gewaehlt is None, width="stretch"):
            ok, fehler = db.transaktion(lambda cur: cur.execute(
                "INSERT INTO spiel_schiedsrichter (spiel_id, person_id, rolle) VALUES (%s, %s, %s)",
                (spiel_id, int(gewaehlt["person_id"]), rolle)))
            if ok:
                ui.melden(f"{gewaehlt['name']} ist als {rolle} eingeteilt.", f"sr_tabelle_{spiel_id}")
            else:
                db.fehler_anzeigen(fehler, "Nicht eingeteilt")

    ui.technik(
        "Regeln für Schiedsrichter",
        "Die Liste filtert per SQL: Freigabe (`hoechste_ebene`) passend zur Spielklasse, Stammverein weder Heim- "
        "noch Gastverein, an diesem Tag kein anderes Spiel. Diese Regeln stehen bisher nur in der App, nicht in der "
        "Datenbank. Ein Trigger auf `spiel_schiedsrichter` würde sie auch für andere Zugänge erzwingen.")
