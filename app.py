import json
import os
import html
from datetime import date, timedelta

import yaml
from yaml.loader import SafeLoader

import folium
import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth
from streamlit_folium import st_folium

import pipeline as P

# ── brand / asset configuration — edit these for a new client or pipeline ───────
BRAND = "RoW Monitoring Tool"
SUBTITLE = "Satellite-based pipeline right-of-way monitoring"
ORG = "BioSky Space Innovations"
OPERATOR = "Pipeline"
PRODUCT_LINE = "Petroleum product pipeline"
PIPELINE_NAME = "Jaipur Segment"
SCAN_CADENCE_DAYS = 12
MANIFEST = "data/derived/layers_manifest.json"

KPI = {
    "total": "#38bdf8",
    "Critical": "#e5484d",
    "High": "#f0883e",
    "Medium": "#f5b013",
    "change": "#a855f7",
}

STATUS_OPTIONS = [
    "New",
    "Acknowledged",
    "Field Verification",
    "Resolved",
    "Under review",
    "Advisory",
    "Field dispatch",
]

# ── domain content kept local to app.py (no pipeline.py dependency) ─────────────
SEV_SLA = {
    "Critical": "Immediate — field verification within 24 h",
    "High": "Priority — field verification within 72 h",
    "Medium": "Scheduled — next routine patrol (≤7 days)",
    "Low": "Routine — monitor at next scheduled pass",
}
SEV_SLA_SHORT = {
    "Critical": "≤ 24h",
    "High": "≤ 72h",
    "Medium": "≤ 7d",
    "Low": "Routine",
}

CATEGORY_ICON = {
    "vegetation": "🌿",
    "water": "💧",
    "excavation": "🚧",
    "road": "🛣️",
    "structure": "🏗️",
}
CATEGORY_ACTION = {
    "vegetation": (
        "Dispatch vegetation clearance crew; confirm clearance meets "
        "minimum RoW easement spacing."
    ),
    "water": (
        "Verify local drainage pattern and assess erosion/scour risk to "
        "buried pipeline coating and cathodic protection."
    ),
    "excavation": (
        "Possible third-party interference. Contact landowner and "
        "local authority per encroachment SOP; confirm no mechanical "
        "contact with the pipeline before any further digging."
    ),
    "road": (
        "Survey crew to confirm an unauthorized crossing; check depth of "
        "cover for mechanical-damage risk from vehicle loading."
    ),
    "structure": (
        "Cross-check against the RoW easement and approved-structure "
        "register; initiate a removal notice if unauthorized."
    ),
}

st.set_page_config(
    page_title=f"{BRAND} — {ORG}",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{--ink:#0a0f16;--panel:#111a24;--surface:#17212c;--surface2:#1c2733;
      --border:#25323f;--muted:#8fa3b8;--text:#cfdae6;--strong:#f3f7fb;
      --brand:#38bdf8;--good:#3ecf8e;}
html,body,[class*="css"],.stApp{font-family:'Inter',system-ui,sans-serif;}
.stApp{background:
  radial-gradient(1200px 500px at 10% -10%, rgba(56,189,248,.05), transparent),
  var(--ink);}
/* Hide Streamlit-hosted chrome and floating platform controls for client demos. */
[data-testid="stToolbar"],
[data-testid="stStatusWidget"],
[data-testid="stAppDeployButton"],
.stDeployButton,
#MainMenu,
footer,
.viewerBadge_container__1QSob,
[data-testid="stDecoration"]{display:none !important; visibility:hidden !important;}
header{visibility:hidden !important; height:0 !important;}

.block-container{padding-top:1rem;padding-bottom:0.5rem;max-width:1640px;}
[data-testid="stSidebar"]{background:var(--panel);border-right:1px solid var(--border);}
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stMultiSelect label,
[data-testid="stSidebar"] .stSlider label{color:var(--muted)!important;
  font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em;}
h1,h2,h3,h4{color:var(--strong);}
hr{border-color:var(--border);}

.topbar{display:flex;align-items:center;justify-content:space-between;gap:18px;
  padding:14px 20px;border:1px solid var(--border);border-radius:14px;
  background:linear-gradient(180deg,var(--surface2),var(--panel));margin-bottom:10px;
  box-shadow:0 1px 0 rgba(255,255,255,.02) inset, 0 8px 24px rgba(0,0,0,.25);}
.tb-left{display:flex;flex-direction:column;gap:3px;min-width:200px;}
.tb-left .mark{font-size:19px;font-weight:800;color:var(--strong);letter-spacing:-.01em;}
.tb-left .sub{font-size:12px;color:var(--muted);}
.tb-mid{display:flex;gap:24px;flex-wrap:wrap;align-items:center;}
.tb-field{display:flex;flex-direction:column;gap:1px;}
.tb-field .k{font-size:9.5px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;font-weight:700;}
.tb-field .v{font-size:12.5px;color:var(--text);font-weight:600;}
.tb-right{display:flex;flex-direction:column;align-items:flex-end;gap:6px;}
.live-pill{display:inline-flex;align-items:center;gap:6px;font-size:10.5px;
  font-weight:700;letter-spacing:.04em;color:var(--good);
  background:rgba(62,207,142,.1);border:1px solid rgba(62,207,142,.35);
  border-radius:999px;padding:3px 10px;}
.live-dot{width:6px;height:6px;border-radius:50%;background:var(--good);
  animation:pulseDot 1.8s infinite;}
@keyframes pulseDot{0%{box-shadow:0 0 0 0 rgba(62,207,142,.55);}
  70%{box-shadow:0 0 0 6px rgba(62,207,142,0);}100%{box-shadow:0 0 0 0 rgba(62,207,142,0);}}
.conf-badge{font-size:10.5px;color:var(--muted);}
.conf-badge b{color:var(--text);}

.priority-banner{display:flex;align-items:center;gap:12px;padding:11px 18px;
  border-radius:12px;margin-bottom:10px;border:1px solid rgba(229,72,77,.4);
  background:linear-gradient(90deg,rgba(229,72,77,.14),rgba(229,72,77,.04));}
.priority-banner .ic{font-size:20px;}
.priority-banner .txt{font-size:13px;color:var(--text);line-height:1.4;}
.priority-banner .txt b{color:#ff8a8d;}
.priority-ok{display:flex;align-items:center;gap:10px;padding:9px 18px;
  border-radius:12px;margin-bottom:10px;border:1px solid rgba(62,207,142,.3);
  background:rgba(62,207,142,.06);font-size:12.5px;color:var(--text);}

.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:12px;}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:13px;
  padding:13px 15px;position:relative;overflow:hidden;transition:transform .15s,border-color .15s;}
.kpi:hover{transform:translateY(-2px);border-color:rgba(255,255,255,.14);}
.kpi .ic{font-size:15px;opacity:.85;}
.kpi .n{font-size:28px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;
  margin-top:6px;}
.kpi .l{font-size:10.5px;color:var(--muted);margin-top:5px;font-weight:700;
  text-transform:uppercase;letter-spacing:.04em;}
.kpi .d{font-size:10.5px;color:var(--muted);margin-top:3px;}

.legrow{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text);margin:3px 0;}
.swatch{width:12px;height:12px;border-radius:3px;display:inline-block;}
.stTabs [data-baseweb="tab"]{background:var(--panel);border:1px solid var(--border);
  border-radius:9px 9px 0 0;color:var(--muted);padding:7px 18px;font-weight:600;}
