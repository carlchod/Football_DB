"""Gemeinsame Bausteine: Stil, Datumsformate, Staffelauswahl, Anzeigetafel, Tabelle, Spielverlauf."""

import datetime as dt
from html import escape

import pandas as pd
import streamlit as st

import db

SEITEN: dict = {}          # wird in app.py gefüllt: Name -> st.Page (für st.switch_page)

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
          "Oktober", "November", "Dezember"]
POSITIONEN = {"Tor": 1, "Abwehr": 2, "Mittelfeld": 3, "Sturm": 4}

CSS = """
<style>
:root {
  --rasen: #1E7D4C; --tafel: #163B2E; --kreide: #FFFFFF; --text: #1F2622; --leise: #5E6862;
  --linie: #D9DFDA; --flaeche: #F2F5F2; --gelb: #F2C12E; --rot: #C8323C;
}
/* Anzeigetafel für Ergebnisse */
.zl-tafel { display: inline-block; min-width: 4.6rem; padding: .1rem .55rem; border-radius: 4px;
  background: var(--tafel); color: var(--kreide); text-align: center; white-space: nowrap;
  font-family: "Barlow Condensed", sans-serif; font-weight: 700; font-size: 1.5rem; line-height: 1.35;
  font-variant-numeric: tabular-nums; }
.zl-tafel.offen { background: transparent; color: var(--tafel); box-shadow: inset 0 0 0 1px var(--linie);
  font-size: 1.15rem; line-height: 1.75; }
.zl-tafel.gross { font-size: 3.25rem; min-width: 8rem; padding: .1rem 1rem; }

/* Eine Spielzeile im Spieltag */
.zl-spiel { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: .9rem; }
.zl-spiel .heim { text-align: right; font-weight: 600; }
.zl-spiel .gast { font-weight: 600; }
.zl-meta { color: var(--leise); font-size: .875rem; margin-top: .15rem; }
.zl-status { display: inline-block; font-size: .8rem; padding: 0 .45rem; border-radius: 3px;
  background: #FFF6D6; color: #6B5200; margin-left: .35rem; }

/* Kopf im Spielbericht */
.zl-kopf { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 1.5rem;
  padding: 1.25rem 0 .75rem; }
.zl-kopf .team { font-family: "Barlow Condensed", sans-serif; font-weight: 700; font-size: 1.9rem; line-height: 1.1; }
.zl-kopf .heim { text-align: right; }

/* Tabelle */
.zl-tabelle-rahmen { overflow-x: auto; }
table.zl-tabelle { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
table.zl-tabelle th { text-align: right; font-weight: 600; color: var(--leise); font-size: .85rem;
  padding: .35rem .5rem; border-bottom: 1px solid var(--linie); white-space: nowrap; }
table.zl-tabelle td { text-align: right; padding: .42rem .5rem; border-bottom: 1px solid var(--flaeche); white-space: nowrap; }
table.zl-tabelle th.links, table.zl-tabelle td.links { text-align: left; }
table.zl-tabelle td.mannschaft { text-align: left; font-weight: 600; white-space: normal; min-width: 11rem; }
table.zl-tabelle td.punkte { font-weight: 700; }
table.zl-tabelle.kompakt td.mannschaft { min-width: 0; font-weight: 500; }
table.zl-tabelle.kompakt td { padding: .32rem .4rem; }
table.zl-tabelle tr.markiert td { background: #E6F2EA; }
.zl-form { display: inline-flex; gap: 3px; }
.zl-form span { display: inline-block; width: 1.25rem; height: 1.25rem; line-height: 1.25rem; text-align: center;
  font-size: .75rem; font-weight: 700; border-radius: 3px; color: #fff; }
.zl-form .S { background: var(--rasen); } .zl-form .U { background: #8C968F; } .zl-form .N { background: var(--rot); }

/* Karten als kleine Rechtecke, wie auf dem Platz */
.zl-karte { display: inline-block; width: .6rem; height: .85rem; border-radius: 2px; vertical-align: -1px; margin: 0 .15rem; }
.zl-karte.Gelb { background: var(--gelb); } .zl-karte.Rot { background: var(--rot); }
.zl-karte.Gelb-Rot { background: linear-gradient(135deg, var(--gelb) 50%, var(--rot) 50%); }
.zl-rein { color: var(--rasen); font-weight: 700; } .zl-raus { color: var(--rot); font-weight: 700; }

/* Aufstellung */
.zl-aufstellung { list-style: none; padding: 0; margin: 0 0 .5rem; }
.zl-aufstellung li { display: flex; gap: .6rem; padding: .25rem 0; border-bottom: 1px solid var(--flaeche); }
.zl-aufstellung .nr { width: 1.6rem; text-align: right; color: var(--leise); font-variant-numeric: tabular-nums; }
.zl-aufstellung .zusatz { margin-left: auto; color: var(--leise); font-size: .875rem; white-space: nowrap; }

/* Spielverlauf: Heim links, Minute Mitte, Gast rechts */
.zl-verlauf { display: grid; grid-template-columns: 1fr 3.4rem 1fr; row-gap: .1rem; }
.zl-verlauf > div { padding: .3rem 0; border-bottom: 1px solid var(--flaeche); }
.zl-verlauf .h { text-align: right; padding-right: .75rem; }
.zl-verlauf .m { text-align: center; font-family: "Barlow Condensed", sans-serif; font-weight: 700; color: var(--leise); }
.zl-verlauf .g { padding-left: .75rem; }
.zl-verlauf .stand { font-family: "Barlow Condensed", sans-serif; font-weight: 700; margin: 0 .3rem; }

@media (max-width: 640px) {
  .zl-spiel { gap: .45rem; } .zl-tafel { min-width: 3.8rem; font-size: 1.25rem; }
  .zl-kopf .team { font-size: 1.35rem; } .zl-tafel.gross { font-size: 2.25rem; min-width: 5.5rem; }
}
</style>
"""


