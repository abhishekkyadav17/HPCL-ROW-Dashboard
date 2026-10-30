# ═══════════════════════════════════════════════════════════════════════════════
# app.py  ·  RoW Sentinel — South Jaipur (Cartosat-2S + GEP historical)
#
#   1) python prep.py           # build data/derived/ from your raw imagery (once)
#   2) streamlit run app.py     # launch the dashboard
#
# If data/derived/ is empty, the app still runs on an imaginary South Jaipur
# corridor with sample detections and no imagery (it prompts you to run prep.py).
# ═══════════════════════════════════════════════════════════════════════════════

import json
import os

import yaml
from yaml.loader import SafeLoader

import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth
from streamlit_folium import st_folium

import pipeline as P

BRAND = "RoW Sentinel"
SUBTITLE = "Cartosat-2S + Google Earth historical · change console"
ORG = "BioSky Space Innovations"
ASSET = "Imaginary pipeline corridor · South Jaipur"
MANIFEST = "data/derived/layers_manifest.json"

KPI = {"total": "#38bdf8", "Critical": "#e5484d", "High": "#f0883e",
       "Medium": "#f5b013", "change": "#a855f7"}

st.set_page_config(page_title=f"{BRAND} — {ORG}", page_icon="🛰️",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{--ink:#0b1016;--panel:#121a24;--surface:#18222e;--border:#243344;
      --muted:#8fa3b8;--text:#cfdae6;--strong:#eef4fb;--brand:#38bdf8;}
html,body,[class*="css"],.stApp{font-family:'Inter',system-ui,sans-serif;}
.stApp{background:var(--ink);}
[data-testid="stToolbar"]{visibility:visible;}
footer{visibility:hidden;}
/* Leave Streamlit header and sidebar controls to Streamlit itself. */
.block-container{padding-top:1.1rem;padding-bottom:1rem;max-width:1600px;}
[data-testid="stSidebar"]{background:var(--panel);border-right:1px solid var(--border);}
h1,h2,h3,h4{color:var(--strong);}
.topbar{display:flex;align-items:center;justify-content:space-between;
  padding:12px 18px;border:1px solid var(--border);border-radius:12px;
  background:linear-gradient(180deg,var(--surface),var(--panel));margin-bottom:12px;}
.brand .mark{font-size:20px;font-weight:800;color:var(--strong);}
.brand .sub{font-size:12.5px;color:var(--muted);}
.asset{font-size:12.5px;color:var(--muted);} .asset b{color:var(--text);}
.who{font-size:12.5px;color:var(--muted);text-align:right;} .who b{color:var(--text);}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:12px;}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:12px 14px;position:relative;overflow:hidden;}
.kpi .n{font-size:30px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;}
.kpi .l{font-size:11px;color:var(--muted);margin-top:6px;font-weight:600;}
.legrow{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text);margin:3px 0;}
.swatch{width:12px;height:12px;border-radius:3px;display:inline-block;}
.stTabs [data-baseweb="tab"]{background:var(--panel);border:1px solid var(--border);
  border-radius:8px 8px 0 0;color:var(--muted);padding:6px 16px;}
.stTabs [aria-selected="true"]{background:var(--surface);color:var(--strong);}
.loginwrap{text-align:center;margin-top:6vh;}
.loginwrap .mk{font-size:34px;font-weight:800;color:var(--strong);}
.loginwrap .sb{color:var(--muted);margin-bottom:18px;}
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
    c1, c2, c3 = st.columns([1, 1.25, 1])
    with c2:
        st.markdown(f"<div class='loginwrap'><div class='mk'>🛰️ {BRAND}</div>"
                    f"<div class='sb'>{SUBTITLE}</div></div>", unsafe_allow_html=True)
        authenticator.login(location="main",
                            fields={"Form name": "Sign in", "Login": "Sign in"})
        if st.session_state.get("authentication_status") is False:
            st.error("Incorrect username or password.")
    st.stop()

# Main-page logout remains available even if the sidebar is collapsed.
authenticator.logout(
    button_name="Log out",
    location="main",
    key="logout_main_btn",
)


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
if man:
    lines = man["corridor_lines"]
    center = man["center"]
    cache_key = "manifest"
else:
    center = [26.80, 75.80]                               # South Jaipur fallback
    lines = P.make_synthetic_lines(center[1], center[0], bearing_deg=18)
    cache_key = "default"

change_fc = load_change_cases(man.get("cases_geojson") if man else None)