.stTabs [aria-selected="true"]{background:var(--surface);color:var(--strong);}
.loginwrap{text-align:center;margin-bottom:14px;}
.loginwrap .mk{font-size:28px;font-weight:800;color:var(--strong);}
.loginwrap .sb{color:var(--muted);margin-bottom:4px;font-size:13px;}
.notice{color:var(--muted);font-size:11px;margin-top:14px;text-align:center;
  border-top:1px solid var(--border);padding-top:12px;}
[data-testid="stVerticalBlockBorderWrapper"]{background:var(--surface)!important;
  border:1px solid var(--border)!important;border-radius:16px!important;
  box-shadow:0 20px 60px rgba(0,0,0,.35);padding:8px 10px;}
[data-testid="stVerticalBlockBorderWrapper"] label{color:var(--muted)!important;}

.exec-summary{background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:16px 18px;font-size:13.5px;line-height:1.65;
  color:var(--text);margin-bottom:14px;}
.exec-summary b{color:var(--strong);}
.detail-card{background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:16px 18px;}
.detail-card .dh{display:flex;align-items:center;gap:10px;margin-bottom:10px;}
.detail-card .dh .id{font-size:15px;font-weight:800;color:var(--strong);}
.detail-row{display:flex;justify-content:space-between;font-size:12.5px;
  padding:5px 0;border-bottom:1px solid var(--border);color:var(--text);}
.detail-row span:first-child{color:var(--muted);}
.action-box{margin-top:10px;padding:10px 12px;border-radius:9px;
  background:rgba(240,136,62,.08);border:1px solid rgba(240,136,62,.3);
  font-size:12.5px;color:var(--text);line-height:1.5;}
