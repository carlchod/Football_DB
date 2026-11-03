"""Seiten für Vereinsverantwortliche: Aufstellung melden, Spielerpass und Vereinswechsel."""

import datetime as dt

import pandas as pd
import streamlit as st

import db
import ui

STARTELF = 11
BANK_MAX = 7


def _verein_und_mannschaft():
    vereine = db.abfrage("""SELECT DISTINCT t.verein_id, t.verein FROM v_teilnahme t ORDER BY t.verein""")
    namen = dict(zip(vereine["verein_id"].astype(int), vereine["verein"]))
    a, b = st.columns(2)
    verein_id = a.selectbox("Verein", list(namen), format_func=namen.get, key="mein_verein")
    teams = db.abfrage("""SELECT teilnahme_id, mannschaft FROM v_teilnahme WHERE verein_id = %s ORDER BY nummer""",
                       (verein_id,))
    tnamen = dict(zip(teams["teilnahme_id"].astype(int), teams["mannschaft"]))
    teilnahme_id = b.selectbox("Mannschaft", list(tnamen), format_func=tnamen.get, key=f"team_{verein_id}")
    return verein_id, teilnahme_id


# ------------------------------------------------------------------ Aufstellung melden

def seite_aufstellung():
    st.title("Aufstellung melden")
    ui.meldung_zeigen()
    st.caption("Wähle das Spiel, kreuze elf Spieler für die Startelf und bis zu sieben für die Ersatzbank an. "
               "Gesperrte Spieler sind markiert.")
    _, teilnahme_id = _verein_und_mannschaft()

    spiele = db.abfrage("""
        SELECT * FROM v_spiel
        WHERE %(t)s IN (heim_teilnahme_id, gast_teilnahme_id)
          AND (status IN ('angesetzt', 'aufgestellt') OR (status = 'bericht_fehlt'))
        ORDER BY anstoss_zeit LIMIT 5""", {"t": teilnahme_id})
    if spiele.empty:
        st.info("Für diese Mannschaft steht kein Spiel an.")
        return

    def spieltext(sid):
        s = spiele[spiele["spiel_id"] == sid].iloc[0]
        gemeldet = ", gemeldet" if s["status"] == "aufgestellt" else ""
        return (f"{s['spieltag']}. Spieltag: {s['heim']} gegen {s['gast']}, "
                f"{ui.datum_kurz(s['anstoss_zeit'])} {ui.uhrzeit(s['anstoss_zeit'])} Uhr{gemeldet}")
    spiel_id = ui.stabile_auswahl(st.radio, "Spiel", [int(i) for i in spiele["spiel_id"]], spieltext,
                                  merk=f"auf_spiel_{teilnahme_id}")

    kader = db.abfrage("""
        SELECT k.kader_id, k.rueckennummer AS nr, p.vorname || ' ' || p.nachname AS spieler, sp.position,
               fn_sperrgrund(k.kader_id, %(spiel)s) AS sperre,
               coalesce(sk.startelf, false) AS startelf,
               (sk.spieltag_kader_id IS NOT NULL AND NOT sk.startelf) AS bank
        FROM kader k
        JOIN person p   ON p.person_id = k.person_id
        JOIN spieler sp ON sp.person_id = k.person_id
        LEFT JOIN spieltag_kader sk ON sk.kader_id = k.kader_id AND sk.spiel_id = %(spiel)s
        WHERE k.teilnahme_id = %(t)s
        ORDER BY CASE sp.position WHEN 'Tor' THEN 1 WHEN 'Abwehr' THEN 2 WHEN 'Mittelfeld' THEN 3 ELSE 4 END, k.rueckennummer
        """, {"spiel": spiel_id, "t": teilnahme_id})
    vorher_gemeldet = bool((kader["startelf"] | kader["bank"]).any())
    kader["status"] = kader["sperre"].fillna("spielberechtigt")

    editor_name = f"editor_{spiel_id}_{teilnahme_id}"
    editor = ui.schluessel(editor_name)
    tabelle = st.data_editor(
        kader[["startelf", "bank", "nr", "spieler", "position", "status"]],
        key=editor, hide_index=True, width="stretch",
        height=38 + 35 * len(kader),
        disabled=["nr", "spieler", "position", "status"],
        column_config={
            "startelf": st.column_config.CheckboxColumn("Startelf", width="small"),
            "bank": st.column_config.CheckboxColumn("Bank", width="small"),
            "nr": st.column_config.NumberColumn("Nr.", width="small"),
            "spieler": "Spieler", "position": "Position", "status": st.column_config.TextColumn("Status", width="large")})

    start = tabelle[tabelle["startelf"]]
    bank = tabelle[tabelle["bank"]]
    doppelt = tabelle[tabelle["startelf"] & tabelle["bank"]]
    gesperrt = tabelle[(tabelle["startelf"] | tabelle["bank"]) & (tabelle["status"] != "spielberechtigt")]

    a, b, c = st.columns(3)
    a.metric("Startelf", f"{len(start)} von {STARTELF}")
    b.metric("Ersatzbank", f"{len(bank)} von höchstens {BANK_MAX}")
    c.metric("Torhüter in der Startelf", int((start["position"] == "Tor").sum()))

    probleme = []
    leer = start.empty and bank.empty
    if leer:
        st.caption("Noch niemand angekreuzt.")
    elif len(start) != STARTELF:
        probleme.append(f"Die Startelf braucht genau {STARTELF} Spieler.")
    if len(start) == STARTELF and not (start["position"] == "Tor").any():
        st.warning("In der Startelf steht kein Torhüter. Die Meldung ist trotzdem möglich.", icon=":material/warning:")
    if len(bank) > BANK_MAX:
        probleme.append(f"Auf der Ersatzbank sind höchstens {BANK_MAX} Spieler erlaubt.")
    if not doppelt.empty:
        probleme.append("Ein Spieler kann nicht gleichzeitig in der Startelf und auf der Bank stehen: "
                        + ", ".join(doppelt["spieler"]) + ".")

    with st.expander("Für die Präsentation: Sperrprüfung der Datenbank zeigen"):
        an_db = st.toggle("Gesperrte Spieler trotzdem an die Datenbank senden", key="sperre_testen",
                          help="Dann prüft nur noch der Trigger. Er lehnt Spieler mit laufender Urteilssperre ab.")
    if not gesperrt.empty:
        text = "Gesperrt: " + "; ".join(f"{r['spieler']} ({r['status']})" for _, r in gesperrt.iterrows())
        if an_db:
            st.warning(text + ". Die Meldung geht trotzdem an die Datenbank.", icon=":material/warning:")
        else:
            probleme.append(text + ".")

    for p in probleme:
        st.error(p, icon=":material/error:")

    links, rechts = st.columns([1, 1])
    if links.button("Aufstellung speichern", type="primary", disabled=bool(probleme) or leer, width="stretch"):
        kader_ids = [int(i) for i in kader["kader_id"]]
        zeilen = [(bool(r["startelf"]), int(kader.at[i, "kader_id"])) for i, r in tabelle.iterrows()
                  if r["startelf"] or r["bank"]]

        def speichern(cur):
            cur.execute("DELETE FROM spieltag_kader WHERE spiel_id = %s AND kader_id = ANY(%s)", (spiel_id, kader_ids))
            for ist_start, kader_id in zeilen:
                cur.execute("INSERT INTO spieltag_kader (startelf, spiel_id, kader_id) VALUES (%s, %s, %s)",
                            (ist_start, spiel_id, kader_id))
        ok, fehler = db.transaktion(speichern)
        if ok:
            ui.melden(f"Aufstellung gespeichert: {len(start)} Spieler in der Startelf, {len(bank)} auf der Bank.",
                      editor_name)
        else:
            db.fehler_anzeigen(fehler, "Aufstellung nicht gespeichert")
    if vorher_gemeldet and rechts.button("Meldung zurückziehen", width="stretch"):
        ok, fehler = db.transaktion(lambda cur: cur.execute(
            "DELETE FROM spieltag_kader WHERE spiel_id = %s AND kader_id = ANY(%s)",
            (spiel_id, [int(i) for i in kader["kader_id"]])))
        if ok:
            ui.melden("Meldung zurückgezogen.", editor_name)
        else:
            db.fehler_anzeigen(fehler, "Meldung nicht zurückgezogen")

    ui.technik(
        "Trigger blockiere_gesperrte_spieler",
        "Beim Speichern schreibt die App jede Zeile in `spieltag_kader`. Vor jedem Einfügen prüft der Trigger, "
        "ob es zu einer Karte des Spielers aus einem früheren Spiel ein Urteil gibt, dessen Sperre noch nicht "
        "abgesessen ist. Dann bricht die ganze Transaktion ab. Die Markierung in der Liste kommt aus der Funktion "
        "`fn_sperrgrund`, die zusätzlich Gelb-Rot, die fünfte Gelbe Karte und offene Verfahren kennt. Diese "
        "Sperren prüft der Trigger bisher nicht.",
        "SELECT kader_id, fn_sperrgrund(kader_id, :spiel) FROM kader WHERE teilnahme_id = :mannschaft;\n\n"
        "-- Speichern in einer Transaktion\n"
        "DELETE FROM spieltag_kader WHERE spiel_id = :spiel AND kader_id = ANY(:kader);\n"
        "INSERT INTO spieltag_kader (startelf, spiel_id, kader_id) VALUES (:startelf, :spiel, :kader_id);")