# ── change-case severity by footprint area ──────────────────────────────────────
def change_sev(area):
    return ("Critical" if area > 8000 else "High" if area > 3000
            else "Medium" if area > 800 else "Low")


# ── sidebar ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"#### 🛰️ {BRAND}")
    st.caption(SUBTITLE)
    st.divider()

    basemap = st.selectbox("Basemap", list(P.BASEMAPS.keys()), index=0)

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
                                 index=len(epoch_opts))   # default = newest
        img_opacity = st.slider("Imagery opacity", 0.0, 1.0, 0.85, 0.05)
        show_change = st.toggle("Show detected change layer", value=bool(man.get("change")))
    else:
        sel_epoch, img_opacity, show_change = "(none)", 0.85, False
        st.caption("No imagery yet — run `python prep.py` with your Cartosat + GEP files.")

    with st.expander("Corridor geometry"):
        row_margin = st.slider("RoW margin (m)", 5, 60, P.DEFAULT_CFG["ROW_MARGIN_M"], 5)
        detect_buffer = st.slider("Monitoring band (m)", 20, 150,
                                  P.DEFAULT_CFG["DETECT_BUFFER_M"], 10)

    with st.expander("Legend"):
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

data = get_data(cache_key, row_margin, detect_buffer, lines)
cfg = data["cfg"]; cnt = data["counts"]

# ── merged case register (synthetic detections + imagery change) ─────────────────
det_rows = [{"ID": c["id"], "Type": c["type"], "Severity": c["sev"],
             "Confidence": c["conf"], "Chainage": f"CH {c['ch']}",
             "Status": c["status"], "Source": "Live scan",
             "Lat": round(c["latlon"][0], 5), "Lon": round(c["latlon"][1], 5)}
            for c in data["cases"]]
chg_rows = []
for f in change_fc["features"]:
    p = f["properties"]; sev = change_sev(p["area_m2"])
    chg_rows.append({"ID": p["id"], "Type": f"Change {p['from']}→{p['to']}",
                     "Severity": sev, "Confidence": p["conf"],
                     "Chainage": f"{p['area_m2']} m²", "Status": "New",
                     "Source": "Imagery CD", "Lat": p["lat"], "Lon": p["lon"]})
all_rows = det_rows + chg_rows
n_change = len(chg_rows)
n_total = len(all_rows)
n_crit = sum(1 for r in all_rows if r["Severity"] == "Critical")
n_high = sum(1 for r in all_rows if r["Severity"] == "High")
n_med = sum(1 for r in all_rows if r["Severity"] == "Medium")

# ── top bar + KPIs ───────────────────────────────────────────────────────────────
st.markdown(
    f"<div class='topbar'><div class='brand'><span class='mark'>🛰️ {BRAND}</span> "
    f"<span class='sub'>{SUBTITLE}</span></div>"
    f"<div class='asset'>Asset: <b>{ASSET}</b></div>"
    f"<div class='who'>Center <b>{center[0]:.3f}, {center[1]:.3f}</b><br>{ORG}</div></div>",
    unsafe_allow_html=True)

def kpi(n, label, color):
    return (f"<div class='kpi'><div class='n' style='color:{color}'>{n}</div>"
            f"<div class='l'>{label}</div>"
            f"<span style='position:absolute;left:0;top:0;bottom:0;width:4px;"
            f"background:{color}'></span></div>")

st.markdown("<div class='kpis'>"
            + kpi(n_total, "TOTAL CASES", KPI["total"])
            + kpi(n_crit, "CRITICAL", KPI["Critical"])
            + kpi(n_high, "HIGH", KPI["High"])
            + kpi(n_med, "MEDIUM", KPI["Medium"])
            + kpi(n_change, "IMAGERY CHANGE", KPI["change"])
            + "</div>", unsafe_allow_html=True)


def epoch_overlay(entry, opacity, z=3):
    return {"name": entry.get("date", "Imagery"), "png": entry["png"],
            "bounds": entry["bounds"], "opacity": opacity, "zindex": z}


tab_map, tab_img, tab_cases, tab_overview = st.tabs(
    ["🗺  Corridor map", "🛰  Imagery & change", "📋  Case register", "📊  Overview"])

