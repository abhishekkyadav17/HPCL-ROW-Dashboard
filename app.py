import json
import os

import yaml
from yaml.loader import SafeLoader

import folium
import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth
from streamlit_folium import st_folium

import pipeline as P

# ── brand / asset configuration — edit these for a new client or pipeline ───────
BRAND = "RoW Sentinel"
SUBTITLE = "Satellite-based pipeline right-of-way monitoring"
ORG = "BioSky Space Innovations"
OPERATOR = "HPCL"
PRODUCT_LINE = "Petroleum product pipeline"
PIPELINE_NAME = "Jaipur Segment"
SCAN_CADENCE_DAYS = 12
MANIFEST = "data/derived/layers_manifest.json"

KPI = {"total": "#38bdf8", "Critical": "#e5484d", "High": "#f0883e",
       "Medium": "#f5b013", "change": "#a855f7"}

STATUS_OPTIONS = ["New", "Acknowledged", "Field Verification", "Resolved",
                  "Under review", "Advisory", "Field dispatch"]

# ── domain content kept local to app.py (no pipeline.py dependency) ─────────────
SEV_SLA = {
    "Critical": "Immediate — field verification within 24 h",
    "High": "Priority — field verification within 72 h",
    "Medium": "Scheduled — next routine patrol (≤7 days)",
    "Low": "Routine — monitor at next scheduled pass",
}
SEV_SLA_SHORT = {"Critical": "≤ 24h", "High": "≤ 72h", "Medium": "≤ 7d", "Low": "Routine"}

CATEGORY_ICON = {"vegetation": "🌿", "water": "💧", "excavation": "🚧",
                 "road": "🛣️", "structure": "🏗️"}
CATEGORY_ACTION = {
    "vegetation": "Dispatch vegetation clearance crew; confirm clearance meets "
                  "minimum RoW easement spacing.",
    "water": "Verify local drainage pattern and assess erosion/scour risk to "
             "buried pipeline coating and cathodic protection.",
    "excavation": "Possible third-party interference. Contact landowner and "
                  "local authority per encroachment SOP; confirm no mechanical "
                  "contact with the pipeline before any further digging.",
    "road": "Survey crew to confirm an unauthorized crossing; check depth of "
            "cover for mechanical-damage risk from vehicle loading.",
    "structure": "Cross-check against the RoW easement and approved-structure "
                 "register; initiate a removal notice if unauthorized.",
}