.sev-chip{display:inline-block;padding:2px 9px;border-radius:999px;font-size:10.5px;
  font-weight:700;color:#fff;}
.app-footer{display:flex;justify-content:space-between;align-items:center;
  padding:10px 4px;margin-top:4px;font-size:11px;color:var(--muted);
  border-top:1px solid var(--border);}

.demo-strip{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;
  padding:11px 15px;margin:0 0 12px;border:1px solid rgba(56,189,248,.28);
  border-radius:11px;background:linear-gradient(90deg,rgba(56,189,248,.09),rgba(56,189,248,.025));
  color:var(--text);font-size:12px;line-height:1.5;}
.demo-strip b{color:#a5e4ff;}
.demo-tag{white-space:nowrap;border:1px solid rgba(56,189,248,.35);border-radius:999px;
  color:#a5e4ff;padding:3px 9px;font-size:10px;font-weight:800;letter-spacing:.06em;}
.freshness{color:var(--muted);font-size:10.5px;text-align:right;line-height:1.45;}
.freshness strong{color:var(--text);}
.section-lead{color:var(--muted);font-size:12px;margin-top:-7px;margin-bottom:12px;}
.queue-note{padding:10px 13px;border:1px solid var(--border);background:var(--surface);
  border-radius:10px;color:var(--muted);font-size:11.5px;line-height:1.5;margin:8px 0 12px;}
.workflow-steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:10px 0 18px;}
.workflow-step{padding:13px;border:1px solid var(--border);border-radius:11px;background:var(--surface);}
.workflow-step .num{font-size:10px;color:var(--brand);font-weight:800;letter-spacing:.08em;}
.workflow-step .name{font-size:13px;color:var(--strong);font-weight:700;margin:4px 0;}
.workflow-step .desc{font-size:11px;color:var(--muted);line-height:1.45;}
.integration-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:10px;}
.integration-item{padding:13px;border:1px solid var(--border);border-radius:10px;background:var(--panel);}
.integration-item b{display:block;color:var(--text);font-size:12px;margin-bottom:4px;}
.integration-item span{color:var(--muted);font-size:11px;line-height:1.45;}
.detail-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0;}
.small-muted{font-size:10.5px;color:var(--muted);}
@media(max-width:900px){.workflow-steps,.integration-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media(max-width:600px){.workflow-steps,.integration-grid{grid-template-columns:1fr;}.demo-strip{flex-direction:column;}}
</style>
""",
    unsafe_allow_html=True,
)


# ── auth ────────────────────────────────────────────────────────────────────────
def _plain(obj):
    return {k: _plain(v) for k, v in obj.items()} if hasattr(obj, "items") else obj


@st.cache_resource(show_spinner=False)
def load_auth_config(path="config.yaml"):
    try:
        if "credentials" in st.secrets:
            return {
                "credentials": _plain(st.secrets["credentials"]),
                "cookie": _plain(st.secrets["cookie"]),
            }
    except Exception:
        pass
    with open(path) as f:
        return yaml.load(f, Loader=SafeLoader)


config = load_auth_config()
authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
)

if not st.session_state.get("authentication_status"):
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        st.markdown("<div style='height:6vh'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(
                f"<div class='loginwrap'>"
                f"<div class='mk'>🛰️ {BRAND}</div>"
                f"<div class='sb'>{SUBTITLE}</div>"
                f"<div class='sb' style='font-size:11px;'>{OPERATOR} · {PIPELINE_NAME}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            authenticator.login(
                location="main",
                fields={"Form name": "Sign in", "Login": "Sign in"},
            )
            if st.session_state.get("authentication_status") is False:
                st.error("Incorrect username or password.")
            st.markdown(
                "<div class='notice'>Authorized personnel only. All activity "
                "on this console is logged.</div>",
                unsafe_allow_html=True,
            )
    st.stop()

authenticator.logout(button_name="Log out", location="main", key="logout_main_btn")


# ── data + manifest ─────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def load_manifest(path=MANIFEST):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


@st.cache_resource(show_spinner=False)
def load_change_cases(path):
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"type": "FeatureCollection", "features": []}


@st.cache_resource(show_spinner="Building corridor model…")
def get_data(cache_key, row_margin, detect_buffer, _lines):
    cfg = {
        **P.DEFAULT_CFG,
        "ROW_MARGIN_M": row_margin,
        "DETECT_BUFFER_M": detect_buffer,
    }
    return P.generate_corridor(_lines, cfg)


man = load_manifest()
PIPELINE_START = (75.85311, 26.87124)
PIPELINE_END = (75.80952, 26.88724)
lines = [[PIPELINE_START, PIPELINE_END]]
center = [
    (PIPELINE_START[1] + PIPELINE_END[1]) / 2,
    (PIPELINE_START[0] + PIPELINE_END[0]) / 2,
]
cache_key = "jaipur_pipeline_20261031"

SOUTH, NORTH, WEST, EAST = 26.86791, 26.89145, 75.80760, 75.85929
VIEW_BOUNDS = [[SOUTH, WEST], [NORTH, EAST]]

change_fc = load_change_cases(man.get("cases_geojson") if man else None)


def change_sev(area):
    return (
        "Critical"
        if area > 8000
        else "High"
        if area > 3000
        else "Medium"
        if area > 800
        else "Low"
    )


def categorize(type_str):
    """Derive a detection category from the case's free-text type label."""
    t = type_str.lower()
    if "vegetation" in t:
        return "vegetation"
    if "water" in t or "flood" in t:
        return "water"
    if "excavation" in t:
        return "excavation"
    if "road" in t:
        return "road"
    if "structure" in t:
        return "structure"
    return "other"


def add_selected_basemaps(map_obj, show_google, show_satellite_image):
    """Add the basemap layers selected in the sidebar.

    P.build_map() creates its own default base TileLayer. Remove that layer so
    the sidebar checkboxes, rather than a permanently enabled base layer,
    control which basemap is visible. The internal P.BASEMAPS key remains
    "Google Satellite" for compatibility with pipeline.py, but the visible
    layer name is simply "Google".

    When both boxes are checked, Google is the lower layer and Satellite
    Image is placed above it at 50% opacity so both remain visible.
    """
    # Remove only the default base tile layer created by P.build_map(). Leave
    # ImageOverlay / GeoJson / FeatureGroup detection layers untouched.
    for child_key, child in list(map_obj._children.items()):
        if isinstance(child, folium.raster_layers.TileLayer) and not child.overlay:
            map_obj._children.pop(child_key, None)

    both_selected = show_google and show_satellite_image

    if show_google:
        google_url, google_attr, google_subs, google_max_zoom = P.BASEMAPS[
            "Google Satellite"
        ]
        folium.TileLayer(
            google_url,
            attr=google_attr,
            name="Google",
            subdomains=google_subs or "abc",
            max_zoom=google_max_zoom,
            opacity=1.0,
            overlay=True,
            control=False,
        ).add_to(map_obj)

    if show_satellite_image:
        sat_url, sat_attr, sat_subs, sat_max_zoom = P.BASEMAPS["Satellite Image"]
        folium.TileLayer(
            sat_url,
            attr=sat_attr,
            name="Satellite Image",
            subdomains=sat_subs or "abc",
            max_zoom=sat_max_zoom,
            opacity=0.5 if both_selected else 1.0,
            overlay=True,
            control=False,
        ).add_to(map_obj)


# ── sidebar ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        f"""<div style="font-size:24px;font-weight:800;color:#f3f7fb;
        letter-spacing:-0.5px;padding:8px 0 5px 0;white-space:nowrap;">
        🛰️ {BRAND}</div>""",
        unsafe_allow_html=True,
    )
    st.caption(f"{OPERATOR} · {PIPELINE_NAME}")
    st.divider()

    st.markdown("**Basemap layers**")
    show_satellite_image = st.checkbox(
        "Satellite Image", value=True, key="show_satellite_image_basemap_v3"
    )
    show_google = st.checkbox("Google", value=False, key="show_google_basemap_v3")
    if not show_google and not show_satellite_image:
        st.caption("No basemap selected — detection layers remain visible.")

    layer_labels = {k: lbl for k, lbl in P.LAYER_DEFS}
    chosen = st.multiselect(
        "Detection layers",
        options=P.ALL_LAYERS,
        default=P.ALL_LAYERS,
        format_func=lambda k: layer_labels[k],
    )
    severities = st.multiselect(
        "Severity filter (cases)",
        ["Critical", "High", "Medium", "Low"],
        default=["Critical", "High", "Medium", "Low"],
    )

    st.markdown("**Imagery**")
    epoch_opts, epoch_lookup = [], {}
    if man:
        for e in man.get("epochs", []):
            lbl = f"GEP {e['date']}"
            epoch_opts.append(lbl)
            epoch_lookup[lbl] = e
        if man.get("cartosat"):
            epoch_opts.append("Cartosat-2S")
            epoch_lookup["Cartosat-2S"] = man["cartosat"]
    if epoch_opts:
        sel_epoch = st.selectbox(
            "Show imagery epoch", ["(none)"] + epoch_opts, index=len(epoch_opts)
        )
        img_opacity = st.slider("Imagery opacity", 0.0, 1.0, 0.85, 0.05)
        show_change = st.toggle(
            "Show detected change layer", value=bool(man.get("change"))
        )
    else:
        sel_epoch, img_opacity, show_change = "(none)", 0.85, False
        # Keep the imagery controls available without displaying setup instructions
        # in the operator-facing demonstration sidebar.

    with st.expander("Corridor geometry"):
        row_margin = st.slider(
            "RoW margin (m)", 5, 60, P.DEFAULT_CFG["ROW_MARGIN_M"], 5
        )
        detect_buffer = st.slider(
            "Monitoring band (m)",
            20,
            150,
            P.DEFAULT_CFG["DETECT_BUFFER_M"],
            10,
        )

    st.markdown("**Legend**")
    st.markdown(
        "<div class='legrow'><span class='swatch' style='background:#ff1744'></span>"
        "Detected change (imagery)</div>"
        "<div class='legrow'><span class='swatch' style='background:#d7191c'></span>"
        "Vegetation — dense</div>"
        "<div class='legrow'><span class='swatch' style='background:#2196f3'></span>"
        "Water / flood</div>"
        "<div class='legrow'><span class='swatch' style='background:#8d6e63'></span>"
        "Excavation</div>"
        "<div class='legrow'><span class='swatch' style='background:#ffa500'></span>"
        "RoW corridor</div>",
        unsafe_allow_html=True,
    )

    st.divider()
    st.caption(f"Signed in as **{st.session_state.get('name', 'user')}**")
    authenticator.logout(button_name="Log out", location="sidebar", key="logout_btn")
    st.caption(f"{BRAND} v1.4 · operator demo build")


data = get_data(cache_key, row_margin, detect_buffer, lines)
cfg = data["cfg"]
cnt = data["counts"]
case_lookup = {c["id"]: c for c in data["cases"]}

# ── sidebar: chainage navigator (uses data["chainage_ticks"], already in pipeline.py) ──
with st.sidebar:
    with st.expander("Chainage navigator"):
        ch_pts = {f"CH {lbl}": pt for pt, lbl in data["chainage_ticks"]}
        ch_opts = ["(corridor overview)"] + list(ch_pts.keys())
        sel_ch = st.selectbox("Jump to chainage", ch_opts, index=0)
        jump_zoom = (
            st.slider("Jump zoom level", 15, 19, 17)
            if sel_ch != "(corridor overview)"
            else 14
        )

# ── per-session editable workflow state (status / assignee) ─────────────────────
if "case_status" not in st.session_state:
    st.session_state.case_status = {c["id"]: c["status"] for c in data["cases"]}
if "case_assignee" not in st.session_state:
    st.session_state.case_assignee = {c["id"]: "" for c in data["cases"]}
for c in data["cases"]:
    st.session_state.case_status.setdefault(c["id"], c["status"])
    st.session_state.case_assignee.setdefault(c["id"], "")


# ── merged case register (synthetic detections + imagery change) ─────────────────
det_rows = [
    {
        "ID": c["id"],
        "Type": c["type"],
        "Severity": c["sev"],
        "Confidence": c["conf"],
        "Chainage": f"CH {c['ch']}",
        "SLA": SEV_SLA_SHORT.get(c["sev"], ""),
        "Status": st.session_state.case_status.get(c["id"], c["status"]),
        "Assigned To": st.session_state.case_assignee.get(c["id"], ""),
        "Source": "Live scan",
        "Lat": round(c["latlon"][0], 5),
        "Lon": round(c["latlon"][1], 5),
    }
    for c in data["cases"]
]
chg_rows = []
for f in change_fc["features"]:
    p = f["properties"]
    sev = change_sev(p["area_m2"])
    chg_rows.append(
        {
            "ID": p["id"],
            "Type": f"Change {p['from']}→{p['to']}",
            "Severity": sev,
            "Confidence": p["conf"],
            "Chainage": f"{p['area_m2']} m²",
            "SLA": SEV_SLA_SHORT.get(sev, ""),
            "Status": st.session_state.case_status.get(p["id"], "New"),
            "Assigned To": st.session_state.case_assignee.get(p["id"], ""),
            "Source": "Imagery CD",
            "Lat": p["lat"],
            "Lon": p["lon"],
        }
    )
all_rows = det_rows + chg_rows
n_change = len(chg_rows)
n_total = len(all_rows)
open_rows = [r for r in all_rows if r["Status"] != "Resolved"]
n_open = len(open_rows)
n_crit = sum(1 for r in open_rows if r["Severity"] == "Critical")
n_high = sum(1 for r in open_rows if r["Severity"] == "High")
n_med = sum(1 for r in open_rows if r["Severity"] == "Medium")
n_low = sum(1 for r in open_rows if r["Severity"] == "Low")
n_unassigned = sum(1 for r in open_rows if not str(r.get("Assigned To", "")).strip())
n_change_open = sum(1 for r in open_rows if r["Source"] == "Imagery CD")
avg_conf = round(sum(r["Confidence"] for r in all_rows) / n_total) if n_total else 0

# Imagery freshness is operationally important: a past-due pass should be visible
# rather than presented as a live monitoring feed.
scan_timestamp = pd.to_datetime(cfg.get("SCAN_DATE"), errors="coerce")
scan_date = None if pd.isna(scan_timestamp) else scan_timestamp.date()
if scan_date:
    imagery_age_days = max((date.today() - scan_date).days, 0)
    next_pass_due = scan_date + timedelta(days=SCAN_CADENCE_DAYS)
    imagery_overdue = date.today() > next_pass_due
    imagery_freshness = (
        f"Refresh due · {imagery_age_days} days since pass"
        if imagery_overdue
        else f"Within cadence · {imagery_age_days} days since pass"
    )
    next_pass_label = next_pass_due.strftime("%d %b %Y")
else:
    imagery_age_days = None
    imagery_overdue = False
    imagery_freshness = "Pass date unavailable"
    next_pass_label = "Not available"

SEVERITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
STATUS_RANK = {"New": 0, "Acknowledged": 1, "Field dispatch": 2,
               "Field Verification": 3, "Under review": 4, "Advisory": 5,
               "Resolved": 6}

def priority_sort_key(row):
    return (SEVERITY_RANK.get(row.get("Severity"), 9),
            STATUS_RANK.get(row.get("Status"), 9),
            str(row.get("ID", "")))

# ── product header + operating context ───────────────────────────────────────────
corridor_range = f"CH 0+000 – {data['chainage_str'](data['L'])}"
status_label = "IMAGERY REFRESH DUE" if imagery_overdue else "DEMO ENVIRONMENT"
st.markdown(
    f"<div class='topbar'>"
    f"<div class='tb-left'><span class='mark'>🛰️ {BRAND}</span>"
    f"<span class='sub'>{SUBTITLE}</span></div>"
    f"<div class='tb-mid'>"
    f"<div class='tb-field'><span class='k'>Operator</span><span class='v'>{html.escape(OPERATOR)}</span></div>"
    f"<div class='tb-field'><span class='k'>Asset</span><span class='v'>{html.escape(PIPELINE_NAME)}</span></div>"
    f"<div class='tb-field'><span class='k'>Product</span><span class='v'>{html.escape(PRODUCT_LINE)}</span></div>"
    f"<div class='tb-field'><span class='k'>Monitored segment</span><span class='v'>{corridor_range}</span></div>"
    f"<div class='tb-field'><span class='k'>Last imagery pass</span><span class='v'>{html.escape(str(cfg.get('SCAN_DATE', '—')))}</span></div>"
    f"<div class='tb-field'><span class='k'>Cadence</span><span class='v'>Every {SCAN_CADENCE_DAYS} days</span></div>"
    f"</div>"
    f"<div class='tb-right'>"
    f"<span class='live-pill' style='color:#a5e4ff;background:rgba(56,189,248,.09);border-color:rgba(56,189,248,.3)'>{status_label}</span>"
    f"<span class='conf-badge'>Average candidate confidence <b>{avg_conf}%</b></span>"
    f"<span class='freshness'>Next pass due: <strong>{next_pass_label}</strong></span>"
    f"</div></div>",
    unsafe_allow_html=True,
)

st.markdown(
    "<div class='demo-strip'>"
    "<div><b>DEMONSTRATION WORKSPACE</b> · Sample candidate detections are shown to demonstrate the review and field-workflow experience. "
    "They are not live operational alerts or confirmed encroachments. Validate every candidate in the field before taking operational action.</div>"
    "<span class='demo-tag'>DEMO DATA</span></div>",
    unsafe_allow_html=True,
)

# A stale imagery pass is surfaced prominently instead of implying real-time coverage.
if scan_date:
    freshness_color = "#f5b013" if imagery_overdue else "#3ecf8e"
    freshness_icon = "⏳" if imagery_overdue else "✓"
    st.markdown(
        f"<div class='queue-note' style='border-left:3px solid {freshness_color}'>"
        f"{freshness_icon} <b style='color:var(--text)'>Imagery freshness:</b> {html.escape(imagery_freshness)}. "
        f"Scheduled cadence: {SCAN_CADENCE_DAYS} days · Next pass due: {next_pass_label}. "
        "A production deployment should update this from the actual acquisition manifest.</div>",
        unsafe_allow_html=True,
    )

# ── priority banner ──────────────────────────────────────────────────────────────
priority_rows = sorted(open_rows, key=priority_sort_key)
if n_crit > 0 or n_high > 0:
    first_priority = priority_rows[0]
    priority_text = (
        f"<b>{n_crit} Critical</b> and <b>{n_high} High</b> open cases need review. "
        f"First in queue: <b>{html.escape(first_priority['ID'])}</b> · "
        f"{html.escape(str(first_priority['Type']))} · {html.escape(str(first_priority['Chainage']))}."
    )
    st.markdown(
        f"<div class='priority-banner'><span class='ic'>⚠️</span>"
        f"<span class='txt'>{priority_text} Use the Action centre to assign an owner and update the field workflow.</span></div>",
        unsafe_allow_html=True,
    )
elif n_open == 0:
    st.markdown(
        "<div class='priority-ok'>✅ No open cases in the current demonstration dataset.</div>",
        unsafe_allow_html=True,
    )

# ── operator KPIs: active items only; resolved items are excluded ────────────────
def kpi(n, label, color, icon, sub=None):
    sub_html = f"<div class='d'>{sub}</div>" if sub else ""
    return (
        f"<div class='kpi'><span class='ic'>{icon}</span>"
        f"<div class='n' style='color:{color}'>{n}</div>"
        f"<div class='l'>{label}</div>{sub_html}"
        f"<span style='position:absolute;left:0;top:0;bottom:0;width:3px;"
        f"background:{color}'></span></div>"
    )

st.markdown(
    "<div class='kpis'>"
    + kpi(n_open, "Active cases", KPI["total"], "📋", f"{n_total - n_open} resolved")
    + kpi(n_crit, "Critical open", KPI["Critical"], "🔴", SEV_SLA_SHORT["Critical"])
    + kpi(n_high, "High open", KPI["High"], "🟠", SEV_SLA_SHORT["High"])
    + kpi(n_unassigned, "Unassigned", "#f5b013", "👷", "Open cases without an owner")
    + kpi(n_change_open, "Imagery changes", KPI["change"], "🛰️", "Open candidate change cases")
    + "</div>",
    unsafe_allow_html=True,
)

def epoch_overlay(entry, opacity, z=3):
    return {
        "name": entry.get("date", "Imagery"),
        "png": entry["png"],
        "bounds": entry["bounds"],
        "opacity": opacity,
        "zindex": z,
    }


tab_map, tab_action, tab_cases, tab_overview = st.tabs(
    ["🗺  Corridor map", "⚠️  Action centre", "📋  Case register", "📊  Asset insights"]
)

# ── map tab ──────────────────────────────────────────────────────────────────────
with tab_map:
    st.markdown("#### Corridor monitoring view")
    st.markdown(
        f"<div class='section-lead'>{html.escape(PIPELINE_NAME)} · {corridor_range} · "
        f"{round(data['L']):,} m monitored segment · RoW margin {cfg['ROW_MARGIN_M']} m · "
        f"Monitoring band {cfg['DETECT_BUFFER_M']} m</div>",
        unsafe_allow_html=True,
    )
    if not show_google and not show_satellite_image:
        st.info("No basemap is selected. Detection overlays and the corridor geometry remain available.")
    map_center, map_zoom = center, 14
    if sel_ch != "(corridor overview)" and sel_ch in ch_pts:
        map_center, map_zoom = list(ch_pts[sel_ch]), jump_zoom

    overlays = []
    if sel_epoch != "(none)" and sel_epoch in epoch_lookup:
        overlays.append(epoch_overlay(epoch_lookup[sel_epoch], img_opacity, z=3))
    if show_change and man and man.get("change"):
        ch = man["change"][-1]
        overlays.append(
            {
                "name": f"Change {ch['from']}→{ch['to']}",
                "png": ch["png"],
                "bounds": ch["bounds"],
                "opacity": 0.8,
                "zindex": 4,
            }
        )

    # Keep the pipeline.py basemap argument for compatibility. Its default
    # base tile layer is removed immediately afterwards and replaced with the
    # layers selected by the two sidebar checkboxes.
    m = P.build_map(
        data,
        cfg=cfg,
        basemap="Google Satellite",
        visible_layers=chosen,
        severities=severities,
        overlays=overlays,
        change_geojson=change_fc,
        center=map_center,
        zoom=map_zoom,
        max_bounds=VIEW_BOUNDS,
    )

    add_selected_basemaps(m, show_google, show_satellite_image)

    # Hide the basemap attribution/source control shown on the map itself.
    m.options["attributionControl"] = False

    # Force a full remount whenever anything affecting the map's content changes.
    # This ensures the checkbox changes reliably add/remove basemap tile layers.
    map_key = "corridor_map_" + "_".join(
        str(v)
        for v in [
            show_google,
            show_satellite_image,
            sorted(chosen),
            sorted(severities),
            sel_epoch,
            show_change,
            sel_ch,
            jump_zoom,
        ]
    )
    st_folium(
        m,
        use_container_width=True,
        height=620,
        returned_objects=[],
        key=map_key,
    )
    st.caption(
        "Map layers show candidate locations within the configured monitoring corridor. "
        "Use the Action centre to review severity, assign a field owner and record the outcome."
    )


# ── inspection-report export ─────────────────────────────────────────────────────
def build_html_report(cfg, rows, operator, pipeline_name, corridor_range):
    sev_counts = {
        severity: sum(1 for row in rows if row["Severity"] == severity)
        for severity in ("Critical", "High", "Medium", "Low")
    }
    ordered_rows = sorted(rows, key=priority_sort_key)
    trs = "".join(
        f"<tr><td>{html.escape(str(row['ID']))}</td>"
        f"<td>{html.escape(str(row['Type']))}</td>"
        f"<td style='color:{P.SEV_COL.get(row['Severity'], '#555')};font-weight:700'>"
        f"{html.escape(str(row['Severity']))}</td>"
        f"<td>{row['Confidence']}%</td><td>{html.escape(str(row['Chainage']))}</td>"
        f"<td>{html.escape(str(row['SLA']))}</td>"
        f"<td>{html.escape(str(row['Status']))}</td>"
        f"<td>{html.escape(str(row.get('Assigned To', '')))}</td>"
        f"<td>{row.get('Lat', '')}, {row.get('Lon', '')}</td></tr>"
        for row in ordered_rows[:50]
    )
    generated = date.today().strftime("%d %b %Y")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>RoW Monitoring Tool — Demonstration Inspection Report</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;color:#17212c;max-width:1100px;margin:36px auto;padding:0 22px;}}
h1{{margin-bottom:4px;}} .sub{{color:#526273;margin-top:0;}}
.banner{{padding:10px 12px;background:#eef7fb;border-left:4px solid #168ec0;font-size:12px;}}
table{{border-collapse:collapse;width:100%;margin-top:16px;font-size:12px;}}
th,td{{border:1px solid #ccd5de;padding:7px 8px;text-align:left;}}
th{{background:#edf2f6;}}
.disclaimer{{color:#657586;font-size:11px;margin-top:24px;font-style:italic;line-height:1.5;}}
@media print{{body{{margin:0;}}}}
</style></head><body>
<h1>RoW Monitoring Tool — Pipeline Inspection Report</h1>
<p class="sub">{html.escape(operator)} · {html.escape(pipeline_name)} · {html.escape(corridor_range)}</p>
<p class="sub">Generated: {generated} · Current imagery pass: {html.escape(str(cfg.get('SCAN_DATE', '—')))} · Previous pass: {html.escape(str(cfg.get('PREV_SCAN', '—')))}</p>
<div class="banner"><b>Demonstration report.</b> Records represent candidate detections for workflow evaluation and are not confirmed encroachments or live operational alerts.</div>
<h3>Case summary</h3>
<p>Active cases: {sum(1 for row in rows if row['Status'] != 'Resolved')} &nbsp;|&nbsp; Total candidates: {len(rows)} &nbsp;|&nbsp;
Critical: {sev_counts['Critical']} &nbsp; High: {sev_counts['High']} &nbsp; Medium: {sev_counts['Medium']} &nbsp; Low: {sev_counts['Low']}</p>
<p>RoW margin: {cfg['ROW_MARGIN_M']} m &nbsp; Monitoring band: {cfg['DETECT_BUFFER_M']} m</p>
<h3>Case register (priority order; first 50)</h3>
<table><tr><th>ID</th><th>Type</th><th>Severity</th><th>Confidence</th><th>Chainage / extent</th><th>SLA</th><th>Status</th><th>Assigned to</th><th>Coordinates</th></tr>{trs}</table>
<p class="disclaimer">Satellite-derived detections are indicative candidates. Field verification, review against the approved pipeline alignment and asset register, and compliance with the operator's operating procedures are required before any operational decision. Confidential — for internal evaluation only.</p>
</body></html>"""


def render_case_detail(case_id, detail_context="case", allow_workflow=True):
    """Render one candidate case, including imagery-change records and workflow controls."""
    row_match = next((item for item in all_rows if item["ID"] == case_id), None)
    if row_match is None:
        st.info("Select a case to view its details.")
        return

    row = dict(row_match)
    row["Status"] = st.session_state.case_status.get(case_id, row.get("Status", "New"))
    row["Assigned To"] = st.session_state.case_assignee.get(case_id, row.get("Assigned To", ""))
    raw_case = case_lookup.get(case_id)
    case_type = raw_case["type"] if raw_case else row["Type"]
    category = categorize(str(case_type))
    icon = CATEGORY_ICON.get(category, "🛰️" if row["Source"] == "Imagery CD" else "📍")
    action = CATEGORY_ACTION.get(
        category,
        "Compare the candidate against the approved pipeline alignment and asset register; arrange field verification and record the outcome.",
    )
    severity = row["Severity"]
    sla_full = SEV_SLA.get(severity, "Review under the operator's case-handling procedure")
    extra = []

    if raw_case:
        if category == "vegetation":
            veg_sorted = sorted(
                [v for v in data["veg"] if v["level"] >= 2],
                key=lambda v: (-v["level"], v["dist_m"]),
            )[:4]
            try:
                idx = int(str(raw_case["id"]).split("-")[1]) - 1
            except (IndexError, ValueError):
                idx = -1
            det = veg_sorted[idx] if 0 <= idx < len(veg_sorted) else {}
            extra = [
                ("NDVI signature", det.get("ndvi")),
                ("Encroachment area", f"{det.get('area_m2')} m²" if det.get("area_m2") else None),
                ("Distance to pipeline", f"{det.get('dist_m')} m" if det.get("dist_m") is not None else None),
            ]
        elif category == "water":
            det = next((f for f in data["floods"] if f["id"] == case_id), {})
            extra = [
                ("Surface extent", f"{det.get('area_m2')} m²" if det.get("area_m2") else None),
                ("SAR VV change", f"{det.get('vv_b')} → {det.get('vv_a')} dB" if det.get("vv_b") is not None else None),
                ("NDWI", f"+{det.get('ndwi')}" if det.get("ndwi") is not None else None),
                ("% inside RoW", f"{det.get('pct_rou')}%" if det.get("pct_rou") is not None else None),
            ]
        elif category == "excavation":
            det = next((x for x in data["excs"] if x["id"] == case_id), {})
            extra = [
                ("Footprint area", f"{det.get('area_m2')} m²" if det.get("area_m2") else None),
                ("Estimated depth", f"{det.get('depth_m')} m" if det.get("depth_m") is not None else None),
                ("Estimated volume", f"{det.get('vol_m3'):,} m³" if det.get("vol_m3") else None),
                ("% inside RoW", f"{det.get('pct_rou')}%" if det.get("pct_rou") is not None else None),
            ]
        elif category == "road":
            det = data["road"]
            extra = [
                ("Length", f"{det.get('len')} m" if det.get("len") is not None else None),
                ("Distance to pipeline", f"{det.get('dist')} m" if det.get("dist") is not None else None),
                ("Crosses corridor", "Yes" if det.get("cross") else "No"),
            ]
        elif category == "structure":
            det = next((item for item in data["structures"] if item["id"] == case_id), {})
            extra = [
                ("Structure type", det.get("type")),
                ("Footprint area", f"{det.get('area_m2')} m²" if det.get("area_m2") else None),
                ("Within RoW", "Yes" if det.get("in_rou") else "No"),
                ("Within monitoring band", "Yes" if det.get("within") else "No"),
            ]
    else:
        feature = next(
            (feature for feature in change_fc.get("features", [])
             if feature.get("properties", {}).get("id") == case_id),
            None,
        )
        if feature:
            props = feature["properties"]
            extra = [
                ("Comparison", f"{props.get('from', '—')} → {props.get('to', '—')}"),
                ("Changed surface", f"{props.get('area_m2', '—')} m²"),
                ("Review source", "Historical imagery comparison"),
            ]
        action = (
            "Review the before/after imagery pair, compare the changed footprint with the approved RoW and asset register, "
            "then request field verification if the change is relevant to pipeline integrity or access."
        )

    lat = row.get("Lat")
    lon = row.get("Lon")
    coord_text = f"{lat:.5f}, {lon:.5f}" if lat is not None and lon is not None else "Not available"
    rows_html = "".join(
        f"<div class='detail-row'><span>{html.escape(str(key))}</span><span>{html.escape(str(value))}</span></div>"
        for key, value in extra if value is not None
    )
    sev_color = P.SEV_COL.get(severity, "#64748b")
    st.markdown(
        f"<div class='detail-card'>"
        f"<div class='dh'><span style='font-size:20px'>{icon}</span>"
        f"<span class='id'>{html.escape(str(case_id))}</span>"
        f"<span class='sev-chip' style='background:{sev_color}'>{html.escape(str(severity))}</span></div>"
        f"<div class='detail-row'><span>Detection type</span><span>{html.escape(str(case_type))}</span></div>"
        f"<div class='detail-row'><span>Chainage / extent</span><span>{html.escape(str(row.get('Chainage', '—')))}</span></div>"
        f"<div class='detail-row'><span>Candidate confidence</span><span>{row.get('Confidence', '—')}%</span></div>"
        f"<div class='detail-row'><span>Coordinates</span><span>{coord_text}</span></div>"
        f"<div class='detail-row'><span>Detection source</span><span>{html.escape(str(row.get('Source', '—')))}</span></div>"
        f"{rows_html}"
        f"<div class='action-box'><b>Suggested review action</b><br>{html.escape(action)}<br>"
        f"<b>Response target:</b> {html.escape(sla_full)}</div></div>",
        unsafe_allow_html=True,
    )

    action_cols = st.columns([1, 1, 1.4])
    if lat is not None and lon is not None:
        maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        with action_cols[0]:
            st.link_button("📍 Open location", maps_url, key=f"case_location_{detail_context}_{case_id}", use_container_width=True)
    with action_cols[1]:
        st.download_button(
            "⬇ Case record CSV",
            pd.DataFrame([row]).to_csv(index=False).encode("utf-8"),
            file_name=f"{case_id}_case_record.csv",
            mime="text/csv",
            key=f"case_record_download_{detail_context}_{case_id}",
            use_container_width=True,
        )
    with action_cols[2]:
        st.caption(
            "Update the review status and owner below."
            if allow_workflow
            else "To change status or owner, use the Action centre."
        )

    if allow_workflow:
        st.markdown("**Field workflow**")
        status_key = f"workflow_status_{detail_context}_{case_id}"
        assignee_key = f"workflow_assignee_{detail_context}_{case_id}"
        if status_key not in st.session_state:
            current_status = st.session_state.case_status.get(case_id, row["Status"])
            st.session_state[status_key] = current_status if current_status in STATUS_OPTIONS else "New"
        if assignee_key not in st.session_state:
            st.session_state[assignee_key] = st.session_state.case_assignee.get(case_id, "")
        wf1, wf2, wf3 = st.columns([1.2, 1.2, 0.8])
        with wf1:
            chosen_status = st.selectbox("Status", STATUS_OPTIONS, key=status_key)
        with wf2:
            chosen_assignee = st.text_input("Assigned to", key=assignee_key, placeholder="Field team / owner")
        with wf3:
            st.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)
            if st.button("Save update", key=f"save_workflow_{detail_context}_{case_id}", use_container_width=True):
                st.session_state.case_status[case_id] = chosen_status
                st.session_state.case_assignee[case_id] = chosen_assignee.strip()
                st.rerun()
        st.caption("Workflow edits in this demo are held in the current browser session. Connect a shared database or work-order API for multi-user, persistent operations.")


