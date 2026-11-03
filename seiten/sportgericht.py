"""Sportgericht: offene Verfahren entscheiden, laufende Sperren und Urteile einsehen."""

import streamlit as st

import db
import ui


def seite_sportgericht():
    st.title("Sportgericht")
    ui.meldung_zeigen()
    offen = db.abfrage("""
        SELECT ka.spielereignis_id AS karte_id, p.vorname || ' ' || p.nachname AS spieler, t.mannschaft,
               e.minute, s.anstoss_zeit, s.heim, s.gast, s.staffel_id
        FROM karte ka
        JOIN spielereignis e   ON e.spielereignis_id = ka.spielereignis_id
        JOIN v_spiel s         ON s.spiel_id = e.spiel_id
        JOIN spieltag_kader sk ON sk.spieltag_kader_id = ka.spieltag_kader_id
        JOIN kader k           ON k.kader_id = sk.kader_id
        JOIN person p          ON p.person_id = k.person_id
        JOIN v_teilnahme t     ON t.teilnahme_id = k.teilnahme_id
        WHERE ka.art = 'Rot' AND NOT EXISTS (SELECT 1 FROM urteil u WHERE u.spielereignis_id = ka.spielereignis_id)
        ORDER BY s.anstoss_zeit""")
    sperren = db.abfrage("SELECT * FROM v_sperren_aktuell ORDER BY offen DESC, wieder_spielberechtigt_ab, spieler")

    a, b, c = st.columns(3)
    a.metric("Offene Verfahren", len(offen))
    b.metric("Laufende Sperren", len(sperren))
    c.metric("Davon durch Urteil", int((sperren["art"] == "Urteil").sum()) if not sperren.empty else 0)

    reiter = st.tabs(["Offene Verfahren", "Laufende Sperren", "Urteile"])
    with reiter[0]:
        _offene_verfahren(offen)
    with reiter[1]:
        if sperren.empty:
            st.caption("Zurzeit ist niemand gesperrt.")
        else:
            df = sperren.copy()
            df["grund"] = df.apply(lambda r: r["art"] + (f": {r['vergehen']}" if r["vergehen"] else ""), axis=1)
            df["durchsetzung"] = df["vom_trigger_geprueft"].map({True: "Datenbank (Trigger)", False: "nur App"})
            st.dataframe(df[["spieler", "mannschaft", "grund", "sperre_spiele", "abgesessen", "offen",
                             "wieder_spielberechtigt_ab", "durchsetzung"]], hide_index=True, width="stretch",
                         column_config={
                             "spieler": "Spieler", "mannschaft": "Mannschaft", "grund": "Grund",
                             "sperre_spiele": "Sperre", "abgesessen": "Abgesessen", "offen": "Offen",
                             "wieder_spielberechtigt_ab": st.column_config.DatetimeColumn("Wieder spielberechtigt ab",
                                                                                          format="DD.MM.YYYY"),
                             "durchsetzung": "Geprüft durch"})
            st.caption("Gelb-Rot und jede fünfte Gelbe Karte sperren ein Spiel, eine Rote Karte bis zum Urteil "
                       "vorläufig zwei. Gezählt werden die Spiele der Mannschaft nach der Karte.")
    with reiter[2]:
        urteile = db.abfrage("""
            SELECT u.datum, p.vorname || ' ' || p.nachname AS spieler, t.mannschaft, sk.vergehen,
                   u.sperre_spiele, u.tatsaechliche_geldstrafe AS geldstrafe, sp.anstoss_zeit AS spiel
            FROM urteil u
            JOIN strafenkatalog sk  ON sk.strafe_id = u.strafe_id
            JOIN karte ka           ON ka.spielereignis_id = u.spielereignis_id
            JOIN spielereignis e    ON e.spielereignis_id = ka.spielereignis_id
            JOIN spiel sp           ON sp.spiel_id = e.spiel_id
            JOIN spieltag_kader b   ON b.spieltag_kader_id = ka.spieltag_kader_id
            JOIN kader k            ON k.kader_id = b.kader_id
            JOIN person p           ON p.person_id = k.person_id
            JOIN v_teilnahme t      ON t.teilnahme_id = k.teilnahme_id
            ORDER BY u.datum DESC, spieler""")
        st.dataframe(urteile, hide_index=True, width="stretch", column_config={
            "datum": st.column_config.DateColumn("Urteil vom", format="DD.MM.YYYY"), "spieler": "Spieler",
            "mannschaft": "Mannschaft", "vergehen": "Vergehen", "sperre_spiele": "Sperre (Spiele)",
            "geldstrafe": st.column_config.NumberColumn("Geldstrafe", format="%.2f €"),
            "spiel": st.column_config.DateColumn("Spiel vom", format="DD.MM.YYYY")})

    ui.technik(
        "Vom Urteil zur Sperre",
        "Ein Urteil verweist auf die Rote Karte (`urteil.spielereignis_id`) und legt die Sperre in Spielen fest. "
        "Gespeichert wird nur das Urteil. Wie viele Spiele schon abgesessen sind, berechnet die View "
        "`v_sperren_aktuell` aus dem Spielplan. Beim Aufstellen zählt der Trigger dieselben Spiele und lehnt "
        "gesperrte Spieler ab.",
        "INSERT INTO urteil (datum, sperre_spiele, tatsaechliche_geldstrafe, spielereignis_id, strafe_id)\n"
        "VALUES (:datum, :spiele, :geldstrafe, :rote_karte, :tatbestand);")