st.set_page_config(page_title=f"{BRAND} — {ORG}", page_icon="🛰️",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{--ink:#0a0f16;--panel:#111a24;--surface:#17212c;--surface2:#1c2733;
      --border:#25323f;--muted:#8fa3b8;--text:#cfdae6;--strong:#f3f7fb;
      --brand:#38bdf8;--good:#3ecf8e;}
html,body,[class*="css"],.stApp{font-family:'Inter',system-ui,sans-serif;}
.stApp{background:
  radial-gradient(1200px 500px at 10% -10%, rgba(56,189,248,.05), transparent),
  var(--ink);}
[data-testid="stToolbar"]{visibility:visible;}
footer{visibility:hidden;}
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
</style>
""", unsafe_allow_html=True)


# ── auth ────────────────────────────────────────────────────────────────────────
def _plain(obj):
    return {k: _plain(v) for k, v in obj.items()} if hasattr(obj, "items") else obj

@st.cache_resource(show_spinner=False)
def load_auth_config(path="config.yaml"):
    try:
        if "credentials" in st.secrets:
            return {"credentials": _plain(st.secrets["credentials"]),
                    "cookie": _plain(st.secrets["cookie"])}
    except Exception:
        pass
    with open(path) as f:
        return yaml.load(f, Loader=SafeLoader)

config = load_auth_config()
authenticator = stauth.Authenticate(
    config["credentials"], config["cookie"]["name"],
    config["cookie"]["key"], config["cookie"]["expiry_days"])

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
                f"</div>", unsafe_allow_html=True)
            authenticator.login(location="main",
                                fields={"Form name": "Sign in", "Login": "Sign in"})
            if st.session_state.get("authentication_status") is False:
                st.error("Incorrect username or password.")
            st.markdown("<div class='notice'>Authorized personnel only. All activity "
                        "on this console is logged.</div>", unsafe_allow_html=True)
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
    cfg = {**P.DEFAULT_CFG, "ROW_MARGIN_M": row_margin,
           "DETECT_BUFFER_M": detect_buffer}
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
    return ("Critical" if area > 8000 else "High" if area > 3000
            else "Medium" if area > 800 else "Low")


def categorize(type_str):
    """Derive a detection category from the case's free-text type label --
    done here instead of in pipeline.py so this file needs no companion change."""
    t = type_str.lower()
    if "vegetation" in t: return "vegetation"
    if "water" in t or "flood" in t: return "water"
    if "excavation" in t: return "excavation"
    if "road" in t: return "road"
    if "structure" in t: return "structure"
    return "other"


# ── sidebar ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"#### 🛰️ {BRAND}")
    st.caption(f"{OPERATOR} · {PIPELINE_NAME}")
    st.divider()

    st.markdown("**Imagery blend**")
    st.caption("Google Satellite (below) · Satellite Image (above)")
    blend = st.slider("Blend", 0, 100, 0, 5, label_visibility="collapsed",
                      help="0 = Google Satellite only · 100 = Satellite Image only")
    basemap = "Google Satellite"  # fixed base layer; the slider above adds the second

    layer_labels = {k: lbl for k, lbl in P.LAYER_DEFS}
    chosen = st.multiselect("Detection layers", options=P.ALL_LAYERS,
                            default=P.ALL_LAYERS, format_func=lambda k: layer_labels[k])
    severities = st.multiselect("Severity filter (cases)",
                                ["Critical", "High", "Medium", "Low"],
                                default=["Critical", "High", "Medium", "Low"])

    st.markdown("**Imagery**")
    epoch_opts, epoch_lookup = [], {}
    if man:
        for e in man.get("epochs", []):
            lbl = f"GEP {e['date']}"
            epoch_opts.append(lbl); epoch_lookup[lbl] = e
        if man.get("cartosat"):
            epoch_opts.append("Cartosat-2S"); epoch_lookup["Cartosat-2S"] = man["cartosat"]
    if epoch_opts:
        sel_epoch = st.selectbox("Show imagery epoch", ["(none)"] + epoch_opts,
                                 index=len(epoch_opts))
        img_opacity = st.slider("Imagery opacity", 0.0, 1.0, 0.85, 0.05)
        show_change = st.toggle("Show detected change layer", value=bool(man.get("change")))
    else:
        sel_epoch, img_opacity, show_change = "(none)", 0.85, False
        st.caption("No imagery yet — run `python prep.py` with your Cartosat + GEP files.")

    with st.expander("Corridor geometry"):
        row_margin = st.slider("RoW margin (m)", 5, 60, P.DEFAULT_CFG["ROW_MARGIN_M"], 5)
        detect_buffer = st.slider("Monitoring band (m)", 20, 150,
                                  P.DEFAULT_CFG["DETECT_BUFFER_M"], 10)

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
        "RoW corridor</div>", unsafe_allow_html=True)

    st.divider()
    st.caption(f"Signed in as **{st.session_state.get('name', 'user')}**")
    authenticator.logout(button_name="Log out", location="sidebar", key="logout_btn")
    st.caption(f"{BRAND} v1.3 · build 2026.10.31")

data = get_data(cache_key, row_margin, detect_buffer, lines)
cfg = data["cfg"]; cnt = data["counts"]
case_lookup = {c["id"]: c for c in data["cases"]}

# ── sidebar: chainage navigator (uses data["chainage_ticks"], already in pipeline.py) ──
with st.sidebar:
    with st.expander("Chainage navigator"):
        ch_pts = {f"CH {lbl}": pt for pt, lbl in data["chainage_ticks"]}
        ch_opts = ["(corridor overview)"] + list(ch_pts.keys())
        sel_ch = st.selectbox("Jump to chainage", ch_opts, index=0)
        jump_zoom = st.slider("Jump zoom level", 15, 19, 17) if sel_ch != "(corridor overview)" else 14

# ── per-session editable workflow state (status / assignee) ────────────────────
if "case_status" not in st.session_state:
    st.session_state.case_status = {c["id"]: c["status"] for c in data["cases"]}
if "case_assignee" not in st.session_state:
    st.session_state.case_assignee = {c["id"]: "" for c in data["cases"]}
for c in data["cases"]:
    st.session_state.case_status.setdefault(c["id"], c["status"])
    st.session_state.case_assignee.setdefault(c["id"], "")


# ── merged case register (synthetic detections + imagery change) ─────────────────
det_rows = [{"ID": c["id"], "Type": c["type"],
             "Severity": c["sev"], "Confidence": c["conf"], "Chainage": f"CH {c['ch']}",
             "SLA": SEV_SLA_SHORT.get(c["sev"], ""),
             "Status": st.session_state.case_status.get(c["id"], c["status"]),
             "Assigned To": st.session_state.case_assignee.get(c["id"], ""),
             "Source": "Live scan",
             "Lat": round(c["latlon"][0], 5), "Lon": round(c["latlon"][1], 5)}
            for c in data["cases"]]
chg_rows = []
for f in change_fc["features"]:
    p = f["properties"]; sev = change_sev(p["area_m2"])
    chg_rows.append({"ID": p["id"], "Type": f"Change {p['from']}→{p['to']}",
                     "Severity": sev, "Confidence": p["conf"],
                     "Chainage": f"{p['area_m2']} m²", "SLA": SEV_SLA_SHORT.get(sev, ""),
                     "Status": st.session_state.case_status.get(p["id"], "New"),
                     "Assigned To": st.session_state.case_assignee.get(p["id"], ""),
                     "Source": "Imagery CD", "Lat": p["lat"], "Lon": p["lon"]})
all_rows = det_rows + chg_rows
n_change = len(chg_rows)
n_total = len(all_rows)
n_crit = sum(1 for r in all_rows if r["Severity"] == "Critical")
n_high = sum(1 for r in all_rows if r["Severity"] == "High")
n_med = sum(1 for r in all_rows if r["Severity"] == "Medium")
avg_conf = round(sum(r["Confidence"] for r in all_rows) / n_total) if n_total else 0

# ── top bar ──────────────────────────────────────────────────────────────────────
corridor_range = f"CH 0+000 – {data['chainage_str'](data['L'])}"
st.markdown(
    f"<div class='topbar'>"
    f"<div class='tb-left'><span class='mark'>🛰️ {BRAND}</span>"
    f"<span class='sub'>{SUBTITLE}</span></div>"
    f"<div class='tb-mid'>"
    f"<div class='tb-field'><span class='k'>Operator</span><span class='v'>{OPERATOR}</span></div>"
    f"<div class='tb-field'><span class='k'>Asset</span><span class='v'>{PIPELINE_NAME}</span></div>"
    f"<div class='tb-field'><span class='k'>Product</span><span class='v'>{PRODUCT_LINE}</span></div>"
    f"<div class='tb-field'><span class='k'>Segment</span><span class='v'>{corridor_range}</span></div>"
    f"<div class='tb-field'><span class='k'>Last pass</span><span class='v'>{cfg['SCAN_DATE']}</span></div>"
    f"<div class='tb-field'><span class='k'>Prior pass</span><span class='v'>{cfg['PREV_SCAN']}</span></div>"
    f"<div class='tb-field'><span class='k'>Cadence</span><span class='v'>every {SCAN_CADENCE_DAYS} days</span></div>"
    f"</div>"
    f"<div class='tb-right'>"
    f"<span class='live-pill'><span class='live-dot'></span>MONITORING ACTIVE</span>"
    f"<span class='conf-badge'>Avg. detection confidence <b>{avg_conf}%</b></span>"
    f"</div></div>",
    unsafe_allow_html=True)

# ── priority banner ──────────────────────────────────────────────────────────────
n_open_crit_high = sum(1 for r in all_rows
                       if r["Severity"] in ("Critical", "High") and r["Status"] == "New")
if n_crit > 0:
    top_crit = next((c for c in data["cases"] if c["sev"] == "Critical"), None)
    tc_txt = (f" Highest priority: <b>{top_crit['id']}</b> at {top_crit['ch']} km-post "
              f"({top_crit['type']})." if top_crit else "")
    st.markdown(
        f"<div class='priority-banner'><span class='ic'>⚠️</span>"
        f"<span class='txt'><b>{n_crit} Critical case(s)</b> require field verification "
        f"within 24 hours per RoW encroachment SOP.{tc_txt}</span></div>",
        unsafe_allow_html=True)
elif n_open_crit_high == 0 and n_total > 0:
    st.markdown(
        "<div class='priority-ok'>✅ No unactioned Critical or High-severity cases — "
        "corridor within normal monitoring parameters.</div>",
        unsafe_allow_html=True)

# ── KPI cards ────────────────────────────────────────────────────────────────────
def kpi(n, label, color, icon, sub=None):
    sub_html = f"<div class='d'>{sub}</div>" if sub else ""
    return (f"<div class='kpi'><span class='ic'>{icon}</span>"
            f"<div class='n' style='color:{color}'>{n}</div>"
            f"<div class='l'>{label}</div>{sub_html}"
            f"<span style='position:absolute;left:0;top:0;bottom:0;width:3px;"
            f"background:{color}'></span></div>")

st.markdown("<div class='kpis'>"
            + kpi(n_total, "Total open cases", KPI["total"], "📋",
                  f"{cnt['n_new']} new since prior pass")
            + kpi(n_crit, "Critical", KPI["Critical"], "🔴", SEV_SLA_SHORT["Critical"])
            + kpi(n_high, "High", KPI["High"], "🟠", SEV_SLA_SHORT["High"])
            + kpi(n_med, "Medium", KPI["Medium"], "🟡", SEV_SLA_SHORT["Medium"])
            + kpi(n_change, "Imagery change", KPI["change"], "🛰️", "vs. historical baseline")
            + "</div>", unsafe_allow_html=True)


def epoch_overlay(entry, opacity, z=3):
    return {"name": entry.get("date", "Imagery"), "png": entry["png"],
            "bounds": entry["bounds"], "opacity": opacity, "zindex": z}


tab_map, tab_cases, tab_overview = st.tabs(
    ["🗺  Corridor map", "📋  Case register", "📊  Overview"])

# ── map tab ──────────────────────────────────────────────────────────────────────
with tab_map:
    map_center, map_zoom = center, 14
    if sel_ch != "(corridor overview)" and sel_ch in ch_pts:
        map_center, map_zoom = list(ch_pts[sel_ch]), jump_zoom

    overlays = []
    if sel_epoch != "(none)" and sel_epoch in epoch_lookup:
        overlays.append(epoch_overlay(epoch_lookup[sel_epoch], img_opacity, z=3))
    if show_change and man and man.get("change"):
        ch = man["change"][-1]
        overlays.append({"name": f"Change {ch['from']}→{ch['to']}", "png": ch["png"],
                         "bounds": ch["bounds"], "opacity": 0.8, "zindex": 4})
    m = P.build_map(data, cfg=cfg, basemap=basemap, visible_layers=chosen,
                    severities=severities, overlays=overlays,
                    change_geojson=change_fc, center=map_center, zoom=map_zoom,
                    max_bounds=VIEW_BOUNDS)

    # Second basemap layered on top with adjustable opacity -- the "Imagery
    # blend" slider. Done here (not in pipeline.py) by adding directly to the
    # Map object build_map() already returned; overlay=True, control=False
    # keeps it out of any layer-control UI since there isn't one on this map.
    if blend > 0:
        ov_url, ov_attr, ov_subs, ov_mx = P.BASEMAPS["Satellite Image"]
        folium.TileLayer(ov_url, attr=ov_attr, name="Satellite Image (blend)",
                         subdomains=ov_subs or "abc", max_zoom=ov_mx,
                         opacity=blend / 100.0, overlay=True, control=False).add_to(m)

    # Hide the basemap attribution/source control shown on the map itself.
    m.options["attributionControl"] = False

    # Force a full remount whenever anything affecting the map's content changes.
    # st_folium tries to update an already-mounted map in place for some prop
    # changes (zoom/center), but doesn't reliably pick up layers added/removed
    # between reruns (confirmed: the Imagery-blend overlay above didn't appear
    # on the live map without this). A key tied to everything relevant forces
    # a clean remount instead of relying on that in-place update path.
    map_key = "corridor_map_" + "_".join(str(v) for v in [
        blend, sorted(chosen), sorted(severities), sel_epoch, show_change,
        sel_ch, jump_zoom,
    ])
    st_folium(m, use_container_width=True, height=620, returned_objects=[],
             key=map_key)


# ── inspection-report export (plain HTML -- no new pip dependency) ──────────────
def build_html_report(cfg, rows, operator, pipeline_name, corridor_range):
    sev_counts = {s: sum(1 for r in rows if r["Severity"] == s)
                 for s in ("Critical", "High", "Medium", "Low")}
    trs = "".join(
        f"<tr><td>{r['ID']}</td><td>{r['Type']}</td>"
        f"<td style='color:{P.SEV_COL.get(r['Severity'],'#555')};font-weight:700'>{r['Severity']}</td>"
        f"<td>{r['Confidence']}%</td><td>{r['Chainage']}</td><td>{r['SLA']}</td>"
        f"<td>{r['Status']}</td></tr>"
        for r in rows[:30])
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>RoW Sentinel Inspection Report</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;color:#111;max-width:900px;margin:40px auto;padding:0 20px;}}
h1{{margin-bottom:4px;}} .sub{{color:#555;margin-top:0;}}
table{{border-collapse:collapse;width:100%;margin-top:16px;font-size:13px;}}
th,td{{border:1px solid #ccc;padding:6px 8px;text-align:left;}}
th{{background:#f0f0f0;}}
.disclaimer{{color:#777;font-size:11px;margin-top:24px;font-style:italic;}}
@media print{{body{{margin:0;}}}}
</style></head><body>
<h1>RoW Sentinel — Pipeline Inspection Report</h1>
<p class="sub">{operator} · {pipeline_name} · {corridor_range}</p>
<p class="sub">Satellite pass: {cfg['SCAN_DATE']} (previous: {cfg['PREV_SCAN']})</p>
<h3>Summary</h3>
<p>Total open cases: {len(rows)} &nbsp;|&nbsp;
Critical: {sev_counts['Critical']} &nbsp; High: {sev_counts['High']} &nbsp;
Medium: {sev_counts['Medium']} &nbsp; Low: {sev_counts['Low']}</p>
<p>RoW margin: {cfg['ROW_MARGIN_M']} m &nbsp; Monitoring band: {cfg['DETECT_BUFFER_M']} m</p>
<h3>Case Register (top 30 by priority)</h3>
<table><tr><th>ID</th><th>Type</th><th>Severity</th><th>Confidence</th>
<th>Chainage</th><th>SLA</th><th>Status</th></tr>{trs}</table>
<p class="disclaimer">Generated by RoW Sentinel. Satellite-derived detections are
indicative and require field verification before any operational decision.
Confidential — for internal evaluation only. Use your browser's Print →
Save as PDF to export this report as a PDF.</p>
</body></html>"""


# ── case register ────────────────────────────────────────────────────────────────
with tab_cases:
    top_row = st.columns([2.2, 1])
    with top_row[0]:
        search = st.text_input("Search cases", placeholder="Search by ID, type, or chainage…",
                               label_visibility="collapsed")
    with top_row[1]:
        st.caption(f"{n_total} total · {n_change} from imagery change detection · "
                   f"avg. confidence {avg_conf}%")

    rows = [r for r in all_rows if r["Severity"] in severities]
    if search:
        s = search.lower()
        rows = [r for r in rows if s in r["ID"].lower() or s in r["Type"].lower()
               or s in r["Chainage"].lower()]

    df = pd.DataFrame(rows)
    if not df.empty:
        display_cols = ["ID", "Type", "Severity", "Confidence", "Chainage", "SLA",
                        "Status", "Assigned To", "Source"]
        edited = st.data_editor(
            df[display_cols], width="stretch", hide_index=True, key="case_editor",
            column_config={
                "Confidence": st.column_config.ProgressColumn(
                    "Confidence", format="%d%%", min_value=0, max_value=100),
                "Status": st.column_config.SelectboxColumn(
                    "Status", options=STATUS_OPTIONS, required=True),
                "Assigned To": st.column_config.TextColumn("Assigned To", width="small"),
            },
            disabled=["ID", "Type", "Severity", "Confidence", "Chainage", "SLA", "Source"],
        )
        for _, row in edited.iterrows():
            st.session_state.case_status[row["ID"]] = row["Status"]
            st.session_state.case_assignee[row["ID"]] = row["Assigned To"]

        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button("⬇ Download case register (CSV)",
                               df.to_csv(index=False).encode(),
                               file_name="row_sentinel_cases.csv", mime="text/csv")
        with dl2:
            html_report = build_html_report(cfg, rows, OPERATOR, PIPELINE_NAME, corridor_range)
            st.download_button("📄 Download inspection report (HTML)",
                               html_report.encode(),
                               file_name="row_sentinel_inspection_report.html",
                               mime="text/html",
                               help="Opens in any browser; use Print → Save as PDF to export as PDF.")
    else:
        st.info("No cases match the current filters.")

    st.markdown("---")
    st.markdown("###### Case detail")
    detail_opts = [r["ID"] for r in rows] if rows else ["— no cases match filters —"]
    if st.session_state.get("case_detail_select") not in detail_opts:
        st.session_state["case_detail_select"] = detail_opts[0]
    sel_id = st.selectbox("Select a case for full detail", detail_opts,
                          label_visibility="collapsed", key="case_detail_select")
    if rows:
        sc = case_lookup.get(sel_id)
        if sc:
            cat = categorize(sc["type"])
            icon = CATEGORY_ICON.get(cat, "📍")
            action = CATEGORY_ACTION.get(cat, "Verify in field and update case status.")
            sla_full = SEV_SLA.get(sc["sev"], "")

            # Look up the richer underlying record for extra technical fields.
            # pipeline.py doesn't attach these to the case dict directly, so we
            # reproduce its own matching logic against the raw detection lists
            # it already returns in `data` (veg / floods / excs / structures / road).
            extra = []
            if cat == "vegetation":
                veg_sorted = sorted([v for v in data["veg"] if v["level"] >= 2],
                                    key=lambda v: (-v["level"], v["dist_m"]))[:4]
                idx = int(sc["id"].split("-")[1]) - 1
                det = veg_sorted[idx] if 0 <= idx < len(veg_sorted) else {}
                extra = [("NDVI signature", det.get("ndvi")),
                        ("Encroachment area", f"{det.get('area_m2')} m²" if det.get("area_m2") else None),
                        ("Distance to pipeline", f"{det.get('dist_m')} m" if det.get("dist_m") is not None else None)]
            elif cat == "water":
                det = next((f for f in data["floods"] if f["id"] == sc["id"]), {})
                extra = [("Surface extent", f"{det.get('area_m2')} m²" if det.get("area_m2") else None),
                        ("SAR VV change", f"{det.get('vv_b')} → {det.get('vv_a')} dB" if det.get("vv_b") is not None else None),
                        ("NDWI", f"+{det.get('ndwi')}" if det.get("ndwi") is not None else None),
                        ("% inside RoW", f"{det.get('pct_rou')}%" if det.get("pct_rou") is not None else None)]
            elif cat == "excavation":
                det = next((x for x in data["excs"] if x["id"] == sc["id"]), {})
                extra = [("Footprint area", f"{det.get('area_m2')} m²" if det.get("area_m2") else None),
                        ("Est. depth", f"{det.get('depth_m')} m" if det.get("depth_m") is not None else None),
                        ("Est. volume", f"{det.get('vol_m3'):,} m³" if det.get("vol_m3") else None),
                        ("% inside RoW", f"{det.get('pct_rou')}%" if det.get("pct_rou") is not None else None)]
            elif cat == "road":
                det = data["road"]
                extra = [("Length", f"{det.get('len')} m" if det.get("len") is not None else None),
                        ("Distance to pipeline", f"{det.get('dist')} m" if det.get("dist") is not None else None),
                        ("Crosses corridor", "Yes" if det.get("cross") else "No")]
            elif cat == "structure":
                det = next((s for s in data["structures"] if s["id"] == sc["id"]), {})
                extra = [("Structure type", det.get("type")),
                        ("Footprint area", f"{det.get('area_m2')} m²" if det.get("area_m2") else None),
                        ("Within RoW", "Yes" if det.get("in_rou") else "No"),
                        ("Within monitoring band", "Yes" if det.get("within") else "No")]

            rows_html = "".join(
                f"<div class='detail-row'><span>{k}</span><span>{v}</span></div>"
                for k, v in extra if v is not None)
            st.markdown(
                f"<div class='detail-card'>"
                f"<div class='dh'><span style='font-size:20px'>{icon}</span>"
                f"<span class='id'>{sc['id']}</span>"
                f"<span class='sev-chip' style='background:{P.SEV_COL[sc['sev']]}'>{sc['sev']}</span>"
                f"</div>"
                f"<div class='detail-row'><span>Type</span><span>{sc['type']}</span></div>"
                f"<div class='detail-row'><span>Chainage</span><span>{sc['ch']}</span></div>"
                f"<div class='detail-row'><span>Confidence</span><span>{sc['conf']}%</span></div>"
                f"<div class='detail-row'><span>Coordinates</span>"
                f"<span>{sc['latlon'][0]:.5f}, {sc['latlon'][1]:.5f}</span></div>"
                f"{rows_html}"
                f"<div class='action-box'><b>Recommended action</b><br>{action}<br>"
                f"<b>Response target:</b> {sla_full}</div>"
                f"</div>", unsafe_allow_html=True)

# ── overview ─────────────────────────────────────────────────────────────────────
with tab_overview:
    status_counts = pd.Series([r["Status"] for r in all_rows]).value_counts()
    resolved_n = status_counts.get("Resolved", 0)
    summary = (
        f"As of the <b>{cfg['SCAN_DATE']}</b> satellite pass (previous pass "
        f"<b>{cfg['PREV_SCAN']}</b>), the {round(data['L'])} m {PIPELINE_NAME} corridor "
        f"shows <b>{n_total} open cases</b>. <b>{n_crit}</b> are classified Critical and "
        f"require field verification within 24 hours; <b>{n_high}</b> are High priority "
        f"(≤72 h). The largest category is "
        f"<b>{pd.Series([r['Type'] for r in all_rows]).value_counts().idxmax() if all_rows else '—'}</b>. "
        f"<b>{n_change}</b> candidate areas of surface change were identified from "
        f"historical-imagery comparison against the Cartosat-2S baseline. "
        f"{resolved_n} case(s) have been marked Resolved so far this cycle."
    )
    st.markdown(f"<div class='exec-summary'>{summary}</div>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("###### Cases by severity")
        st.bar_chart(pd.DataFrame({"count": [n_crit, n_high, n_med,
                     sum(1 for r in all_rows if r["Severity"] == "Low")]},
                     index=["Critical", "High", "Medium", "Low"]),
                     color="#e5484d", height=230)
    with col2:
        st.markdown("###### Case register status")
        if not status_counts.empty:
            st.bar_chart(status_counts, color="#38bdf8", height=230)
        else:
            st.caption("No cases to summarize.")

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("###### Cases by category")
        cat_counts = pd.Series([r["Type"] for r in all_rows]).value_counts()
        if not cat_counts.empty:
            st.bar_chart(cat_counts, color="#a855f7", height=220)
    with col4:
        st.markdown("###### Change features per epoch pair")
        if man and man.get("change"):
            cc = pd.DataFrame({"changes": [c["n"] for c in man["change"]]},
                              index=[f"{c['from']}→{c['to']}" for c in man["change"]])
            st.bar_chart(cc, color="#f0883e", height=220)
        else:
            st.caption("Run prep.py to populate change detection.")

# ── footer ───────────────────────────────────────────────────────────────────────
st.markdown(
    f"<div class='app-footer'>"
    f"<span>{BRAND} — powered by {ORG} · Cartosat-2S & historical satellite imagery</span>"
    f"<span>Confidential — for internal evaluation only</span></div>",
    unsafe_allow_html=True)