# ── action centre ────────────────────────────────────────────────────────────────
with tab_action:
    st.markdown("#### Action centre")
    st.markdown(
        "<div class='section-lead'>A prioritised worklist for review, assignment and field verification. "
        "Critical and High items appear first.</div>",
        unsafe_allow_html=True,
    )
    queue_rows = sorted([row for row in open_rows if row["Severity"] in severities], key=priority_sort_key)
    q1, q2, q3 = st.columns(3)
    q1.metric("Open work items", len(queue_rows))
    q2.metric("Critical / High", sum(1 for row in queue_rows if row["Severity"] in ("Critical", "High")))
    q3.metric("Awaiting assignment", sum(1 for row in queue_rows if not str(row.get("Assigned To", "")).strip()))
    if queue_rows:
        queue_df = pd.DataFrame(queue_rows)[
            ["ID", "Type", "Severity", "Confidence", "Chainage", "SLA", "Status", "Assigned To"]
        ]
        st.dataframe(
            queue_df,
            width="stretch",
            hide_index=True,
            column_config={
                "Confidence": st.column_config.ProgressColumn("Confidence", format="%d%%", min_value=0, max_value=100),
                "Severity": st.column_config.TextColumn("Priority"),
            },
        )
        st.markdown("**Review a work item**")
        queue_ids = [row["ID"] for row in queue_rows]
        selected_queue_id = st.selectbox("Select candidate", queue_ids, key="action_centre_case_select", label_visibility="collapsed")
        render_case_detail(selected_queue_id, "action")
    else:
        st.success("No open work items match the current severity filters.")
        st.caption("Resolved items remain available in the Case register when the Resolved status filter is enabled.")