def _offene_verfahren(offen):
    if offen.empty:
        st.caption("Alle Roten Karten sind entschieden.")
        return
    katalog = db.abfrage("SELECT strafe_id, vergehen, standard_sperre_spiele, geldstrafe_eur FROM strafenkatalog "
                         "ORDER BY standard_sperre_spiele, vergehen")
    kat = {int(r["strafe_id"]): r for _, r in katalog.iterrows()}
    heute = db.jetzt().date()
    texte = {int(r["karte_id"]): f"{r['spieler']} ({r['mannschaft']}), Rot in Minute {r['minute']}, "
                                 f"{r['heim']} gegen {r['gast']} am {r['anstoss_zeit']:%d.%m.%Y}"
             for _, r in offen.iterrows()}
    karte_id = st.selectbox("Verfahren", list(texte), format_func=texte.get, key="verfahren")
    fall = offen[offen["karte_id"] == karte_id].iloc[0]

    tatbestand = st.selectbox("Tatbestand", list(kat), key=f"tat_{karte_id}",
                              format_func=lambda i: f"{kat[i]['vergehen']} (üblich: {ui.spiele_wort(int(kat[i]['standard_sperre_spiele']))}, "
                                                    f"{kat[i]['geldstrafe_eur']:.0f} €)")
    with st.form(f"urteil_{karte_id}_{tatbestand}"):
        a, b, c = st.columns(3)
        spiele = a.number_input("Sperre in Spielen", min_value=1, max_value=30,
                                value=int(kat[tatbestand]["standard_sperre_spiele"]))
        geld = b.number_input("Geldstrafe in Euro", min_value=0.0, step=25.0,
                              value=float(kat[tatbestand]["geldstrafe_eur"]))
        datum = c.date_input("Urteil vom", value=heute, min_value=fall["anstoss_zeit"].date(), format="DD.MM.YYYY")
        absenden = st.form_submit_button("Urteil speichern", type="primary")
    if absenden:
        ok, fehler = db.transaktion(lambda cur: cur.execute(
            "INSERT INTO urteil (datum, sperre_spiele, tatsaechliche_geldstrafe, spielereignis_id, strafe_id) "
            "VALUES (%s, %s, %s, %s, %s)", (datum, spiele, geld, karte_id, tatbestand)))
        if ok:
            ab = db.wert("SELECT wieder_spielberechtigt_ab FROM v_sperren_aktuell WHERE karte_id = %s", (karte_id,))
            zusatz = f" Wieder spielberechtigt ab {ab:%d.%m.%Y}." if ab is not None else ""
            ui.melden(f"Urteil gespeichert: {fall['spieler']} ist für {ui.spiele_wort(spiele)} gesperrt.{zusatz}")
        else:
            db.fehler_anzeigen(fehler, "Urteil nicht gespeichert")