# ── map tab ──────────────────────────────────────────────────────────────────────
with tab_map:
    overlays = []
    if sel_epoch != "(none)" and sel_epoch in epoch_lookup:
        overlays.append(epoch_overlay(epoch_lookup[sel_epoch], img_opacity, z=3))
    if show_change and man and man.get("change"):
        ch = man["change"][-1]
        overlays.append({"name": f"Change {ch['from']}→{ch['to']}", "png": ch["png"],
                         "bounds": ch["bounds"], "opacity": 0.8, "zindex": 4})
    m = P.build_map(data, cfg=cfg, basemap=basemap, visible_layers=chosen,
                    severities=severities, overlays=overlays,
                    change_geojson=change_fc, center=center, zoom=15)
    st_folium(m, use_container_width=True, height=640, returned_objects=[])

# ── imagery & change tab: before / after + change table ──────────────────────────
with tab_img:
    if not man or not man.get("change"):
        st.info("Run `python prep.py` with your Cartosat bands and 5 Google Earth "
                "Pro exports to populate imagery and change detection here.")
    else:
        pair_opts = [f"{c['from']} → {c['to']}" for c in man["change"]]
        sel_pair = st.selectbox("Change pair", pair_opts, index=len(pair_opts) - 1)
        ch = man["change"][pair_opts.index(sel_pair)]
        a = epoch_lookup.get(f"GEP {ch['from']}") or epoch_lookup.get(ch["from"])
        b = epoch_lookup.get(f"GEP {ch['to']}") or epoch_lookup.get(ch["to"])

        col_a, col_b = st.columns(2)
        with col_a:
            st.caption(f"Before · {ch['from']}")
            ma = P.build_map(data, cfg=cfg, basemap=basemap, visible_layers=["corridor"],
                             overlays=[epoch_overlay(a, 1.0)] if a else [],
                             center=center, zoom=15)
            st_folium(ma, use_container_width=True, height=440, returned_objects=[],
                      key="map_before")
        with col_b:
            st.caption(f"After · {ch['to']} (change overlay in red)")
            ovb = [epoch_overlay(b, 1.0)] if b else []
            ovb.append({"name": "Change", "png": ch["png"], "bounds": ch["bounds"],
                        "opacity": 0.8, "zindex": 5})
            mb = P.build_map(data, cfg=cfg, basemap=basemap, visible_layers=["corridor"],
                             overlays=ovb, change_geojson=change_fc,
                             center=center, zoom=15)
            st_folium(mb, use_container_width=True, height=440, returned_objects=[],
                      key="map_after")

        pair_cases = [r for r in chg_rows if r["Type"] == f"Change {ch['from']}→{ch['to']}"]
        st.caption(f"{len(pair_cases)} change features detected between "
                   f"{ch['from']} and {ch['to']}")
        if pair_cases:
            st.dataframe(pd.DataFrame(pair_cases)[["ID", "Severity", "Confidence",
                         "Chainage", "Lat", "Lon"]], width="stretch", hide_index=True)

# ── case register ────────────────────────────────────────────────────────────────
with tab_cases:
    rows = [r for r in all_rows if r["Severity"] in severities]
    df = pd.DataFrame(rows)
    st.caption(f"{len(df)} of {n_total} cases · {n_change} from imagery change detection")

    def sev_style(v):
        return f"color:#fff;background-color:{P.SEV_COL.get(v, '#555')};font-weight:700"
    styled = df.style.map(sev_style, subset=["Severity"]) if not df.empty else df
    st.dataframe(styled, width="stretch", hide_index=True,
                 column_config={"Confidence": st.column_config.ProgressColumn(
                     "Confidence", format="%d%%", min_value=0, max_value=100)})
    if not df.empty:
        st.download_button("Download case register (CSV)",
                           df.to_csv(index=False).encode(),
                           file_name="south_jaipur_cases.csv", mime="text/csv")

# ── overview ─────────────────────────────────────────────────────────────────────
with tab_overview:
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("###### Cases by severity")
        st.bar_chart(pd.DataFrame({"count": [n_crit, n_high, n_med,
                     sum(1 for r in all_rows if r["Severity"] == "Low")]},
                     index=["Critical", "High", "Medium", "Low"]),
                     color="#e5484d", height=240)
    with col2:
        st.markdown("###### Change features per epoch pair")
        if man and man.get("change"):
            cc = pd.DataFrame({"changes": [c["n"] for c in man["change"]]},
                              index=[f"{c['from']}→{c['to']}" for c in man["change"]])
            st.bar_chart(cc, color="#a855f7", height=240)
        else:
            st.caption("Run prep.py to populate change detection.")
    st.caption(f"Corridor {round(data['L'])} m · center {center[0]:.3f}, {center[1]:.3f} "
               f"· {n_change} imagery change cases · {len(det_rows)} live-scan cases")
