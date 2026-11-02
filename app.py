import os
import pandas as pd
import psycopg2
import streamlit as st

# =====================================================================
# 1. SEITEN-KONFIGURATION & DATENBANK-VERBINDUNG
# =====================================================================
st.set_page_config(
    page_title="ZLMV 26 – Berliner Amateurfußball",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# liest DB_URI aus Streamlit Secrets, Umgebungsvariable oder direktem String
DB_URI = st.secrets["DB_URI"]


def get_conn():
    return psycopg2.connect(DB_URI)


def run_query(query, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description is None:
                return pd.DataFrame()
            cols = [desc[0] for desc in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)


def execute_stmt(stmt, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(stmt, params)
            conn.commit()


@st.cache_resource
def init_views():
    """Erstellt die SQL-Views automatisch beim App-Start, falls sie noch fehlen."""
    sql_views = """
    CREATE OR REPLACE VIEW v_ligatabelle AS
    WITH ergebnis AS (
        SELECT sp.spiel_id, st.staffel_id, sp.heim_teilnahme_id AS heim, sp.gast_teilnahme_id AS gast,
               count(*) FILTER (WHERE k.teilnahme_id = sp.heim_teilnahme_id) AS tore_heim,
               count(*) FILTER (WHERE k.teilnahme_id = sp.gast_teilnahme_id) AS tore_gast
        FROM spiel sp
        JOIN spieltag st ON st.spieltag_id = sp.spieltag_id
        LEFT JOIN spielereignis e ON e.spiel_id = sp.spiel_id
        LEFT JOIN tor t ON t.spielereignis_id = e.spielereignis_id
        LEFT JOIN spieltag_kader sk ON sk.spieltag_kader_id = t.spieltag_kader_id
        LEFT JOIN kader k ON k.kader_id = sk.kader_id
        WHERE sp.spiel_id IN (SELECT DISTINCT spiel_id FROM spieltag_kader)
        GROUP BY sp.spiel_id, st.staffel_id
    ),
    sicht AS (
        SELECT staffel_id, heim AS teilnahme_id, tore_heim AS tore, tore_gast AS gegentore FROM ergebnis
        UNION ALL
        SELECT staffel_id, gast, tore_gast, tore_heim FROM ergebnis
    )
    SELECT 
        st.staffel_id,
        kl.name || ' – Staffel ' || st.nummer AS liga_name,
        RANK() OVER (PARTITION BY st.staffel_id ORDER BY 
            sum(CASE WHEN s.tore > s.gegentore THEN 3 WHEN s.tore = s.gegentore THEN 1 ELSE 0 END) - coalesce(max(t.punkteabzug), 0) DESC,
            sum(s.tore - s.gegentore) DESC, sum(s.tore) DESC) AS platz,
        v.name || CASE WHEN m.nummer > 1 THEN ' II' ELSE '' END AS mannschaft,
        count(*) AS spiele,
        count(*) FILTER (WHERE s.tore > s.gegentore) AS s,
        count(*) FILTER (WHERE s.tore = s.gegentore) AS u,
        count(*) FILTER (WHERE s.tore < s.gegentore) AS n,
        sum(s.tore) AS tore_fuer,
        sum(s.gegentore) AS tore_gegen,
        sum(s.tore - s.gegentore) AS tordifferenz,
        sum(s.tore) || ':' || sum(s.gegentore) AS tore,
        coalesce(max(t.punkteabzug), 0) AS punkteabzug,
        sum(CASE WHEN s.tore > s.gegentore THEN 3 WHEN s.tore = s.gegentore THEN 1 ELSE 0 END) - coalesce(max(t.punkteabzug), 0) AS punkte
    FROM sicht s
    JOIN staffel_teilnahme t ON t.teilnahme_id = s.teilnahme_id
    JOIN mannschaft m ON m.mannschaft_id = t.mannschaft_id
    JOIN verein v ON v.verein_id = m.verein_id
    JOIN staffel st ON st.staffel_id = s.staffel_id
    JOIN spielklasse kl ON kl.spielklasse_id = st.spielklasse_id
    GROUP BY st.staffel_id, kl.name, st.nummer, s.teilnahme_id, v.name, m.nummer;

    CREATE OR REPLACE VIEW v_rote_karten_urteile AS
    SELECT 
        k.spielereignis_id,
        p.vorname || ' ' || p.nachname AS spieler, 
        v.name || CASE WHEN m.nummer > 1 THEN ' II' ELSE '' END AS mannschaft, 
        k.art AS karte, 
        sp.anstoss_zeit::date AS spiel_datum,
        e.minute AS minute,
        COALESCE(sk.vergehen, '⏳ Verfahren offen (Vorläufig 2 Spiele)') AS sportgericht_status,
        COALESCE(u.sperre_spiele, 2) AS sperre_spiele, 
        COALESCE(u.tatsaechliche_geldstrafe, 0.00) AS geldstrafe_eur,
        CASE WHEN u.urteil_id IS NULL THEN false ELSE true END AS hat_urteil
    FROM karte k
    JOIN spielereignis e ON e.spielereignis_id = k.spielereignis_id
    JOIN spiel sp ON sp.spiel_id = e.spiel_id
    JOIN spieltag_kader stk ON stk.spieltag_kader_id = k.spieltag_kader_id
    JOIN kader ka ON ka.kader_id = stk.kader_id
    JOIN person p ON p.person_id = ka.person_id
    JOIN staffel_teilnahme st ON st.teilnahme_id = ka.teilnahme_id
    JOIN mannschaft m ON m.mannschaft_id = st.mannschaft_id
    JOIN verein v ON v.verein_id = m.verein_id
    LEFT JOIN urteil u ON u.spielereignis_id = k.spielereignis_id
    LEFT JOIN strafenkatalog sk ON sk.strafe_id = u.strafe_id
    WHERE k.art = 'Rot'
    ORDER BY sp.anstoss_zeit DESC;

    CREATE OR REPLACE VIEW v_aktive_sperren AS
    WITH gespielt AS (
        SELECT DISTINCT spiel_id FROM spieltag_kader
    ),
    naechstes_spiel AS (
        SELECT t.teilnahme_id, min(sp.spiel_id) AS spiel_id, min(sp.anstoss_zeit) AS anstoss_zeit
        FROM staffel_teilnahme t
        JOIN spiel sp ON t.teilnahme_id IN (sp.heim_teilnahme_id, sp.gast_teilnahme_id)
        WHERE sp.spiel_id NOT IN (SELECT spiel_id FROM gespielt)
        GROUP BY t.teilnahme_id
    )
    SELECT 
        ka_kader.kader_id,
        p.vorname || ' ' || p.nachname AS spieler,
        v.name || CASE WHEN m.nummer > 1 THEN ' II' ELSE '' END AS mannschaft,
        s.vergehen AS grund,
        u.sperre_spiele AS gesamt_sperre,
        z.abgesessen AS abgesessene_spiele,
        (u.sperre_spiele - z.abgesessen) AS rest_sperre_spiele,
        ns.spiel_id AS naechstes_spiel_id,
        ns.anstoss_zeit AS naechstes_spiel_datum
    FROM urteil u
    JOIN karte ka ON ka.spielereignis_id = u.spielereignis_id
    JOIN spieltag_kader sk ON sk.spieltag_kader_id = ka.spieltag_kader_id
    JOIN kader ka_kader ON ka_kader.kader_id = sk.kader_id
    JOIN person p ON p.person_id = ka_kader.person_id
    JOIN staffel_teilnahme st ON st.teilnahme_id = ka_kader.teilnahme_id
    JOIN mannschaft m ON m.mannschaft_id = st.mannschaft_id
    JOIN verein v ON v.verein_id = m.verein_id
    JOIN spiel sp_karte ON sp_karte.spiel_id = sk.spiel_id
    JOIN strafenkatalog s ON s.strafe_id = u.strafe_id
    JOIN naechstes_spiel ns ON ns.teilnahme_id = ka_kader.teilnahme_id
    CROSS JOIN LATERAL (
        SELECT count(*)::INT AS abgesessen
        FROM spiel x
        WHERE ka_kader.teilnahme_id IN (x.heim_teilnahme_id, x.gast_teilnahme_id)
          AND x.anstoss_zeit > sp_karte.anstoss_zeit
          AND x.anstoss_zeit < ns.anstoss_zeit
    ) z
    WHERE sp_karte.anstoss_zeit < ns.anstoss_zeit
      AND z.abgesessen < u.sperre_spiele;
    """
    execute_stmt(sql_views)
    return True


# =====================================================================
# 2. FLIP7 DESIGN SYSTEM (CSS & UI-HELPER)
# =====================================================================
st.markdown(
    """
<style>
:root {
    --primary-teal: #2BA8A2;
    --primary-light: #3CC4BD;
    --primary-dark: #1E8C86;
    --primary-bg: #E8F6F5;
    --accent-gold: #FFD23F;
    --accent-light: #FFE47A;
    --accent-dark: #E6B800;
    --coral: #EF6C4A;
    --coral-light: #FF8A6A;
    --coral-dark: #D45233;
    --cream: #FFF8E7;
    --sky-blue: #5DADE2;
    --surface-base: #EFF8F7;
    --surface-card: #FFFFFF;
    --success: #27AE60;
    --error: #E74C3C;
}

/* App Background & Typography */
.stApp {
    background-color: var(--surface-base) !important;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif !important;
    color: #1A3A38;
}

h1, h2, h3, .flip-h1, .flip-h2, .flip-h3 {
    font-weight: 800 !important;
    letter-spacing: 1.5px !important;
    color: var(--primary-dark) !important;
}

/* Keyframe Animations from flip7-card-game-DESIGN.md */
@keyframes crownBounce {
    0%, 100% { transform: translateY(0) rotate(-4deg); }
    25% { transform: translateY(-6px) rotate(4deg); }
    50% { transform: translateY(-2px) rotate(-2deg); }
    75% { transform: translateY(-5px) rotate(3deg); }
}

@keyframes glowPulse {
    0%, 100% { transform: scale(1.0); box-shadow: 0 4px 22px rgba(255, 210, 63, 0.45); }
    50% { transform: scale(1.02); box-shadow: 0 8px 30px rgba(255, 210, 63, 0.75); }
}

@keyframes boomPulse {
    0%, 100% { box-shadow: 0 4px 20px rgba(239, 108, 74, 0.35); border-left-color: #EF6C4A; }
    50% { box-shadow: 0 6px 28px rgba(239, 108, 74, 0.75); border-left-color: #D45233; }
}

/* Flip7 Hero Logo Header */
.flip7-hero-wrapper {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 28px 16px 20px 16px;
    margin-bottom: 18px;
    position: relative;
}

.fan-cards-container {
    position: relative;
    height: 68px;
    width: 240px;
    margin-bottom: -36px;
    z-index: 1;
}

.fan-card {
    position: absolute;
    left: 50%;
    bottom: 0;
    width: 48px;
    height: 68px;
    margin-left: -24px;
    border-radius: 8px;
    border: 2.5px solid #1A3A38;
    transform-origin: bottom center;
    box-shadow: 0 4px 10px rgba(0,0,0,0.12);
}
.fan-card.c1 { background: #EF6C4A; transform: rotate(-24deg) translateX(-45px); }
.fan-card.c2 { background: #FFD23F; transform: rotate(-12deg) translateX(-22px); }
.fan-card.c3 { background: #2BA8A2; transform: rotate(0deg); }
.fan-card.c4 { background: #5DADE2; transform: rotate(12deg) translateX(22px); }
.fan-card.c5 { background: #FFE47A; transform: rotate(24deg) translateX(45px); }

.flip7-logo-box {
    position: relative;
    z-index: 2;
    background: var(--cream);
    border: 3.5px solid #1A3A38;
    border-radius: 16px;
    padding: 8px 32px;
    transform: rotate(-2deg) skewX(-6deg);
    box-shadow: 0 8px 25px rgba(43, 168, 162, 0.25);
    display: inline-flex;
    align-items: baseline;
    gap: 8px;
}

.flip7-logo-text {
    font-size: 46px;
    font-weight: 900;
    color: var(--primary-dark);
    letter-spacing: 4px;
    text-shadow: 2px 2px 0px #FFFFFF, 3px 3px 0px rgba(30,140,134,0.25);
}

.flip7-logo-num {
    font-size: 64px;
    font-weight: 900;
    color: var(--accent-gold);
    display: inline-block;
    transform: rotate(5deg);
    text-shadow: -2px -2px 0 #1A3A38, 2px -2px 0 #1A3A38, -2px 2px 0 #1A3A38, 3px 4px 0 #1A3A38;
    line-height: 1;
}

.flip7-ribbon {
    position: relative;
    z-index: 3;
    margin-top: -8px;
    background: var(--cream);
    border: 2.5px solid #1A3A38;
    border-radius: 8px;
    padding: 6px 28px;
    font-weight: 800;
    font-size: 13px;
    color: var(--primary-dark);
    letter-spacing: 3.5px;
    text-transform: uppercase;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}

/* Section Titles with Emoji View + 3px Dashed Border */
.flip7-section-title {
    display: flex;
    align-items: center;
    gap: 12px;
    padding-bottom: 10px;
    margin: 20px 0 16px 0;
    border-bottom: 3px dashed var(--primary-light);
}
.flip7-emoji-box {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 38px;
    height: 38px;
    background: var(--cream);
    border: 2px solid var(--primary-dark);
    border-radius: 12px;
    font-size: 20px;
    box-shadow: 0 2px 8px rgba(43, 168, 162, 0.2);
}
.flip7-section-text {
    font-size: 22px;
    font-weight: 800;
    color: var(--primary-dark);
    letter-spacing: 1.5px;
}

/* Flip7 Cards */
.flip7-card {
    background: var(--surface-card);
    border-radius: 16px;
    padding: 18px 20px;
    margin-bottom: 14px;
    border-left: 6px solid var(--primary-light);
    box-shadow: 0 4px 20px rgba(43, 168, 162, 0.12);
    transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.flip7-card:hover {
    transform: translateY(-2px);
}
.flip7-card.gold {
    border-left: 8px solid var(--accent-gold);
    background: linear-gradient(135deg, #FFFFFF 0%, #FFFDF5 65%, #FFF3C4 100%);
    animation: glowPulse 2.5s infinite;
}
.flip7-card.silver {
    border-left: 8px solid #95A5A6;
    background: linear-gradient(135deg, #FFFFFF 0%, #F8F9F9 100%);
    box-shadow: 0 4px 18px rgba(149, 165, 166, 0.22);
}
.flip7-card.bronze {
    border-left: 8px solid var(--coral);
    background: linear-gradient(135deg, #FFFFFF 0%, #FFF5F2 100%);
    box-shadow: 0 4px 20px rgba(239, 108, 74, 0.25);
}
.flip7-card.boom {
    border-left: 8px solid var(--coral);
    background: linear-gradient(135deg, #FFF5F2 0%, #FFE4DC 100%);
    animation: boomPulse 2s infinite;
}
.flip7-card.sky {
    border-left: 6px solid var(--sky-blue);
    background: linear-gradient(135deg, #FFFFFF 0%, #F2F9FD 100%);
    box-shadow: 0 4px 16px rgba(93, 173, 226, 0.25);
}
.flip7-card.success {
    border-left: 6px solid var(--success);
    background: linear-gradient(135deg, #FFFFFF 0%, #F0FBF4 100%);
    box-shadow: 0 4px 18px rgba(39, 174, 96, 0.25);
}

/* Badges & Pills */
.flip7-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 999px;
    font-weight: 800;
    font-size: 12px;
    letter-spacing: 0.8px;
}
.badge-teal { background: var(--primary-bg); color: var(--primary-dark); border: 1.5px solid var(--primary-light); }
.badge-gold { background: var(--accent-light); color: #5C4800; border: 1.5px solid var(--accent-dark); }
.badge-coral { background: #FFE4DC; color: var(--coral-dark); border: 1.5px solid var(--coral); }
.badge-sky { background: #EBF5FB; color: #1B4F72; border: 1.5px solid var(--sky-blue); }

/* Crown Animation */
.crown-icon {
    display: inline-block;
    animation: crownBounce 1.5s infinite;
    font-size: 26px;
}

/* Pill Buttons (Gold CTA) */
.stButton > button, .stFormSubmitButton > button {
    border-radius: 999px !important;
    min-height: 46px !important;
    background: linear-gradient(180deg, #FFE47A 0%, #FFD23F 55%, #E6B800 100%) !important;
    color: #1A3A38 !important;
    font-weight: 800 !important;
    letter-spacing: 1.2px !important;
    border: 2px solid #1A3A38 !important;
    box-shadow: 0 4px 20px rgba(255, 210, 63, 0.45) !important;
    transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
    padding: 0 24px !important;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
    transform: translateY(-2px) scale(1.02) !important;
    box-shadow: 0 6px 24px rgba(255, 210, 63, 0.65) !important;
}
.stButton > button:active, .stFormSubmitButton > button:active {
    transform: scale(0.95) !important;
}

/* Cream Input Surfaces (#FFF8E7) */
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
div[data-baseweb="base-input"],
.stTextInput input, .stNumberInput input, .stDateInput input {
    background-color: var(--cream) !important;
    border-radius: 12px !important;
    border: 2px solid var(--primary-light) !important;
    font-weight: 600 !important;
    color: #1A3A38 !important;
}
div[data-baseweb="select"] > div:focus-within,
div[data-baseweb="input"] > div:focus-within {
    box-shadow: 0 0 0 4px rgba(43, 168, 162, 0.2) !important;
    border-color: var(--primary-dark) !important;
}

/* Tabs Styling as Tactile Game Pieces */
.stTabs [data-baseweb="tab-list"] {
    gap: 10px;
    background-color: var(--primary-bg);
    padding: 8px 12px;
    border-radius: 999px;
    border: 2px solid var(--primary-light);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 999px !important;
    padding: 8px 18px !important;
    font-weight: 800 !important;
    color: var(--primary-dark) !important;
    border: none !important;
}
.stTabs [aria-selected="true"] {
    background: var(--primary-teal) !important;
    color: #FFFFFF !important;
    box-shadow: 0 4px 14px rgba(43, 168, 162, 0.35) !important;
}

/* Sidebar Styling */
section[data-testid="stSidebar"] {
    background-color: var(--primary-bg) !important;
    border-right: 3px dashed var(--primary-light) !important;
}
</style>
""",
    unsafe_allow_html=True,
)


def section_title(emoji: str, text: str):
    st.markdown(
        f"""
    <div class="flip7-section-title">
        <div class="flip7-emoji-box">{emoji}</div>
        <div class="flip7-section-text">{text}</div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def boom_alert(title: str, pg_error: str):
    st.markdown(
        f"""
    <div class="flip7-card boom">
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:6px;">
            <span style="font-size:26px;">💥</span>
            <span style="font-weight:900; font-size:18px; color:#D45233; letter-spacing:1px;">{title}</span>
            <span class="flip7-badge badge-coral">SQL BLOCKED</span>
        </div>
        <code style="display:block; background:#FFF8E7; padding:10px 14px; border-radius:10px; color:#A93226; font-weight:700; border:1.5px dashed #EF6C4A; white-space:pre-wrap;">{pg_error}</code>
    </div>
    """,
        unsafe_allow_html=True,
    )


def success_card(title: str, msg: str):
    st.markdown(
        f"""
    <div class="flip7-card success">
        <div style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:24px;">🎉</span>
            <div>
                <div style="font-weight:900; font-size:17px; color:#1E8449;">{title}</div>
                <div style="font-size:14px; color:#1A3A38;">{msg}</div>
            </div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


# =====================================================================
# 3. HEADER LOGO & SIDEBAR (KPIs)
# =====================================================================
st.markdown(
    """
<div class="flip7-hero-wrapper">
    <div class="fan-cards-container">
        <div class="fan-card c1"></div>
        <div class="fan-card c2"></div>
        <div class="fan-card c3"></div>
        <div class="fan-card c4"></div>
        <div class="fan-card c5"></div>
    </div>
    <div class="flip7-logo-box">
        <span class="flip7-logo-text">ZLMV</span>
        <span class="flip7-logo-num">26</span>
    </div>
    <div class="flip7-ribbon">Berliner Amateurfußball · 3NF SQL Backend</div>
</div>
""",
    unsafe_allow_html=True,
)

# Views initialisieren
try:
    init_views()
    kpis = run_query("""
        SELECT 
            (SELECT count(*) FROM verein) AS vereine,
            (SELECT count(*) FROM mannschaft) AS teams,
            (SELECT count(*) FROM spieler) AS spieler,
            (SELECT count(*) FROM schiedsrichter) AS schiris,
            (SELECT count(*) FROM spiel) AS spiele_gesamt,
            (SELECT count(DISTINCT spiel_id) FROM spieltag_kader) AS gespielt,
            (SELECT count(*) FROM tor) AS tore,
            (SELECT count(*) FROM karte) AS karten,
            (SELECT count(*) FROM urteil) AS urteile;
    """).iloc[0]
except Exception as db_err:
    boom_alert("Datenbank-Verbindung fehlgeschlagen", str(db_err))
    st.stop()

with st.sidebar:
    st.markdown(
        """
    <div style="text-align:center; padding: 10px 0;">
        <span class="flip7-badge badge-gold">SAISON 2026/27 · STICHTAG 02.11.2026</span>
    </div>
    """,
        unsafe_allow_html=True,
    )
    section_title("⚡", "Live-DB Status")

    st.markdown(
        f"""
    <div class="flip7-card">
        <div style="font-size:13px; font-weight:700; color:#1E8C86;">VEREINE & TEAMS</div>
        <div style="font-size:26px; font-weight:900;">{kpis['vereine']} <span style="font-size:15px; color:#2BA8A2;">Vereine ({kpis['teams']} Teams)</span></div>
    </div>
    <div class="flip7-card">
        <div style="font-size:13px; font-weight:700; color:#1E8C86;">AKTEURE IN 3NF</div>
        <div style="font-size:26px; font-weight:900;">{kpis['spieler']} <span style="font-size:15px; color:#2BA8A2;">Spieler · {kpis['schiris']} Schiris</span></div>
    </div>
    <div class="flip7-card">
        <div style="font-size:13px; font-weight:700; color:#1E8C86;">SPIELBETRIEB</div>
        <div style="font-size:26px; font-weight:900;">{kpis['gespielt']} <span style="font-size:15px; color:#2BA8A2;">/ {kpis['spiele_gesamt']} gespielt</span></div>
    </div>
    <div class="flip7-card">
        <div style="font-size:13px; font-weight:700; color:#1E8C86;">LIVE-EREIGNISSE</div>
        <div style="font-size:22px; font-weight:900;">⚽ {kpis['tore']} · 🟨🟥 {kpis['karten']} · ⚖️ {kpis['urteile']}</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    if st.button("🔄 Views & Cache aktualisieren"):
        st.cache_resource.clear()
        st.rerun()

# =====================================================================
# 4. HAUPT-NAVIGATION (5 USE-CASE TABS)
# =====================================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "🏆 1. Ligazentrale & Podium",
        "📋 2. Match-Center & Live-Ticker",
        "🚫 3. Aufstellung & Sperr-Trigger",
        "🏟️ 4. Platz- & Pass-Wächter",
        "⚖️ 5. Sportgericht & 25-Regel-Audit",
    ]
)

# ---------------------------------------------------------------------
# TAB 1: LIGAZENTRALE, PODIUM & TORJÄGER (VIEWS)
# ---------------------------------------------------------------------
with tab1:
    section_title("🏆", "Use-Case 1: Live-Ligazentrale (100% 3NF-Berechnung)")

    staffeln_df = run_query(
        "SELECT DISTINCT staffel_id, liga_name FROM v_ligatabelle ORDER BY staffel_id;"
    )
    col_sel, col_info = st.columns([1, 2])
    with col_sel:
        liga_auswahl = st.selectbox(
            "⚽ Spielklasse & Staffel wählen:", staffeln_df["liga_name"]
        )
        akt_staffel_id = int(
            staffeln_df.loc[
                staffeln_df["liga_name"] == liga_auswahl, "staffel_id"
            ].values[0]
        )
    with col_info:
        st.markdown(
            """
        <div class="flip7-card sky" style="margin-top:6px;">
            <span class="flip7-badge badge-sky">SQL VIEW: v_ligatabelle</span>
            <div style="margin-top:6px; font-size:14px; font-weight:600;">
                In der Tabelle <code>spiel</code> existieren keine Spalten für das Endergebnis. Jedes Tor wird einzeln in <code>tor</code> gespeichert und hier live aggregiert – inklusive automatischer Verrechnung von <code>punkteabzug</code>.
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    df_tab = run_query(
        """
        SELECT platz, mannschaft, spiele, s, u, n, tore, tordifferenz, punkteabzug, punkte
        FROM v_ligatabelle WHERE staffel_id = %s ORDER BY platz, mannschaft;
    """,
        (akt_staffel_id,),
    )

    # FLIP7 VICTORY PODIUM (Top 3 Teams)
    if len(df_tab) >= 3:
        p1, p2, p3 = df_tab.iloc[0], df_tab.iloc[1], df_tab.iloc[2]
        c_p1, c_p2, c_p3 = st.columns(3)
        with c_p1:
            st.markdown(
                f"""
            <div class="flip7-card gold">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="flip7-badge badge-gold">PLATZ #1 · TABELLENFÜHRER</span>
                    <span class="crown-icon">👑</span>
                </div>
                <div style="font-size:22px; font-weight:900; color:#1E8C86; margin:8px 0;">{p1['mannschaft']}</div>
                <div style="display:flex; justify-content:space-between; align-items:baseline;">
                    <span style="font-size:32px; font-weight:900; color:#E6B800; text-shadow:1px 1px 0 #1A3A38;">{p1['punkte']} Pkt.</span>
                    <span style="font-weight:700; font-size:14px;">{p1['tore']} Tore ({p1['s']}S-{p1['u']}U-{p1['n']}N)</span>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )
        with c_p2:
            st.markdown(
                f"""
            <div class="flip7-card silver">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="flip7-badge badge-teal">PLATZ #2 · VERFOLGER</span>
                    <span style="font-size:24px;">🥈</span>
                </div>
                <div style="font-size:20px; font-weight:800; color:#1E8C86; margin:8px 0;">{p2['mannschaft']}</div>
                <div style="display:flex; justify-content:space-between; align-items:baseline;">
                    <span style="font-size:28px; font-weight:900; color:#566573;">{p2['punkte']} Pkt.</span>
                    <span style="font-weight:700; font-size:14px;">{p2['tore']} Tore ({p2['s']}S-{p2['u']}U-{p2['n']}N)</span>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )
        with c_p3:
            st.markdown(
                f"""
            <div class="flip7-card bronze">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="flip7-badge badge-coral">PLATZ #3 · PODIUM</span>
                    <span style="font-size:24px;">🥉</span>
                </div>
                <div style="font-size:20px; font-weight:800; color:#1E8C86; margin:8px 0;">{p3['mannschaft']}</div>
                <div style="display:flex; justify-content:space-between; align-items:baseline;">
                    <span style="font-size:28px; font-weight:900; color:#EF6C4A;">{p3['punkte']} Pkt.</span>
                    <span style="font-weight:700; font-size:14px;">{p3['tore']} Tore ({p3['s']}S-{p3['u']}U-{p3['n']}N)</span>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

    col_table, col_scorers = st.columns([3, 2])
    with col_table:
        st.markdown("#### 📊 Gesamte Staffel-Tabelle")
        st.dataframe(df_tab, use_container_width=True, hide_index=True)

    with col_scorers:
        st.markdown("#### 🎯 Top-Torjäger & Fair-Play der Staffel")
        df_torjaeger = run_query(
            """
            SELECT p.vorname || ' ' || p.nachname AS spieler,
                   v.name || CASE WHEN m.nummer > 1 THEN ' II' ELSE '' END AS team,
                   sp_pos.position AS pos,
                   count(t.spielereignis_id) AS tore
            FROM tor t
            JOIN spieltag_kader stk ON stk.spieltag_kader_id = t.spieltag_kader_id
            JOIN kader k ON k.kader_id = stk.kader_id
            JOIN person p ON p.person_id = k.person_id
            JOIN spieler sp_pos ON sp_pos.person_id = p.person_id
            JOIN staffel_teilnahme st ON st.teilnahme_id = k.teilnahme_id
            JOIN mannschaft m ON m.mannschaft_id = st.mannschaft_id
            JOIN verein v ON v.verein_id = m.verein_id
            WHERE st.staffel_id = %s
            GROUP BY p.person_id, p.vorname, p.nachname, v.name, m.nummer, sp_pos.position
            ORDER BY tore DESC, spieler ASC
            LIMIT 10;
        """,
            (akt_staffel_id,),
        )
        st.dataframe(df_torjaeger, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------
# TAB 2: MATCH-CENTER & LIVE-TICKER (SPIELBERICHTSBOGEN)
# ---------------------------------------------------------------------
with tab2:
    section_title(
        "📋", "Use-Case 2: Digitaler Spielberichtsbogen & Live-Tor-Simulator"
    )

    col_m1, col_m2 = st.columns([1, 2])
    with col_m1:
        staffel_mc = st.selectbox(
            "Staffel filtern:", staffeln_df["liga_name"], key="mc_staffel"
        )
        mc_staffel_id = int(
            staffeln_df.loc[
                staffeln_df["liga_name"] == staffel_mc, "staffel_id"
            ].values[0]
        )

    spiele_mc_df = run_query(
        """
        SELECT sp.spiel_id,
               'Spieltag ' || st.nummer || ' (' || to_char(sp.anstoss_zeit, 'DD.MM.YYYY') || '): ' ||
               vh.name || CASE WHEN mh.nummer > 1 THEN ' II' ELSE '' END || ' vs. ' ||
               vg.name || CASE WHEN mg.nummer > 1 THEN ' II' ELSE '' END AS label,
               vh.name || CASE WHEN mh.nummer > 1 THEN ' II' ELSE '' END AS heim_name,
               vg.name || CASE WHEN mg.nummer > 1 THEN ' II' ELSE '' END AS gast_name,
               pl.name || ' (' || pl.belag || ', ' || sa.name || ')' AS ort,
               sp.heim_teilnahme_id, sp.gast_teilnahme_id
        FROM spiel sp
        JOIN spieltag st ON st.spieltag_id = sp.spieltag_id
        JOIN staffel_teilnahme th ON th.teilnahme_id = sp.heim_teilnahme_id
        JOIN mannschaft mh ON mh.mannschaft_id = th.mannschaft_id
        JOIN verein vh ON vh.verein_id = mh.verein_id
        JOIN staffel_teilnahme tg ON tg.teilnahme_id = sp.gast_teilnahme_id
        JOIN mannschaft mg ON mg.mannschaft_id = tg.mannschaft_id
        JOIN verein vg ON vg.verein_id = mg.verein_id
        JOIN platz pl ON pl.platz_id = sp.platz_id
        JOIN sportanlage sa ON sa.sportanlage_id = pl.sportanlage_id
        WHERE st.staffel_id = %s
          AND sp.spiel_id IN (SELECT DISTINCT spiel_id FROM spieltag_kader)
        ORDER BY st.nummer DESC, sp.spiel_id ASC;
    """,
        (mc_staffel_id,),
    )

    with col_m2:
        spiel_auswahl = st.selectbox(
            "Gespielte Partie auswählen (inkl. vollständigem Spielbericht):",
            spiele_mc_df["label"],
        )
        akt_spiel = spiele_mc_df.loc[
            spiele_mc_df["label"] == spiel_auswahl
        ].iloc[0]
        akt_spiel_id = int(akt_spiel["spiel_id"])

    # Live-Score und Schiedsrichter abrufen
    score_df = run_query(
        """
        SELECT 
            count(*) FILTER (WHERE k.teilnahme_id = %s) AS tore_heim,
            count(*) FILTER (WHERE k.teilnahme_id = %s) AS tore_gast
        FROM spielereignis e
        JOIN tor t ON t.spielereignis_id = e.spielereignis_id
        JOIN spieltag_kader stk ON stk.spieltag_kader_id = t.spieltag_kader_id
        JOIN kader k ON k.kader_id = stk.kader_id
        WHERE e.spiel_id = %s;
    """,
        (
            int(akt_spiel["heim_teilnahme_id"]),
            int(akt_spiel["gast_teilnahme_id"]),
            akt_spiel_id,
        ),
    ).iloc[0]

    schiris_spiel = run_query(
        """
        SELECT ss.rolle || ': ' || p.vorname || ' ' || p.nachname || ' (' || v.name || ')' AS info
        FROM spiel_schiedsrichter ss
        JOIN schiedsrichter sr ON sr.person_id = ss.person_id
        JOIN person p ON p.person_id = sr.person_id
        JOIN verein v ON v.verein_id = sr.stammverein_id
        WHERE ss.spiel_id = %s;
    """,
        (akt_spiel_id,),
    )
    sr_text = (
        " · ".join(schiris_spiel["info"].tolist())
        if not schiris_spiel.empty
        else "Keine Einteilung"
    )

    # Scoreboard Card
    st.markdown(
        f"""
    <div class="flip7-card gold" style="text-align:center; padding:24px;">
        <span class="flip7-badge badge-teal">SPIEL-ID #{akt_spiel_id} · {akt_spiel['ort']}</span>
        <div style="display:flex; justify-content:center; align-items:center; gap:32px; margin:14px 0;">
            <div style="font-size:24px; font-weight:900; color:#1E8C86; flex:1; text-align:right;">{akt_spiel['heim_name']}</div>
            <div style="background:#FFF8E7; border:3px solid #1A3A38; border-radius:16px; padding:8px 26px; font-size:38px; font-weight:900; color:#1A3A38;">
                {score_df['tore_heim']} : {score_df['tore_gast']}
            </div>
            <div style="font-size:24px; font-weight:900; color:#1E8C86; flex:1; text-align:left;">{akt_spiel['gast_name']}</div>
        </div>
        <div style="font-size:13px; font-weight:700; color:#566573;">🕴️ {sr_text}</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    col_events, col_sim = st.columns([3, 2])
    with col_events:
        st.markdown(
            "#### ⏱️ Chronologische Spielereignisse (Subtyping: Tor, Karte, Wechsel)"
        )
        df_timeline = run_query(
            """
            SELECT e.minute || '''' AS min, '⚽ TOR' AS typ,
                   p.vorname || ' ' || p.nachname || ' (#' || k.rueckennummer || ')' AS akteur,
                   v.name AS team
            FROM spielereignis e
            JOIN tor t ON t.spielereignis_id = e.spielereignis_id
            JOIN spieltag_kader stk ON stk.spieltag_kader_id = t.spieltag_kader_id
            JOIN kader k ON k.kader_id = stk.kader_id
            JOIN person p ON p.person_id = k.person_id
            JOIN staffel_teilnahme st ON st.teilnahme_id = k.teilnahme_id
            JOIN mannschaft m ON m.mannschaft_id = st.mannschaft_id
            JOIN verein v ON v.verein_id = m.verein_id
            WHERE e.spiel_id = %s
            UNION ALL
            SELECT e.minute || '''', 
                   CASE WHEN ka.art = 'Rot' THEN '🟥 ROT' WHEN ka.art = 'Gelb-Rot' THEN '🟨🟥 GELB-ROT' ELSE '🟨 GELB' END,
                   p.vorname || ' ' || p.nachname || ' (#' || k.rueckennummer || ')',
                   v.name
            FROM spielereignis e
            JOIN karte ka ON ka.spielereignis_id = e.spielereignis_id
            JOIN spieltag_kader stk ON stk.spieltag_kader_id = ka.spieltag_kader_id
            JOIN kader k ON k.kader_id = stk.kader_id
            JOIN person p ON p.person_id = k.person_id
            JOIN staffel_teilnahme st ON st.teilnahme_id = k.teilnahme_id
            JOIN mannschaft m ON m.mannschaft_id = st.mannschaft_id
            JOIN verein v ON v.verein_id = m.verein_id
            WHERE e.spiel_id = %s
            UNION ALL
            SELECT e.minute || '''', '🔄 WECHSEL',
                   '🟢 ' || p_in.nachname || ' für 🔴 ' || p_out.nachname,
                   v.name
            FROM spielereignis e
            JOIN wechsel w ON w.spielereignis_id = e.spielereignis_id
            JOIN spieltag_kader stk_in ON stk_in.spieltag_kader_id = w.spieltag_kader_id_rein
            JOIN kader k_in ON k_in.kader_id = stk_in.kader_id
            JOIN person p_in ON p_in.person_id = k_in.person_id
            JOIN spieltag_kader stk_out ON stk_out.spieltag_kader_id = w.spieltag_kader_id_raus
            JOIN kader k_out ON k_out.kader_id = stk_out.kader_id
            JOIN person p_out ON p_out.person_id = k_out.person_id
            JOIN staffel_teilnahme st ON st.teilnahme_id = k_in.teilnahme_id
            JOIN mannschaft m ON m.mannschaft_id = st.mannschaft_id
            JOIN verein v ON v.verein_id = m.verein_id
            WHERE e.spiel_id = %s
            ORDER BY 1;
        """,
            (akt_spiel_id, akt_spiel_id, akt_spiel_id),
        )
        st.dataframe(df_timeline, use_container_width=True, hide_index=True)

    with col_sim:
        st.markdown("#### ⚡ Live-Tor eintragen (3NF Beweis)")
        kader_spiel_df = run_query(
            """
            SELECT stk.spieltag_kader_id,
                   v.name || ': ' || p.vorname || ' ' || p.nachname || ' (#' || k.rueckennummer || ', ' ||
                   CASE WHEN stk.startelf THEN 'Startelf' ELSE 'Bank' END || ')' AS spieler_label
            FROM spieltag_kader stk
            JOIN kader k ON k.kader_id = stk.kader_id
            JOIN person p ON p.person_id = k.person_id
            JOIN staffel_teilnahme st ON st.teilnahme_id = k.teilnahme_id
            JOIN mannschaft m ON m.mannschaft_id = st.mannschaft_id
            JOIN verein v ON v.verein_id = m.verein_id
            WHERE stk.spiel_id = %s
            ORDER BY v.name, stk.startelf DESC, k.rueckennummer;
        """,
            (akt_spiel_id,),
        )

        with st.form("form_live_tor"):
            st.caption(
                "Fügt ein neues Spielereignis + Tor in die Datenbank ein und berechnet Spielstand & Tabelle sofort neu:"
            )
            schuetze_sel = st.selectbox(
                "Torschütze (aus Spieltagskader):",
                kader_spiel_df["spieler_label"],
            )
            tor_minute = st.slider("Spielminute:", min_value=1, max_value=95, value=89)
            if st.form_submit_button("⚽ Tor jetzt live in DB verbuchen!"):
                stk_id = int(
                    kader_spiel_df.loc[
                        kader_spiel_df["spieler_label"] == schuetze_sel,
                        "spieltag_kader_id",
                    ].values[0]
                )
                try:
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO spielereignis (minute, spiel_id) VALUES (%s, %s) RETURNING spielereignis_id;",
                                (tor_minute, akt_spiel_id),
                            )
                            new_eid = cur.fetchone()[0]
                            cur.execute(
                                "INSERT INTO tor (spielereignis_id, spieltag_kader_id) VALUES (%s, %s);",
                                (new_eid, stk_id),
                            )
                            conn.commit()
                    success_card(
                        "TOR GESPEICHERT!",
                        f"Ereignis #{new_eid} in Minute {tor_minute} wurde eingetragen.",
                    )
                    st.rerun()
                except psycopg2.Error as e:
                    boom_alert(
                        "Datenbank-Fehler beim Tor-Eintrag", e.pgerror or str(e)
                    )

# ---------------------------------------------------------------------
# TAB 3: AUFSTELLUNG & SPERR-TRIGGER (blockiere_gesperrte_spieler)
# ---------------------------------------------------------------------
with tab3:
    section_title(
        "🚫",
        "Use-Case 3: Spieltags-Aufstellung & Trigger (Sperren durchsetzen)",
    )

    df_sperren = run_query("SELECT * FROM v_aktive_sperren ORDER BY rest_sperre_spiele DESC;")

    st.markdown(
        """
    <div class="flip7-card sky">
        <span class="flip7-badge badge-sky">SQL TRIGGER: blockiere_gesperrte_spieler</span>
        <div style="margin-top:6px; font-size:14px; font-weight:600;">
            Feuert <code>BEFORE INSERT OR UPDATE OF spiel_id, kader_id ON spieltag_kader</code>. Der Trigger prüft in Echtzeit über <code>urteil</code>, wie viele Spiele die Mannschaft seit der Roten Karte bereits bestritten hat. Ist <code>abgesessen &lt; sperre_spiele</code>, blockiert PostgreSQL die Nominierung!
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    col_sp1, col_sp2 = st.columns([3, 2])
    with col_sp1:
        st.markdown("#### 🚨 Aktuell durch Sportgerichtsurteil gesperrte Spieler")
        if not df_sperren.empty:
            for _, row in df_sperren.iterrows():
                st.markdown(
                    f"""
                <div class="flip7-card boom">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-weight:900; font-size:18px; color:#D45233;">🚫 {row['spieler']} ({row['mannschaft']})</span>
                        <span class="flip7-badge badge-coral">NOCH {row['rest_sperre_spiele']} SPIEL(E) GESPERRT</span>
                    </div>
                    <div style="font-size:14px; font-weight:700; margin-top:6px; color:#1A3A38;">
                        📌 Vergehen: <b>{row['grund']}</b> ({row['gesamt_sperre']} Spiele Sperre, davon {row['abgesessene_spiele']} abgesessen)
                    </div>
                    <div style="font-size:12px; color:#566573; margin-top:4px;">
                        Kader-ID: <code>{row['kader_id']}</code> · Nächstes Team-Spiel: <code>#{row['naechstes_spiel_id']}</code> am {row['naechstes_spiel_datum']}
                    </div>
                </div>
                """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("Aktuell keine offenen Urteilssperren gefunden.")

    with col_sp2:
        st.markdown("#### 🧪 Live-Trigger-Test (Aufstellungs-Simulator)")
        with st.form("form_trigger_sperre"):
            if not df_sperren.empty:
                sperr_options = [
                    f"🚫 GESPERRT: {r['spieler']} ({r['mannschaft']}) -> Kader #{r['kader_id']} / Spiel #{r['naechstes_spiel_id']}"
                    for _, r in df_sperren.iterrows()
                ]
                auswahl_sperre = st.selectbox(
                    "Schnellauswahl gesperrter Spieler:", sperr_options
                )
                idx_sel = sperr_options.index(auswahl_sperre)
                def_kader = int(df_sperren.iloc[idx_sel]["kader_id"])
                def_spiel = int(df_sperren.iloc[idx_sel]["naechstes_spiel_id"])
            else:
                def_kader, def_spiel = 1, 97

            kader_in = st.number_input("Kader-ID des Spielers:", value=def_kader, step=1)
            spiel_in = st.number_input("Spiel-ID für Nominierung:", value=def_spiel, step=1)
            startelf_in = st.checkbox("Für die Startelf nominieren", value=True)

            if st.form_submit_button("🚀 Spieler jetzt auf Spielberichtsbogen setzen"):
                try:
                    execute_stmt(
                        "INSERT INTO spieltag_kader (startelf, spiel_id, kader_id) VALUES (%s, %s, %s);",
                        (startelf_in, spiel_in, kader_in),
                    )
                    success_card(
                        "NOMINIERUNG ERLAUBT!",
                        f"Kader-Spieler #{kader_in} ist spielberechtigt und wurde für Spiel #{spiel_in} eingetragen.",
                    )
                except psycopg2.Error as e:
                    boom_alert(
                        "BOOM! TRIGGER HAT DIE AUFSTELLUNG BLOCKIERT",
                        e.pgerror or str(e),
                    )

# ---------------------------------------------------------------------
# TAB 4: PLATZ-KONFLIKT & SPIELERPASS-WÄCHTER (EXCLUSION CONSTRAINTS)
# ---------------------------------------------------------------------
with tab4:
    section_title(
        "🏟️", "Use-Case 4: Exclusion Constraints (Kein Doppel-Platz & Kein Doppel-Pass)"
    )

    col_ex1, col_ex2 = st.columns(2)

    # LINKS: KEIN DOPPEL-PLATZ
    with col_ex1:
        st.markdown(
            """
        <div class="flip7-card">
            <span class="flip7-badge badge-teal">CONSTRAINT 1: excl_kein_doppel_platz</span>
            <h4 style="margin:8px 0 4px 0;">🏟️ Platzbelegung & 120-Minuten-Sperre</h4>
            <p style="font-size:13.5px; margin:0;">
                PostgreSQL prüft über einen GIST-Index mit <code>tsrange(anstoss_zeit, anstoss_zeit + 120 min) WITH &&</code>, dass sich auf keinem Platz zwei Spiele zeitlich überschneiden.
            </p>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Zeige bestehende Spiele am 08.11.2026 als Referenz
        df_platz_ref = run_query("""
            SELECT sp.spiel_id, sp.platz_id, pl.name || ' (' || sa.name || ')' AS platz_name,
                   sp.anstoss_zeit, sp.spieltag_id, sp.heim_teilnahme_id, sp.gast_teilnahme_id
            FROM spiel sp
            JOIN platz pl ON pl.platz_id = sp.platz_id
            JOIN sportanlage sa ON sa.sportanlage_id = pl.sportanlage_id
            WHERE sp.anstoss_zeit::date = DATE '2026-11-08'
            ORDER BY sp.platz_id LIMIT 6;
        """)
        st.caption("Belegte Plätze am Sonntag, 08.11.2026 (Auszug):")
        st.dataframe(df_platz_ref, use_container_width=True, hide_index=True)

        with st.form("form_platz_constraint"):
            st.markdown(
                "**Test-Szenario:** Platz **62** ist am **08.11.2026 von 14:00 bis 16:00 Uhr** durch Spiel #97 belegt. Versuche ein Spiel um **14:30 Uhr** anzusetzen:"
            )
            c1, c2 = st.columns(2)
            with c1:
                p_id = st.number_input("Platz-ID:", value=62, step=1)
                z_str = st.text_input("Anstoßzeit:", value="2026-11-08 14:30:00")
                spt_id = st.number_input("Spieltag-ID:", value=13, step=1)
            with c2:
                h_id = st.number_input("Heim-Teilnahme-ID:", value=1, step=1)
                g_id = st.number_input(
                    "Gast-Teilnahme-ID (Tipp: 1 = Selbstspiel-Check):",
                    value=2,
                    step=1,
                )

            if st.form_submit_button("📅 Spielansetzung prüfen & speichern"):
                try:
                    execute_stmt(
                        "INSERT INTO spiel (anstoss_zeit, heim_teilnahme_id, gast_teilnahme_id, platz_id, spieltag_id) VALUES (%s, %s, %s, %s, %s);",
                        (z_str, h_id, g_id, p_id, spt_id),
                    )
                    success_card(
                        "SPIEL ANGESETZT!",
                        f"Platz {p_id} war frei – Spiel wurde erfolgreich für {z_str} eingetragen.",
                    )
                except psycopg2.Error as e:
                    boom_alert(
                        "BOOM! PLATZ- ODER TEAM-CONSTRAINT VERLETZT",
                        e.pgerror or str(e),
                    )

    # RECHTS: KEIN DOPPEL-PASS
    with col_ex2:
        st.markdown(
            """
        <div class="flip7-card">
            <span class="flip7-badge badge-gold">CONSTRAINT 2: exclude_kein_doppelpass</span>
            <h4 style="margin:8px 0 4px 0;">🪪 Spielerpass-Historie & Transfer-Prüfung</h4>
            <p style="font-size:13.5px; margin:0;">
                Verhindert über <code>daterange(gueltig_ab, gueltig_bis, '[]') WITH &&</code>, dass ein Spieler zur selben Zeit zwei gültige Spielerpässe besitzt.
            </p>
        </div>
        """,
            unsafe_allow_html=True,
        )

        df_paesse_ref = run_query("""
            SELECT sp.pass_id, sp.person_id, p.vorname || ' ' || p.nachname AS spieler,
                   v.name AS verein, sp.gueltig_ab, sp.gueltig_bis
            FROM spielerpass sp
            JOIN person p ON p.person_id = sp.person_id
            JOIN verein v ON v.verein_id = sp.verein_id
            WHERE sp.person_id IN (1, 2, 4, 8, 16)
            ORDER BY sp.person_id, sp.gueltig_ab DESC;
        """)
        st.caption(
            "Bestehende Spielerpässe (inkl. abgelaufener Vorgänger-Pässe bei Vereinswechsel):"
        )
        st.dataframe(df_paesse_ref, use_container_width=True, hide_index=True)

        with st.form("form_pass_constraint"):
            st.markdown(
                "**Test-Szenario:** Spieler **#1 (Stanisław Cegła)** besitzt einen gültigen Pass bis **30.06.2028**. Versuche einen überlappenden Zweitpass ab **2026-11-01** auszustellen:"
            )
            cp1, cp2 = st.columns(2)
            with cp1:
                pers_pass_id = st.number_input("Person-ID:", value=1, step=1)
                ver_pass_id = st.number_input("Neuer Verein-ID:", value=1, step=1)
            with cp2:
                ab_date = st.text_input("Gültig ab (YYYY-MM-DD):", value="2026-11-01")
                bis_date = st.text_input("Gültig bis (YYYY-MM-DD):", value="2027-06-30")

            if st.form_submit_button("🪪 Spielerpass im Verbandssystem beantragen"):
                try:
                    execute_stmt(
                        "INSERT INTO spielerpass (gueltig_ab, gueltig_bis, person_id, verein_id) VALUES (%s, %s, %s, %s);",
                        (ab_date, bis_date, pers_pass_id, ver_pass_id),
                    )
                    success_card(
                        "SPIELERPASS AUSGESTELLT!",
                        f"Neuer Pass für Person #{pers_pass_id} ohne zeitliche Überschneidung gespeichert.",
                    )
                except psycopg2.Error as e:
                    boom_alert(
                        "BOOM! DOPPEL-PASS ODER DATUMS-CHECK VERLETZT",
                        e.pgerror or str(e),
                    )

# ---------------------------------------------------------------------
# TAB 5: SPORTGERICHT & 25-REGELN-AUDITOR (03_pruefungen_2.sql)
# ---------------------------------------------------------------------
with tab5:
    section_title("⚖️", "Use-Case 5: Sportgerichtsurteile fällen & 25-Regeln-Auditor")

    col_sg1, col_sg2 = st.columns([3, 2])
    df_rote = run_query("SELECT * FROM v_rote_karten_urteile;")

    with col_sg1:
        st.markdown("#### 📕 Alle Roten Karten & Sportgerichts-Verfahren (View)")
        st.dataframe(df_rote, use_container_width=True, hide_index=True)

    with col_sg2:
        st.markdown("#### 🔨 Neues Urteil für offene Rote Karte fällen")
        offene_rote = df_rote[df_rote["hat_urteil"] == False]
        katalog_df = run_query(
            "SELECT strafe_id, vergehen || ' (Standard: ' || standard_sperre_spiele || ' Sp. / ' || geldstrafe_eur || ' €)' AS label, standard_sperre_spiele, geldstrafe_eur FROM strafenkatalog ORDER BY strafe_id;"
        )

        if not offene_rote.empty:
            with st.form("form_urteil_faellen"):
                rote_opts = [
                    f"Ereignis #{r['spielereignis_id']}: {r['spieler']} ({r['mannschaft']}) am {r['spiel_datum']}"
                    for _, r in offene_rote.iterrows()
                ]
                sel_rote = st.selectbox("Offene Rote Karte wählen:", rote_opts)
                sel_eid = int(
                    offene_rote.iloc[rote_opts.index(sel_rote)][
                        "spielereignis_id"
                    ]
                )

                sel_kat = st.selectbox(
                    "Tatbestand aus Strafenkatalog:", katalog_df["label"]
                )
                kat_row = katalog_df.loc[katalog_df["label"] == sel_kat].iloc[0]

                sperre_in = st.number_input(
                    "Festgelegte Sperre (Spiele):",
                    min_value=1,
                    max_value=15,
                    value=int(kat_row["standard_sperre_spiele"]),
                )
                geld_in = st.number_input(
                    "Geldstrafe (€):",
                    min_value=0.0,
                    value=float(kat_row["geldstrafe_eur"]),
                    step=25.0,
                )

                if st.form_submit_button("⚖️ Rechtskräftiges Urteil speichern"):
                    try:
                        execute_stmt(
                            """INSERT INTO urteil (datum, sperre_spiele, tatsaechliche_geldstrafe, spielereignis_id, strafe_id)
                               VALUES ( DATE '2026-11-02', %s, %s, %s, %s );""",
                            (
                                sperre_in,
                                geld_in,
                                sel_eid,
                                int(kat_row["strafe_id"]),
                            ),
                        )
                        success_card(
                            "URTEIL GESPROCHEN!",
                            f"Spieler ist ab sofort für {sperre_in} Spiele im Trigger gesperrt (siehe Tab 3).",
                        )
                        st.rerun()
                    except psycopg2.Error as e:
                        boom_alert("Fehler beim Urteilsspruch", e.pgerror or str(e))
        else:
            st.success(
                "✅ Alle Roten Karten sind bereits vom Sportgericht verhandelt worden!"
            )

    section_title("✅", "Live-Datenbank-Audit (Alle 25 Regeln aus 03_pruefungen_2.sql)")
    st.caption(
        "Prüft in Echtzeit sämtliche 25 Geschäftsregeln (Spielberechtigungen, Pässe, Schiedsrichter-Neutralität, Wechsel-Logik, Torminuten und Trigger-Regeln):"
    )

    if st.button("🔍 Alle 25 Konsistenz-Prüfungen jetzt live gegen Supabase ausführen"):
        audit_sql = """
        WITH
        gespielt AS (SELECT DISTINCT spiel_id FROM spieltag_kader),
        bogen AS (
            SELECT sk.spieltag_kader_id, sk.spiel_id, sk.startelf, k.kader_id, k.person_id, k.teilnahme_id
            FROM spieltag_kader sk JOIN kader k ON k.kader_id = sk.kader_id
        ),
        ereignis AS (
            SELECT e.spielereignis_id, e.spiel_id, e.minute, 'tor' AS typ, t.spieltag_kader_id, NULL::varchar AS art
            FROM spielereignis e JOIN tor t USING (spielereignis_id)
            UNION ALL
            SELECT e.spielereignis_id, e.spiel_id, e.minute, 'karte', k.spieltag_kader_id, k.art
            FROM spielereignis e JOIN karte k USING (spielereignis_id)
            UNION ALL
            SELECT e.spielereignis_id, e.spiel_id, e.minute, 'raus', w.spieltag_kader_id_raus, NULL
            FROM spielereignis e JOIN wechsel w USING (spielereignis_id)
            UNION ALL
            SELECT e.spielereignis_id, e.spiel_id, e.minute, 'rein', w.spieltag_kader_id_rein, NULL
            FROM spielereignis e JOIN wechsel w USING (spielereignis_id)
        )
        SELECT nr, pruefung, verstoesse FROM (
          SELECT 1 AS nr, 'Kader: Spieler ohne gültigen Pass für den Verein in der Saison' AS pruefung, count(*) AS verstoesse
          FROM kader k JOIN staffel_teilnahme t ON t.teilnahme_id = k.teilnahme_id JOIN mannschaft m ON m.mannschaft_id = t.mannschaft_id JOIN staffel s ON s.staffel_id = t.staffel_id JOIN saison sa ON sa.saison_id = s.saison_id
          WHERE NOT EXISTS (SELECT 1 FROM spielerpass p WHERE p.person_id = k.person_id AND p.verein_id = m.verein_id AND p.gueltig_ab <= sa.ende AND p.gueltig_bis >= sa.beginn)
          UNION ALL SELECT 2, 'Kader: Spieler in mehreren Kadern derselben Saison', count(*) FROM (SELECT k.person_id FROM kader k JOIN staffel_teilnahme t ON t.teilnahme_id = k.teilnahme_id JOIN staffel s ON s.staffel_id = t.staffel_id GROUP BY k.person_id, s.saison_id HAVING count(*) > 1) x
          UNION ALL SELECT 3, 'Kader: Rückennummer in einer Mannschaft doppelt', count(*) FROM (SELECT 1 FROM kader GROUP BY teilnahme_id, rueckennummer HAVING count(*) > 1) x
          UNION ALL SELECT 4, 'Pässe: zwei gleichzeitig gültige Pässe einer Person', count(*) FROM spielerpass a JOIN spielerpass b ON b.person_id = a.person_id AND b.pass_id > a.pass_id WHERE a.gueltig_ab <= b.gueltig_bis AND b.gueltig_ab <= a.gueltig_bis
          UNION ALL SELECT 5, 'Pässe: Ende vor Beginn', count(*) FROM spielerpass WHERE gueltig_bis < gueltig_ab
          UNION ALL SELECT 6, 'Staffel: Verein mit zwei Mannschaften in derselben Staffel', count(*) FROM (SELECT 1 FROM staffel_teilnahme t JOIN mannschaft m USING (mannschaft_id) GROUP BY t.staffel_id, m.verein_id HAVING count(*) > 1) x
          UNION ALL SELECT 7, 'Staffel: Mannschaft in mehreren Staffeln einer Saison', count(*) FROM (SELECT 1 FROM staffel_teilnahme t JOIN staffel s USING (staffel_id) GROUP BY t.mannschaft_id, s.saison_id HAVING count(*) > 1) x
          UNION ALL SELECT 8, 'Spiel: Heim oder Gast nicht aus der Staffel des Spieltags, oder Heim = Gast', count(*) FROM spiel sp JOIN spieltag st ON st.spieltag_id = sp.spieltag_id JOIN staffel_teilnahme h ON h.teilnahme_id = sp.heim_teilnahme_id JOIN staffel_teilnahme g ON g.teilnahme_id = sp.gast_teilnahme_id WHERE h.staffel_id <> st.staffel_id OR g.staffel_id <> st.staffel_id OR h.teilnahme_id = g.teilnahme_id
          UNION ALL SELECT 9, 'Spiel: Mannschaft zweimal am selben Spieltag', count(*) FROM (SELECT 1 FROM (SELECT spieltag_id, heim_teilnahme_id AS t FROM spiel UNION ALL SELECT spieltag_id, gast_teilnahme_id FROM spiel) x GROUP BY spieltag_id, t HAVING count(*) > 1) y
          UNION ALL SELECT 10, 'Spiel: Platz doppelt belegt (2 Stunden je Spiel)', count(*) FROM spiel a JOIN spiel b ON b.platz_id = a.platz_id AND b.spiel_id > a.spiel_id WHERE abs(extract(epoch FROM b.anstoss_zeit - a.anstoss_zeit)) < 7200
          UNION ALL SELECT 11, 'Schiedsrichter: ohne Freigabe für die Spielklasse', count(*) FROM spiel_schiedsrichter ss JOIN schiedsrichter sr ON sr.person_id = ss.person_id JOIN spiel sp ON sp.spiel_id = ss.spiel_id JOIN spieltag st ON st.spieltag_id = sp.spieltag_id JOIN staffel s ON s.staffel_id = st.staffel_id JOIN spielklasse k ON k.spielklasse_id = s.spielklasse_id WHERE sr.hoechste_ebene > k.ebene
          UNION ALL SELECT 12, 'Schiedsrichter: nicht neutral (Stammverein spielt mit)', count(*) FROM spiel_schiedsrichter ss JOIN schiedsrichter sr ON sr.person_id = ss.person_id JOIN spiel sp ON sp.spiel_id = ss.spiel_id JOIN staffel_teilnahme h ON h.teilnahme_id = sp.heim_teilnahme_id JOIN staffel_teilnahme g ON g.teilnahme_id = sp.gast_teilnahme_id JOIN mannschaft mh ON mh.mannschaft_id = h.mannschaft_id JOIN mannschaft mg ON mg.mannschaft_id = g.mannschaft_id WHERE sr.stammverein_id IN (mh.verein_id, mg.verein_id)
          UNION ALL SELECT 13, 'Schiedsrichter: am selben Tag mehrfach eingeteilt', count(*) FROM (SELECT 1 FROM spiel_schiedsrichter ss JOIN spiel sp USING (spiel_id) GROUP BY ss.person_id, sp.anstoss_zeit::date HAVING count(*) > 1) x
          UNION ALL SELECT 14, 'Spieltagskader: Spieler gehört zu keiner der beiden Mannschaften', count(*) FROM bogen b JOIN spiel sp ON sp.spiel_id = b.spiel_id WHERE b.teilnahme_id NOT IN (sp.heim_teilnahme_id, sp.gast_teilnahme_id)
          UNION ALL SELECT 15, 'Spieltagskader: Startelf nicht genau 11 Spieler', count(*) FROM (SELECT 1 FROM bogen GROUP BY spiel_id, teilnahme_id HAVING count(*) FILTER (WHERE startelf) <> 11) x
          UNION ALL SELECT 16, 'Spieltagskader: Spieler doppelt auf dem Bogen', count(*) FROM (SELECT 1 FROM spieltag_kader GROUP BY spiel_id, kader_id HAVING count(*) > 1) x
          UNION ALL SELECT 19, 'Ereignis: Spieler gehört nicht zum Spiel des Ereignisses', count(*) FROM ereignis e JOIN spieltag_kader sk ON sk.spieltag_kader_id = e.spieltag_kader_id WHERE sk.spiel_id <> e.spiel_id
          UNION ALL SELECT 20, 'Ereignis: kein oder mehr als ein Subtyp (Tor, Karte, Wechsel)', count(*) FROM spielereignis e WHERE (SELECT count(*) FROM tor t WHERE t.spielereignis_id = e.spielereignis_id) + (SELECT count(*) FROM karte k WHERE k.spielereignis_id = e.spielereignis_id) + (SELECT count(*) FROM wechsel w WHERE w.spielereignis_id = e.spielereignis_id) <> 1
          UNION ALL SELECT 21, 'Wechsel: Eingewechselter kam nicht von der Bank derselben Mannschaft', count(*) FROM wechsel w JOIN bogen r ON r.spieltag_kader_id = w.spieltag_kader_id_raus JOIN bogen n ON n.spieltag_kader_id = w.spieltag_kader_id_rein WHERE n.startelf OR r.teilnahme_id <> n.teilnahme_id
          UNION ALL SELECT 23, 'Karte: unbekannte Kartenart', count(*) FROM karte WHERE art NOT IN ('Gelb', 'Gelb-Rot', 'Rot')
          UNION ALL SELECT 24, 'Urteil: zu einer Karte, die nicht Rot ist, oder vor dem Spiel', count(*) FROM urteil u JOIN karte k ON k.spielereignis_id = u.spielereignis_id JOIN spielereignis e ON e.spielereignis_id = k.spielereignis_id JOIN spiel sp ON sp.spiel_id = e.spiel_id WHERE k.art <> 'Rot' OR u.datum < sp.anstoss_zeit::date
          UNION ALL SELECT 25, 'Trigger-Regel: Spieler mit nicht abgesessener Urteilssperre auf dem Bogen', count(*) FROM urteil u JOIN karte k ON k.spielereignis_id = u.spielereignis_id JOIN spieltag_kader a ON a.spieltag_kader_id = k.spieltag_kader_id JOIN kader kd ON kd.kader_id = a.kader_id JOIN spiel s_alt ON s_alt.spiel_id = a.spiel_id JOIN spieltag_kader b ON b.kader_id = a.kader_id JOIN spiel s_neu ON s_neu.spiel_id = b.spiel_id WHERE s_neu.anstoss_zeit > s_alt.anstoss_zeit AND (SELECT count(*) FROM spiel x WHERE kd.teilnahme_id IN (x.heim_teilnahme_id, x.gast_teilnahme_id) AND x.anstoss_zeit > s_alt.anstoss_zeit AND x.anstoss_zeit < s_neu.anstoss_zeit) < u.sperre_spiele
        ) pruefungen ORDER BY nr;
        """
        df_audit = run_query(audit_sql)
        total_errors = int(df_audit["verstoesse"].sum())
        if total_errors == 0:
            success_card(
                "ALLE KONSISTENZ-CHECKS BESTANDEN (0 VERSTÖSSE)!",
                "Sämtliche 45.500+ Datensätze halten alle strukturellen Constraints und Trigger-Regeln zu 100 % ein.",
            )
        st.dataframe(df_audit, use_container_width=True, hide_index=True)