# ------------------------------------------------------------------ Spielerpass und Vereinswechsel

def seite_paesse():
    st.title("Spielerpass und Vereinswechsel")
    ui.meldung_zeigen()
    heute = db.jetzt().date()
    spieler = db.abfrage("""
        SELECT p.person_id, p.nachname || ', ' || p.vorname AS name, extract(year FROM p.geburtsdatum)::int AS jg,
               (SELECT v.name FROM spielerpass sp JOIN verein v ON v.verein_id = sp.verein_id
                 WHERE sp.person_id = p.person_id AND current_date BETWEEN sp.gueltig_ab AND sp.gueltig_bis LIMIT 1) AS verein
        FROM person p JOIN spieler s ON s.person_id = p.person_id ORDER BY p.nachname, p.vorname""")
    texte = {int(r["person_id"]): f"{r['name']} ({r['jg']}), {r['verein'] or 'ohne gültigen Pass'}"
             for _, r in spieler.iterrows()}
    person_id = st.selectbox("Spieler suchen", list(texte), format_func=texte.get, index=None,
                             placeholder="Nachnamen eingeben", key="pass_spieler")
    if person_id is None:
        st.caption("Ein Spieler darf zu jedem Zeitpunkt nur einen gültigen Pass haben. "
                   "Bei einem Vereinswechsel endet der alte Pass am Tag vor dem neuen.")
        a, b = st.columns(2)
        a.metric("Spieler mit gültigem Pass", f"{int(spieler['verein'].notna().sum()):,}".replace(",", "."))
        b.metric("Ohne gültigen Pass", int(spieler["verein"].isna().sum()),
                 help="Diese Spieler dürfen zurzeit in keinem Spiel eingesetzt werden.")
        st.subheader("Zuletzt angelegte Pässe")
        neueste = db.abfrage("""SELECT p.vorname || ' ' || p.nachname AS spieler, v.name AS verein,
                                       sp.gueltig_ab, sp.gueltig_bis
                                FROM spielerpass sp JOIN person p ON p.person_id = sp.person_id
                                JOIN verein v ON v.verein_id = sp.verein_id
                                ORDER BY sp.pass_id DESC LIMIT 8""")
        st.dataframe(neueste, hide_index=True, width="stretch", column_config={
            "spieler": "Spieler", "verein": "Verein",
            "gueltig_ab": st.column_config.DateColumn("Gültig ab", format="DD.MM.YYYY"),
            "gueltig_bis": st.column_config.DateColumn("Gültig bis", format="DD.MM.YYYY")})
        return

    paesse = db.abfrage("""SELECT sp.pass_id, v.name AS verein, sp.gueltig_ab, sp.gueltig_bis
                           FROM spielerpass sp JOIN verein v ON v.verein_id = sp.verein_id
                           WHERE sp.person_id = %s ORDER BY sp.gueltig_ab DESC""", (person_id,))
    paesse["status"] = paesse.apply(lambda r: "gültig" if r["gueltig_ab"] <= heute <= r["gueltig_bis"]
                                    else ("künftig" if r["gueltig_ab"] > heute else "abgelaufen"), axis=1)
    kader = db.abfrage("""SELECT t.mannschaft, s.name AS staffel, k.rueckennummer FROM kader k
                          JOIN v_teilnahme t ON t.teilnahme_id = k.teilnahme_id
                          JOIN v_staffel s ON s.staffel_id = t.staffel_id WHERE k.person_id = %s""", (person_id,))

    links, rechts = st.columns([3, 2], gap="large")
    with links:
        st.subheader("Pässe")
        st.dataframe(paesse[["verein", "gueltig_ab", "gueltig_bis", "status"]], hide_index=True, width="stretch",
                     column_config={"verein": "Verein",
                                    "gueltig_ab": st.column_config.DateColumn("Gültig ab", format="DD.MM.YYYY"),
                                    "gueltig_bis": st.column_config.DateColumn("Gültig bis", format="DD.MM.YYYY"),
                                    "status": "Status"})
        if not kader.empty:
            k = kader.iloc[0]
            st.caption(f"Im Kader von {k['mannschaft']} ({k['staffel']}) mit der Nummer {k['rueckennummer']}.")

    with rechts:
        st.subheader("Vereinswechsel")
        vereine = db.abfrage("SELECT verein_id, name FROM verein ORDER BY name")
        vnamen = dict(zip(vereine["verein_id"].astype(int), vereine["name"]))
        with st.form("wechsel"):
            neu = st.selectbox("Neuer Verein", list(vnamen), format_func=vnamen.get, index=None,
                               placeholder="Verein wählen")
            ab = st.date_input("Gültig ab", value=heute, format="DD.MM.YYYY")
            bis = st.date_input("Gültig bis", value=dt.date(heute.year + 2, 6, 30), format="DD.MM.YYYY")
            beenden = st.checkbox("Bisherigen Pass am Vortag beenden", value=True,
                                  help="Ohne diesen Schritt lehnt die Datenbank den neuen Pass ab, "
                                       "weil sich zwei Pässe überschneiden würden.")
            absenden = st.form_submit_button("Pass ausstellen", type="primary", width="stretch")
        if absenden:
            if neu is None:
                st.error("Bitte den neuen Verein wählen.", icon=":material/error:")
            else:
                def wechseln(cur):
                    if beenden:
                        cur.execute("""UPDATE spielerpass SET gueltig_bis = %(ab)s::date - 1
                                       WHERE person_id = %(p)s AND gueltig_ab < %(ab)s AND gueltig_bis >= %(ab)s""",
                                    {"ab": ab, "p": person_id})
                    cur.execute("INSERT INTO spielerpass (gueltig_ab, gueltig_bis, person_id, verein_id) "
                                "VALUES (%s, %s, %s, %s)", (ab, bis, person_id, neu))
                ok, fehler = db.transaktion(wechseln)
                if ok:
                    ui.melden(f"Pass für {vnamen[neu]} ab {ab:%d.%m.%Y} ausgestellt.")
                else:
                    db.fehler_anzeigen(fehler, "Pass nicht ausgestellt")

    ui.technik(
        "Exclusion Constraint exclude_kein_doppelpass",
        "Die Datenbank verhindert überlappende Pässe einer Person mit einem Exclusion Constraint über den "
        "Zeitraum `daterange(gueltig_ab, gueltig_bis, '[]')`. Der Wechsel läuft in einer Transaktion: erst wird "
        "der alte Pass beendet, dann der neue eingefügt. Schlägt ein Schritt fehl, bleibt alles unverändert. "
        "Lass das Häkchen weg, um die Ablehnung durch die Datenbank zu sehen.",
        "UPDATE spielerpass SET gueltig_bis = :ab - 1\n WHERE person_id = :spieler AND gueltig_ab < :ab AND gueltig_bis >= :ab;\n"
        "INSERT INTO spielerpass (gueltig_ab, gueltig_bis, person_id, verein_id) VALUES (:ab, :bis, :spieler, :verein);")