# ── case register ────────────────────────────────────────────────────────────────
with tab_cases:
    st.markdown("#### Case register")
    st.markdown(
        "<div class='section-lead'>Search and filter candidate detections, inspect case details and export a structured register for review or hand-off. Update owners and statuses in the Action centre.</div>",
        unsafe_allow_html=True,
    )
    filter_cols = st.columns([2.0, 1.25, 1.25])
    with filter_cols[0]:
        search = st.text_input("Search cases", placeholder="Search ID, type, chainage or assignee…", label_visibility="collapsed")
    with filter_cols[1]:
        register_statuses = st.multiselect("Workflow status", STATUS_OPTIONS, default=STATUS_OPTIONS, key="register_status_filter")
    with filter_cols[2]:
        source_filter = st.selectbox("Detection source", ["All sources", "Live scan", "Imagery CD"], key="register_source_filter")

    rows = [
        dict(row, Status=st.session_state.case_status.get(row["ID"], row["Status"]),
             **{"Assigned To": st.session_state.case_assignee.get(row["ID"], row.get("Assigned To", ""))})
        for row in all_rows
        if row["Severity"] in severities
        and st.session_state.case_status.get(row["ID"], row["Status"]) in register_statuses
        and (source_filter == "All sources" or row["Source"] == source_filter)
    ]
    if search:
        search_term = search.lower().strip()
        rows = [
            row for row in rows
            if any(search_term in str(row.get(field, "")).lower()
                   for field in ("ID", "Type", "Chainage", "Status", "Assigned To"))
        ]
    rows = sorted(rows, key=priority_sort_key)
    st.caption(f"Showing {len(rows)} of {n_total} candidate records · {n_open} currently active · {n_total - n_open} resolved")

    if rows:
        df = pd.DataFrame(rows)
        display_cols = ["ID", "Type", "Severity", "Confidence", "Chainage", "SLA", "Status", "Assigned To", "Source"]
        st.dataframe(
            df[display_cols],
            width="stretch",
            hide_index=True,
            column_config={
                "Confidence": st.column_config.ProgressColumn("Confidence", format="%d%%", min_value=0, max_value=100),
                "Severity": st.column_config.TextColumn("Priority"),
            },
        )
        export_df = df[[*display_cols, "Lat", "Lon"]]
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "⬇ Download filtered register (CSV)",
                export_df.to_csv(index=False).encode("utf-8"),
                file_name="row_sentinel_case_register.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with dl2:
            html_report = build_html_report(cfg, rows, OPERATOR, PIPELINE_NAME, corridor_range)
            st.download_button(
                "📄 Download inspection report (HTML)",
                html_report.encode("utf-8"),
                file_name="row_sentinel_inspection_report.html",
                mime="text/html",
                help="Open in a browser and use Print → Save as PDF.",
                use_container_width=True,
            )

        st.divider()
        st.markdown("**Case detail**")
        detail_ids = [row["ID"] for row in rows]
        selected_detail_id = st.selectbox("Select a case for full detail", detail_ids, key="register_detail_case_select", label_visibility="collapsed")
        render_case_detail(selected_detail_id, "register", allow_workflow=False)
    else:
        st.info("No cases match the selected filters. Clear the search or widen the workflow/source filters.")