def stil():
    st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ Formate

def datum_lang(d) -> str:
    return f"{WOCHENTAGE[d.weekday()]}, {d.day}. {MONATE[d.month - 1]} {d.year}"


def datum_kurz(d) -> str:
    return f"{WOCHENTAGE[d.weekday()][:2]} {d:%d.%m.}"


def uhrzeit(d) -> str:
    return f"{d:%H:%M}"


def spiele_wort(n: int) -> str:
    return "1 Spiel" if n == 1 else f"{n} Spiele"


def tordifferenz(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


# ------------------------------------------------------------------ Staffelauswahl (seitenübergreifend)

def staffeln() -> pd.DataFrame:
    return db.abfrage("SELECT staffel_id, name, kurzname, ebene, spielklasse, saison FROM v_staffel "
                      "ORDER BY ebene, nummer")


def staffel_waehler(label: str = "Staffel") -> int:
    """Segmentierte Auswahl der Staffel; die Wahl bleibt beim Seitenwechsel erhalten."""
    df = staffeln()
    namen = dict(zip(df["staffel_id"].astype(int), df["kurzname"]))
    ids = list(namen)
    if st.session_state.get("staffel") not in ids:
        st.session_state["staffel"] = st.session_state.get("staffel_merk", ids[0])
    wahl = st.segmented_control(label, ids, format_func=namen.get, key="staffel",
                                label_visibility="collapsed")
    if wahl is None:                                   # Abwählen durch erneuten Klick ignorieren
        wahl = st.session_state.get("staffel_merk", ids[0])
    st.session_state["staffel_merk"] = wahl
    return int(wahl)


def staffel_name(staffel_id: int) -> str:
    df = staffeln()
    return df.loc[df["staffel_id"] == staffel_id, "name"].iat[0]


# ------------------------------------------------------------------ Anzeigetafel und Spielzeilen

def tafel(spiel, gross: bool = False) -> str:
    klasse = "zl-tafel gross" if gross else "zl-tafel"
    if spiel["status"] == "gespielt":
        return f'<span class="{klasse}">{int(spiel["tore_heim"])}:{int(spiel["tore_gast"])}</span>'
    if spiel["status"] in ("bericht_fehlt", "abgebrochen"):
        return f'<span class="{klasse} offen">–:–</span>'
    return f'<span class="{klasse} offen">{uhrzeit(spiel["anstoss_zeit"])}</span>'


STATUS_TEXT = {"aufgestellt": "Aufstellung gemeldet", "bericht_fehlt": "Spielbericht fehlt",
               # erst nach sql/erweiterung_vorschlag.sql
               "abgesagt": "abgesagt", "abgebrochen": "abgebrochen, Wertung offen"}


def spielzeile(spiel) -> str:
    status = STATUS_TEXT.get(spiel["status"])
    meta = (f'{datum_kurz(spiel["anstoss_zeit"])}, {uhrzeit(spiel["anstoss_zeit"])} Uhr, '
            f'{escape(spiel["sportanlage"])}, {escape(spiel["platz"])}')
    return (f'<div class="zl-spiel"><div class="heim">{escape(spiel["heim"])}</div>{tafel(spiel)}'
            f'<div class="gast">{escape(spiel["gast"])}</div></div>'
            f'<div class="zl-meta" style="text-align:center">{meta}'
            f'{f"<span class=zl-status>{status}</span>" if status else ""}</div>')


FORM_TITEL = {"S": "Sieg", "U": "Unentschieden", "N": "Niederlage"}


def form_chips(form: str) -> str:
    chips = "".join(f'<span class="{c}" title="{FORM_TITEL[c]}">{c}</span>' for c in form)
    return f'<span class="zl-form">{chips}</span>'


def tabelle_html(df: pd.DataFrame, kompakt: bool = False, markiert: int | None = None) -> str:
    """Ligatabelle als HTML. kompakt: nur Platz, Mannschaft, Spiele, Punkte."""
    if kompakt:
        kopf = '<tr><th>Pl.</th><th class="links">Mannschaft</th><th>Pkt.</th></tr>'
    else:
        kopf = ('<tr><th>Pl.</th><th class="links">Mannschaft</th><th>Sp.</th><th>S</th><th>U</th><th>N</th>'
                '<th>Tore</th><th>Diff.</th><th>Pkt.</th><th class="links">Form</th></tr>')
    zeilen = []
    for _, r in df.iterrows():
        name = escape(r["mannschaft"]) + (" *" if r["punkteabzug"] else "")
        klasse = ' class="markiert"' if markiert is not None and int(r["teilnahme_id"]) == markiert else ""
        if kompakt:
            zellen = (f'<td>{r["platz"]}</td><td class="mannschaft">{name}</td>'
                      f'<td class="punkte">{r["punkte"]}</td>')
        else:
            zellen = (f'<td>{r["platz"]}</td><td class="mannschaft">{name}</td><td>{r["spiele"]}</td>'
                      f'<td>{r["siege"]}</td><td>{r["unentschieden"]}</td><td>{r["niederlagen"]}</td>'
                      f'<td>{r["tore"]}:{r["gegentore"]}</td><td>{tordifferenz(int(r["tordifferenz"]))}</td>'
                      f'<td class="punkte">{r["punkte"]}</td><td class="links">{form_chips(r["form"])}</td>')
        zeilen.append(f"<tr{klasse}>{zellen}</tr>")
    klasse_tabelle = "zl-tabelle kompakt" if kompakt else "zl-tabelle"
    return (f'<div class="zl-tabelle-rahmen"><table class="{klasse_tabelle}"><thead>{kopf}</thead>'
            f'<tbody>{"".join(zeilen)}</tbody></table></div>')


def karte_chip(art: str) -> str:
    titel = {"Gelb": "Gelbe Karte", "Gelb-Rot": "Gelb-Rote Karte", "Rot": "Rote Karte"}[art]
    return f'<span class="zl-karte {art}" title="{titel}"></span>'


# ------------------------------------------------------------------ Spielbericht-Daten

def spielbericht_daten(spiel_id: int):
    """Spielberichtsbogen und Ereignisse eines Spiels."""
    bogen = db.abfrage("""
        SELECT sk.spieltag_kader_id AS skid, sk.startelf, k.kader_id, k.teilnahme_id, k.rueckennummer AS nr,
               p.vorname || ' ' || p.nachname AS spieler, p.nachname, sp.position
        FROM spieltag_kader sk
        JOIN kader k    ON k.kader_id = sk.kader_id
        JOIN person p   ON p.person_id = k.person_id
        JOIN spieler sp ON sp.person_id = k.person_id
        WHERE sk.spiel_id = %s""", (spiel_id,))
    ereignisse = db.abfrage("""
        SELECT e.spielereignis_id AS id, e.minute,
               CASE WHEN t.spielereignis_id IS NOT NULL THEN 'tor'
                    WHEN ka.spielereignis_id IS NOT NULL THEN 'karte' ELSE 'wechsel' END AS typ,
               ka.art,
               coalesce(t.spieltag_kader_id, ka.spieltag_kader_id, w.spieltag_kader_id_raus) AS skid,
               w.spieltag_kader_id_rein AS skid_rein
        FROM spielereignis e
        LEFT JOIN tor t      ON t.spielereignis_id = e.spielereignis_id
        LEFT JOIN karte ka   ON ka.spielereignis_id = e.spielereignis_id
        LEFT JOIN wechsel w  ON w.spielereignis_id = e.spielereignis_id
        WHERE e.spiel_id = %s
        ORDER BY e.minute, e.spielereignis_id""", (spiel_id,))
    return bogen, ereignisse


def auf_dem_platz(bogen: pd.DataFrame, ereignisse: pd.DataFrame, teilnahme_id: int, minute: int) -> set:
    """Spieltagskader-IDs, die zur Minute auf dem Platz stehen (Ereignisse vor dieser Minute zählen)."""
    team = bogen[bogen["teilnahme_id"] == teilnahme_id]
    drin = set(team.loc[team["startelf"], "skid"].astype(int))
    for _, e in ereignisse.iterrows():
        if e["minute"] >= minute:
            break
        if e["typ"] == "wechsel" and int(e["skid"]) in set(team["skid"]):
            drin.discard(int(e["skid"]))
            drin.add(int(e["skid_rein"]))
        elif e["typ"] == "karte" and e["art"] in ("Rot", "Gelb-Rot"):
            drin.discard(int(e["skid"]))
    return drin


def verlauf_html(spiel, bogen: pd.DataFrame, ereignisse: pd.DataFrame) -> str:
    """Spielverlauf mit Zwischenstand: Heim links, Minute in der Mitte, Gast rechts."""
    if ereignisse.empty:
        return '<p class="zl-meta">Keine Tore, Karten oder Wechsel erfasst.</p>'
    info = bogen.set_index("skid")
    stand = [0, 0]
    zeilen = []
    for _, e in ereignisse.iterrows():
        wer = info.loc[int(e["skid"])]
        heim = int(wer["teilnahme_id"]) == int(spiel["heim_teilnahme_id"])
        name = escape(wer["spieler"])
        if e["typ"] == "tor":
            stand[0 if heim else 1] += 1
            text = f'<span class="stand">{stand[0]}:{stand[1]}</span> {name}'
        elif e["typ"] == "karte":
            text = f'{karte_chip(e["art"])} {name}'
        else:
            rein = escape(info.loc[int(e["skid_rein"]), "spieler"])
            text = f'<span class="zl-rein">▲</span> {rein} <span class="zl-raus">▼</span> {name}'
        links, rechts = (text, "") if heim else ("", text)
        zeilen.append(f'<div class="h">{links}</div><div class="m">{e["minute"]}.</div><div class="g">{rechts}</div>')
    return f'<div class="zl-verlauf">{"".join(zeilen)}</div>'


def aufstellung_html(bogen: pd.DataFrame, ereignisse: pd.DataFrame, teilnahme_id: int) -> str:
    team = bogen[bogen["teilnahme_id"] == teilnahme_id].copy()
    if team.empty:
        return '<p class="zl-meta">Keine Aufstellung gemeldet.</p>'
    team["pos"] = team["position"].map(POSITIONEN)
    zusatz = {int(s): [] for s in team["skid"]}
    for _, e in ereignisse.iterrows():
        skid = int(e["skid"])
        if skid in zusatz:
            if e["typ"] == "tor":
                zusatz[skid].append(f'Tor {e["minute"]}.')
            elif e["typ"] == "karte":
                zusatz[skid].append(f'{karte_chip(e["art"])}{e["minute"]}.')
            else:
                zusatz[skid].append(f'<span class="zl-raus">▼</span> {e["minute"]}.')
        if e["typ"] == "wechsel" and int(e["skid_rein"]) in zusatz:
            zusatz[int(e["skid_rein"])].append(f'<span class="zl-rein">▲</span> {e["minute"]}.')

    def liste(df):
        return '<ul class="zl-aufstellung">' + "".join(
            f'<li><span class="nr">{r["nr"]}</span><span>{escape(r["spieler"])}</span>'
            f'<span class="zusatz">{" ".join(zusatz[int(r["skid"])])}</span></li>'
            for _, r in df.sort_values(["pos", "nr"]).iterrows()) + "</ul>"

    start, bank = team[team["startelf"]], team[~team["startelf"]]
    html = liste(start)
    if not bank.empty:
        html += '<div class="zl-meta" style="margin:.25rem 0">Ersatzbank</div>' + liste(bank)
    return html


def schluessel(name: str) -> str:
    """Widget-Schlüssel mit Versionsnummer. Nach melden(..., name) entsteht ein neues, leeres Widget.

    Nur den alten Schlüssel zu löschen reicht nicht: Tabellen und Editoren schicken ihre alte Auswahl
    sonst beim nächsten Durchlauf erneut, und die Erfolgsmeldung verschwindet sofort wieder.
    """
    return f"{name}__{st.session_state.get('_version_' + name, 0)}"


def stabile_auswahl(widget, label, optionen, format_func, merk, standard=None, **kwargs):
    """selectbox oder radio, deren Beschriftungen sich ändern dürfen (z. B. "gemeldet").

    Mit festem key legt Streamlit das Feld bei geänderten Beschriftungen neu an und verliert die Auswahl.
    Deshalb merkt sich die Seite die Auswahl selbst unter `merk` und übergibt sie als index.
    """
    optionen = list(optionen)
    wert = st.session_state.get(merk)
    if wert not in optionen:
        wert = standard if standard in optionen else optionen[0]
    wert = widget(label, optionen, index=optionen.index(wert), format_func=format_func, **kwargs)
    st.session_state[merk] = wert
    return wert


def melden(text: str, *neu_anlegen: str):
    """Erfolgsmeldung für den nächsten Durchlauf merken, genannte Widgets neu anlegen und neu laden."""
    st.session_state["_meldung"] = text
    for name in neu_anlegen:
        st.session_state["_version_" + name] = st.session_state.get("_version_" + name, 0) + 1
    st.rerun()


def meldung_zeigen():
    text = st.session_state.pop("_meldung", None)
    if text:
        st.success(text, icon=":material/check_circle:")


def technik(titel: str, text: str, sql: str | None = None):
    """Aufklappbarer Bereich für die Präsentation: was die Datenbank an dieser Stelle tut."""
    with st.expander(f"Technik dahinter: {titel}", icon=":material/database:"):
        st.markdown(text)
        if sql:
            st.code(sql.strip(), language="sql")
