"""Verband: Kennzahlen der Saison und Datenprüfung."""

import altair as alt
import streamlit as st

import db
import ui

RASEN = "#1E7D4C"
TEXT = "#1F2622"
LEISE = "#5E6862"


def seite_verband():
    st.title("Saison im Überblick")
    k = db.abfrage("""
        SELECT (SELECT count(*) FROM verein)                                AS vereine,
               (SELECT count(*) FROM staffel_teilnahme)                     AS mannschaften,
               (SELECT count(*) FROM kader)                                 AS spieler,
               (SELECT count(*) FROM v_spiel WHERE status = 'gespielt')     AS gespielt,
               (SELECT count(*) FROM spiel)                                 AS spiele,
               (SELECT count(*) FROM tor)                                   AS tore,
               (SELECT count(*) FROM v_spiel WHERE status = 'bericht_fehlt') AS fehlend,
               (SELECT saison FROM v_staffel LIMIT 1)                       AS saison""").iloc[0]
    st.caption(f"Saison {k['saison']}, Stand {db.jetzt():%d.%m.%Y, %H:%M} Uhr.")
    a, b, c, d, e = st.columns(5)
    a.metric("Vereine", int(k["vereine"]))
    b.metric("Mannschaften", int(k["mannschaften"]))
    c.metric("Spieler im Kader", f"{int(k['spieler']):,}".replace(",", "."))
    d.metric("Gespielt", f"{int(k['gespielt'])} von {int(k['spiele'])}")
    e.metric("Tore pro Spiel", f"{k['tore'] / max(int(k['gespielt']), 1):.2f}".replace(".", ","))
    if int(k["fehlend"]):
        st.warning(f"{int(k['fehlend'])} Spiele sind angepfiffen, aber ohne Spielbericht.", icon=":material/assignment_late:")

    links, rechts = st.columns(2, gap="large")
    with links:
        st.subheader("Tore pro Spiel nach Staffel")
        df = db.abfrage("""
            SELECT st.kurzname AS name, st.ebene, st.nummer, count(s.spiel_id)::int AS spiele,
                   coalesce(sum(s.tore_heim + s.tore_gast), 0)::int AS tore
            FROM v_staffel st LEFT JOIN v_spiel s ON s.staffel_id = st.staffel_id AND s.status = 'gespielt'
            GROUP BY st.staffel_id, st.kurzname, st.ebene, st.nummer ORDER BY st.ebene, st.nummer""")
        # numeric kommt als Decimal an; Altair braucht float
        df["schnitt"] = (df["tore"].astype(float) / df["spiele"].clip(lower=1).astype(float)).round(2)
        df["text"] = df["schnitt"].map(lambda x: f"{x:.2f}".replace(".", ","))
        df["hinweis"] = df.apply(lambda r: f"{int(r['tore'])} Tore in {int(r['spiele'])} Spielen", axis=1)
        reihenfolge = list(df["name"])
        basis = alt.Chart(df).encode(
            y=alt.Y("name:N", sort=reihenfolge, title=None,
                    axis=alt.Axis(labelColor=TEXT, labelFontSize=13, ticks=False, domain=False, labelPadding=8,
                                  labelLimit=220)),
            x=alt.X("schnitt:Q", title=None, axis=None, scale=alt.Scale(domain=[0, float(df["schnitt"].max()) * 1.15])),
            tooltip=[alt.Tooltip("name:N", title="Staffel"), alt.Tooltip("text:N", title="Tore pro Spiel"),
                     alt.Tooltip("hinweis:N", title="Grundlage")])
        balken = basis.mark_bar(color=RASEN, size=22, cornerRadiusEnd=4)
        werte = basis.mark_text(align="left", dx=6, color=TEXT, fontSize=13).encode(text="text:N")
        st.altair_chart((balken + werte).properties(height=46 * len(df)).configure_view(stroke=None),
                        width="stretch")
        st.caption("Die Werte stehen am Ende der Balken; der Tooltip zeigt die Grundlage.")

    with rechts:
        st.subheader("Bezirke")
        bezirke = db.abfrage("""
            SELECT b.name AS bezirk,
                   (SELECT count(*) FROM verein v WHERE v.bezirk_id = b.bezirk_id) AS vereine,
                   (SELECT count(*) FROM v_teilnahme t JOIN verein v ON v.verein_id = t.verein_id
                     WHERE v.bezirk_id = b.bezirk_id) AS mannschaften,
                   (SELECT count(*) FROM platz p JOIN sportanlage sa ON sa.sportanlage_id = p.sportanlage_id
                     WHERE sa.bezirk_id = b.bezirk_id) AS plaetze
            FROM bezirk b ORDER BY mannschaften DESC, bezirk""")
        st.dataframe(bezirke, hide_index=True, width="stretch", height=38 + 35 * len(bezirke),
                     column_config={"bezirk": st.column_config.TextColumn("Bezirk", width="medium"),
                                    "vereine": st.column_config.NumberColumn("Vereine", width="small"),
                                    "mannschaften": st.column_config.NumberColumn("Mannschaften"),
                                    "plaetze": st.column_config.NumberColumn("Plätze", width="small")})

    st.subheader("Datenprüfung")
    st.caption("Prüft alle Datensätze gegen 25 Regeln: Spielberechtigung, Pässe, Platzbelegung, Schiedsrichter, "
               "Spielberichte, Sperren. Jede Zeile zählt die Verstöße.")
    if st.button("Daten jetzt prüfen", icon=":material/fact_check:"):
        with st.spinner("Prüfe …"):
            ergebnis = db.abfrage("SELECT nr, pruefung, verstoesse FROM v_datenpruefung ORDER BY nr")
        summe = int(ergebnis["verstoesse"].sum())
        if summe == 0:
            st.success("Alle 25 Regeln sind eingehalten.", icon=":material/check_circle:")
        else:
            st.error(f"{summe} Verstöße gefunden. Die betroffenen Regeln stehen oben in der Liste.", icon=":material/error:")
        ergebnis["ok"] = ergebnis["verstoesse"] == 0
        ergebnis = ergebnis.sort_values(["ok", "nr"])
        st.dataframe(ergebnis[["nr", "pruefung", "verstoesse"]], hide_index=True, width="stretch",
                     height=38 + 35 * len(ergebnis),
                     column_config={"nr": st.column_config.NumberColumn("Nr.", width="small"),
                                    "pruefung": "Regel", "verstoesse": "Verstöße"})
    ui.technik(
        "View v_datenpruefung",
        "Jede Regel ist eine Abfrage, die Verstöße zählt; die View fasst alle 25 mit `UNION ALL` zusammen. "
        "Einige Regeln erzwingt die Datenbank ohnehin (Constraints, Trigger), andere prüft nur diese View, "
        "zum Beispiel die Neutralität der Schiedsrichter.",
        "SELECT nr, pruefung, verstoesse FROM v_datenpruefung ORDER BY nr;")