# ── asset insights + operating model ─────────────────────────────────────────────
with tab_overview:
    st.markdown("#### Asset insights")
    st.markdown(
        "<div class='section-lead'>A management view of the current corridor review set and the operational workflow around it.</div>",
        unsafe_allow_html=True,
    )
    status_counts = pd.Series([st.session_state.case_status.get(row["ID"], row["Status"]) for row in all_rows]).value_counts()
    resolved_n = int(status_counts.get("Resolved", 0))
    type_counts = pd.Series([row["Type"] for row in all_rows]).value_counts()
    insight_cols = st.columns(4)
    insight_cols[0].metric("Monitored segment", f"{round(data['L']):,} m")
    insight_cols[1].metric("Candidate records", n_total)
    insight_cols[2].metric("Resolved in session", resolved_n)
    insight_cols[3].metric("Average confidence", f"{avg_conf}%")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Open cases by severity**")
        st.bar_chart(
            pd.DataFrame({"Open cases": [n_crit, n_high, n_med, n_low]}, index=["Critical", "High", "Medium", "Low"]),
            color="#e5484d",
            height=245,
        )
    with col2:
        st.markdown("**Workflow status**")
        if not status_counts.empty:
            st.bar_chart(status_counts, color="#38bdf8", height=245)
        else:
            st.caption("No workflow records to summarize.")

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**Candidate detections by type**")
        if not type_counts.empty:
            st.bar_chart(type_counts, color="#a855f7", height=230)
        else:
            st.caption("No candidate detections available.")
    with col4:
        st.markdown("**Imagery change candidates by comparison**")
        if man and man.get("change"):
            change_counts = pd.DataFrame(
                {"Candidate changes": [item["n"] for item in man["change"]]},
                index=[f"{item['from']} → {item['to']}" for item in man["change"]],
            )
            st.bar_chart(change_counts, color="#f0883e", height=230)
        else:
            st.caption("No historical imagery comparison is available in the current manifest.")

    st.divider()
    st.markdown("**How the RoW Monitoring Tool workflow fits an operator's review process**")
    st.markdown(
        "<div class='workflow-steps'>"
        "<div class='workflow-step'><div class='num'>01 · DETECT</div><div class='name'>Compare imagery</div><div class='desc'>Review repeat satellite acquisitions and flag candidate surface changes along the monitored corridor.</div></div>"
        "<div class='workflow-step'><div class='num'>02 · PRIORITISE</div><div class='name'>Triage by risk</div><div class='desc'>Use severity, confidence, proximity and response targets to focus attention on the most urgent items.</div></div>"
        "<div class='workflow-step'><div class='num'>03 · VERIFY</div><div class='name'>Assign field action</div><div class='desc'>Route the case to a field owner, inspect the location and attach evidence in the operational system.</div></div>"
        "<div class='workflow-step'><div class='num'>04 · CLOSE</div><div class='name'>Record the outcome</div><div class='desc'>Update status, retain the review trail and export a structured case register for follow-up.</div></div>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("**Potential production integration points**")
    st.caption("These are recommended integration points, not connected services in this demonstration build.")
    st.markdown(
        "<div class='integration-grid'>"
        "<div class='integration-item'><b>Pipeline GIS and chainage register</b><span>Load the operator-approved centreline, RoW easement, valve locations, crossings and asset IDs for accurate chainage-based review.</span></div>"
        "<div class='integration-item'><b>Field mobility / work orders</b><span>Push approved cases to the operator's work-order or field-inspection process and receive verification notes, photos and closure status.</span></div>"
        "<div class='integration-item'><b>Enterprise data and alerts</b><span>Persist case history in a shared database and connect role-based access, audit logs, email/SMS alerts and reporting APIs.</span></div>"
        "</div>",
        unsafe_allow_html=True,
    )

# ── footer ───────────────────────────────────────────────────────────────────────
st.markdown(
    f"<div class='app-footer'>"
    f"<span>{BRAND} — {ORG} · Satellite imagery review and RoW case workflow</span>"
    f"<span>Demonstration build · Candidate detections require field verification</span></div>",
    unsafe_allow_html=True,
)
