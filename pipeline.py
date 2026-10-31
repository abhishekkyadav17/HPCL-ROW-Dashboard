# ═══════════════════════════════════════════════════════════════════════════════
# pipeline.py  ·  RoW corridor surveillance — detection + map engine
#
# This is the Colab logic, refactored into two pure functions the dashboard calls:
#   generate_corridor(lines_lonlat, cfg) -> dict   (all detections + geometry)
#   build_map(data, cfg, basemap, visible_layers, cartosat) -> folium.Map
#
# No Streamlit in here on purpose: it stays testable and reusable. All randomness
# is seeded so the same corridor regenerates identically across reruns.
# ═══════════════════════════════════════════════════════════════════════════════

import json
import math
import os
import random

import folium
from folium import Element, DivIcon
from folium.plugins import Fullscreen, MeasureControl, MousePosition
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring, transform, unary_union, nearest_points
import pyproj

# ── defaults (edit here or override from the app) ───────────────────────────────
DEFAULT_CFG = dict(
    ROW_MARGIN_M=20,        # RoW = this many metres beyond the outer lines
    DETECT_BUFFER_M=50,     # monitoring band = this many metres from the lines
    UTM_EPSG=32643,         # UTM 43N (72–78 E; Jaipur area)
    SCAN_DATE="2026-09-28",
    PREV_SCAN="2026-09-16",
    CLOUD_COVER="4 %",
    SEED=7,
)

# three parallel 132 kV conductors, ~1.5 km clipped from the KML (lon, lat)
DEFAULT_LINES = [
    [(78.757978, 29.515077), (78.758085, 29.513506), (78.757834, 29.512085),
     (78.75739, 29.509736), (78.756761, 29.506223), (78.75742, 29.504126),
     (78.757104, 29.502314), (78.756999, 29.501748)],
    [(78.757245, 29.501185), (78.757447, 29.502433), (78.757799, 29.504411),
     (78.757099, 29.505996), (78.758145, 29.509818), (78.758457, 29.511842),
     (78.758385, 29.513319), (78.758386, 29.514437)],
    [(78.757891, 29.501517), (78.758139, 29.502563), (78.757989, 29.504461),
     (78.75745, 29.505546), (78.758321, 29.509842), (78.758636, 29.511424),
     (78.758718, 29.513165), (78.758523, 29.514822)],
]

# canonical layer keys -> label shown in the sidebar / map
LAYER_DEFS = [
    ("corridor",   "① Transmission lines + RoW corridor"),
    ("vegetation", "② Vegetation encroachment"),
    ("water",      "③ Water / flood detection"),
    ("excavation", "④ Excavation detection"),
    ("road",       "⑤ New road detection"),
    ("structures", "⑥ Structure detection"),
    ("risk",       "⑦ RoW segment risk (ribbon)"),
    ("caseids",    "⑧ Case ID markers"),
]
ALL_LAYERS = [k for k, _ in LAYER_DEFS]

# basemap catalogue: name -> (url, attribution, subdomains, max_zoom)
_G = "&copy; Google Maps"
_E = ("Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, "
      "GIS User Community")
BASEMAPS = {
    "Google Satellite": (
        "https://mt{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        _G, ["0", "1", "2", "3"], 21
    ),
    "Satellite Image": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        _E, None, 19
    ),
}

SEV_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
SEV_COL = {"Critical": "#b71c1c", "High": "#d7191c", "Medium": "#f79824", "Low": "#1a9850"}
VEG_STYLE = {
    3: {"label": "Dense (High risk)", "core": "#d7191c", "halo": "#fdae61", "r": 7.5},
    2: {"label": "Medium",            "core": "#f79824", "halo": "#ffe08a", "r": 6.0},
    1: {"label": "Light (Low risk)",  "core": "#1a9850", "halo": "#a6d96a", "r": 5.0},
}


# ═══════════════════════════════════════════════════════════════════════════════
# KML / GeoJSON loader (falls back to the built-in sample so the app always runs)
# ═══════════════════════════════════════════════════════════════════════════════
def load_lines(path=None, fallback=DEFAULT_LINES):
    """Return a list of conductor lines as [(lon, lat), ...].

    Tries a GeoJSON or KML file at `path`; if anything is missing or unreadable,
    returns the built-in sample corridor so the demo never breaks.
    """
    if not path or not os.path.exists(path):
        return fallback
    try:
        import geopandas as gpd  # optional; only needed if you wire in a real file
        gdf = gpd.read_file(path)
        lines = []
        for geom in gdf.geometry:
            if geom is None:
                continue
            if geom.geom_type == "LineString":
                lines.append([(x, y) for x, y, *_ in geom.coords])
            elif geom.geom_type == "MultiLineString":
                for part in geom.geoms:
                    lines.append([(x, y) for x, y, *_ in part.coords])
        return lines or fallback
    except Exception:
        return fallback


# ═══════════════════════════════════════════════════════════════════════════════
# DETECTION ENGINE  (ported 1:1 from the Colab cell, wrapped in a function)
# ═══════════════════════════════════════════════════════════════════════════════
def generate_corridor(lines_lonlat=None, cfg=None):
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    lines_lonlat = lines_lonlat or DEFAULT_LINES
    ROW_MARGIN_M = cfg["ROW_MARGIN_M"]
    DETECT_BUFFER_M = cfg["DETECT_BUFFER_M"]
    random.seed(cfg["SEED"])

    _to_utm = pyproj.Transformer.from_crs(4326, cfg["UTM_EPSG"], always_xy=True).transform
    _to_wgs = pyproj.Transformer.from_crs(cfg["UTM_EPSG"], 4326, always_xy=True).transform
    to_utm = lambda g: transform(_to_utm, g)
    to_wgs = lambda g: transform(_to_wgs, g)
    ll = lambda pt_utm: (lambda g: (g.y, g.x))(to_wgs(pt_utm))

    lines_wgs = [LineString(c) for c in lines_lonlat]
    lines_utm = [to_utm(l) for l in lines_wgs]
    union_utm = unary_union(lines_utm)
    REF = lines_utm[1] if len(lines_utm) > 1 else lines_utm[0]
    L = REF.length

    def corridor(margin):
        raw = union_utm.buffer(margin, cap_style=2, join_style=1)
        return raw.buffer(35, join_style=1).buffer(-35, join_style=1)

    rou_utm = corridor(ROW_MARGIN_M)
    detect_utm = corridor(DETECT_BUFFER_M)
    rou_wgs = to_wgs(rou_utm)
    detect_wgs = to_wgs(detect_utm)

    def point_normal(line, d):
        p = line.interpolate(d)
        pa = line.interpolate(max(d - 1.0, 0))
        pb = line.interpolate(min(d + 1.0, line.length))
        dx, dy = pb.x - pa.x, pb.y - pa.y
        n = math.hypot(dx, dy) or 1.0
        return p, (-dy / n, dx / n)

    def chainage_str(d):
        return f"{int(d) // 1000}+{int(d) % 1000:03d}"

    def boundary_dist(d_along, side):
        P, (nx, ny) = point_normal(REF, d_along)
        t = 0.0
        while t < 250:
            if not rou_utm.contains(Point(P.x + nx * side * t, P.y + ny * side * t)):
                return t
            t += 1.0
        return t

    def centre_at(d_along, side, off):
        P, (nx, ny) = point_normal(REF, d_along)
        return Point(P.x + nx * side * off, P.y + ny * side * off)

    def centre_at_dist(d_along, side, target_dist):
        P, (nx, ny) = point_normal(REF, d_along)
        t = 0.0
        while t < 320:
            pt = Point(P.x + nx * side * t, P.y + ny * side * t)
            if pt.distance(union_utm) >= target_dist:
                return pt
            t += 0.5
        return Point(P.x + nx * side * t, P.y + ny * side * t)

    def irregular_poly(cx, cy, mean_r, n=11, jitter=0.5, seed=None):
        rnd = random.Random(seed)
        angs = sorted(rnd.uniform(0, 2 * math.pi) for _ in range(n))
        pts = [(cx + mean_r * (1 + rnd.uniform(-jitter, jitter)) * math.cos(a),
                cy + mean_r * (1 + rnd.uniform(-jitter, jitter)) * math.sin(a)) for a in angs]
        return Polygon(pts).buffer(0)

    # ── ① vegetation ───────────────────────────────────────────────────────────
    def risk_profile(frac):
        if 0.14 < frac < 0.30: return 3
        if 0.55 < frac < 0.69: return 3
        if 0.30 <= frac < 0.45: return 2
        if 0.69 <= frac < 0.82: return 2
        return 1

    veg = []
    rou_bound = (rou_utm.exterior if rou_utm.geom_type == "Polygon"
                 else max(rou_utm.geoms, key=lambda g: g.area).exterior)
    Bl = rou_bound.length
    bd = 6.0
    while bd < Bl - 4:
        if random.random() < 0.5:
            bp = rou_bound.interpolate(bd)
            npnt, _ = nearest_points(union_utm, bp)
            dx, dy = bp.x - npnt.x, bp.y - npnt.y
            nn = math.hypot(dx, dy) or 1.0
            ux, uy = dx / nn, dy / nn
            frac = REF.project(bp) / L
            level = risk_profile(frac)
            if random.random() < 0.22:
                level = min(3, max(1, level + random.choice([-1, 1])))
            off = random.uniform(-6, 10)
            cpt = Point(bp.x + ux * off, bp.y + uy * off)
            r = VEG_STYLE[level]["r"] * random.uniform(0.85, 1.25)
            veg.append({"pt": cpt, "latlon": ll(cpt), "level": level, "r": r,
                        "area_m2": round(math.pi * r * r),
                        "dist_m": round(cpt.distance(union_utm), 1),
                        "ch": REF.project(cpt), "conf": random.randint(78, 97),
                        "ndvi": round(random.uniform(0.62, 0.84), 2)})
        bd += random.uniform(24, 40)

    # ── ② water / flood ─────────────────────────────────────────────────────────
    FLOOD_DEFS = [(480, +1, 12, 34, 101), (980, -1, 14, 26, 202), (1250, +1, 55, 28, 303)]
    floods = []
    for i, (dl, side, tdist, mr, sd) in enumerate(FLOOD_DEFS, 1):
        c = centre_at_dist(dl, side, tdist)
        poly = irregular_poly(c.x, c.y, mr, 12, 0.55, sd)
        inter_rou = poly.intersection(rou_utm)
        inter_band = poly.intersection(detect_utm)
        pct_rou = round(100 * inter_rou.area / poly.area) if poly.area else 0
        pct_band = round(100 * inter_band.area / poly.area) if poly.area else 0
        vb = round(random.uniform(-9.5, -7.0), 1); va = round(random.uniform(-20.0, -17.5), 1)
        floods.append({"id": f"WAT-{i:03d}", "poly_wgs": to_wgs(poly),
            "inRou_wgs": to_wgs(inter_rou) if not inter_rou.is_empty else None,
            "area_m2": round(poly.area), "rou_area_m2": round(inter_rou.area),
            "pct_rou": pct_rou, "pct_band": pct_band,
            "dist_m": round(poly.distance(union_utm), 1),
            "ch": REF.project(Point(poly.centroid)),
            "vv_b": vb, "vv_a": va, "d_vv": round(va - vb, 1),
            "ndwi": round(random.uniform(0.22, 0.45), 2), "conf": random.randint(85, 97),
            "centroid": ll(Point(poly.centroid)),
            "within_rou": pct_rou > 0, "within_band": pct_band > 0})

    # ── ③ excavation ────────────────────────────────────────────────────────────
    EXC_DEFS = [
        (900, -1, 78, 13, 2.8, 404, "Earthwork beyond corridor (left side)"),
        (1120, +1, 40, 16, 1.6, 505, "Soil stockpile / trenching"),
    ]
    excs = []
    for i, (dl, side, tdist, mr, depth, sd, note) in enumerate(EXC_DEFS, 1):
        c = centre_at_dist(dl, side, tdist)
        poly = irregular_poly(c.x, c.y, mr, 9, 0.4, sd)
        inter_rou = poly.intersection(rou_utm)
        pct_rou = round(100 * inter_rou.area / poly.area) if poly.area else 0
        area = round(poly.area); vb = round(random.uniform(-10.5, -8.5), 1)
        va = round(vb + random.uniform(3.0, 4.5), 1)
        excs.append({"id": f"EXC-{i:03d}", "poly_wgs": to_wgs(poly),
            "area_m2": area, "depth_m": depth, "vol_m3": round(area * depth),
            "dist_m": round(poly.distance(union_utm), 1), "pct_rou": pct_rou, "note": note,
            "ch": REF.project(Point(poly.centroid)),
            "vv_b": vb, "vv_a": va, "d_vv": round(va - vb, 1),
            "ndvi_drop": round(random.uniform(0.18, 0.34), 2),
            "bsi": round(random.uniform(0.12, 0.26), 2), "conf": random.randint(84, 98),
            "centroid": ll(Point(poly.centroid)),
            "within_rou": pct_rou > 0,
            "within_band": poly.distance(union_utm) <= DETECT_BUFFER_M})

    # ── ⑤ new road ──────────────────────────────────────────────────────────────
    rp1 = centre_at(620, -1, 70); rp2 = centre_at(620, +1, 70)
    road_utm = LineString([(rp1.x, rp1.y), (rp2.x, rp2.y)])
    road_wgs = to_wgs(road_utm)
    road_len = round(road_utm.length, 1)
    road_dist = round(road_utm.distance(union_utm), 1)
    road_cross = road_utm.intersects(union_utm)
    road_ch = REF.project(Point(road_utm.centroid))
    road_flag = ("&#9888; CROSSES line corridor" if road_cross
                 else f"within {DETECT_BUFFER_M} m band: "
                      f"{'YES' if road_utm.distance(union_utm) <= DETECT_BUFFER_M else 'no'}")
    road_mid = ll(Point(road_utm.centroid))

    # ── ⑥ structures ────────────────────────────────────────────────────────────
    def rect_at_dist(d_along, side, target_dist, w, h):
        c = centre_at_dist(d_along, side, target_dist)
        return Polygon([(c.x - w / 2, c.y - h / 2), (c.x + w / 2, c.y - h / 2),
                        (c.x + w / 2, c.y + h / 2), (c.x - w / 2, c.y + h / 2)])

    STRUCT_DEFS = [
        (300, +1, 30, 16, 20, "Permanent"),
        (560, -1, 8, 9, 11, "Temporary"),
        (700, +1, 72, 13, 13, "Permanent"),
        (1180, -1, 35, 7, 8, "Temporary"),
    ]
    structures = []
    for i, (dl, side, tdist, w, h, typ) in enumerate(STRUCT_DEFS, 1):
        pu = rect_at_dist(dl, side, tdist, w, h)
        structures.append({"id": f"STR-{i:03d}", "type": typ, "poly_wgs": to_wgs(pu),
            "centroid": ll(Point(pu.centroid)), "area_m2": round(pu.area),
            "dist_m": round(pu.distance(union_utm), 1),
            "within": pu.distance(union_utm) <= DETECT_BUFFER_M,
            "in_rou": pu.distance(union_utm) <= ROW_MARGIN_M,
            "ch_m": REF.project(Point(pu.centroid)), "conf": random.randint(82, 98)})

    # ── ⑦ segment risk ribbon ───────────────────────────────────────────────────
    SEG_M = 80
    segments = []; s = 0.0
    while s < L:
        e = min(s + SEG_M, L)
        seg_line = substring(REF, s, e)
        seg_poly = seg_line.buffer(max(boundary_dist((s + e) / 2, 1),
                                       boundary_dist((s + e) / 2, -1)), cap_style=2)
        seg_poly = seg_poly.intersection(rou_utm)
        score = sum(v["level"] for v in veg if v["pt"].distance(seg_line) <= 30)
        if any(x["within_rou"] and abs(x["ch"] - (s + e) / 2) < SEG_M for x in excs):   score += 8
        if any(f["within_rou"] and abs(f["ch"] - (s + e) / 2) < SEG_M for f in floods): score += 5
        if score >= 7:   color, lab = "#d7191c", "High"
        elif score >= 3: color, lab = "#f79824", "Medium"
        else:            color, lab = "#1a9850", "Low"
        if not seg_poly.is_empty:
            segments.append({"poly": to_wgs(seg_poly), "color": color,
                             "label": lab, "ch": int((s + e) / 2)})
        s = e

    # ── case register ────────────────────────────────────────────────────────────
    cases = []
    for i, v in enumerate(sorted([v for v in veg if v["level"] >= 2],
                                 key=lambda v: (-v["level"], v["dist_m"]))[:4], 1):
        cases.append({"id": f"VEG-{i:03d}", "type": "Vegetation encroachment",
            "sev": "High" if v["level"] == 3 else "Medium", "conf": v["conf"],
            "ch": chainage_str(v["ch"]), "status": random.choice(["New", "Under review"]),
            "latlon": v["latlon"]})
    for f in floods:
        sev = "High" if f["within_rou"] else ("Medium" if f["within_band"] else "Low")
        cases.append({"id": f["id"], "type": "Water / flood accumulation", "sev": sev,
            "conf": f["conf"], "ch": chainage_str(f["ch"]),
            "status": "New" if f["within_band"] else "Advisory", "latlon": f["centroid"]})
    for x in excs:
        sev = "Critical" if x["within_rou"] else ("High" if x["within_band"] else "Medium")
        cases.append({"id": x["id"], "type": "Excavation / earthwork", "sev": sev,
            "conf": x["conf"], "ch": chainage_str(x["ch"]),
            "status": "Field dispatch" if sev == "Critical" else "New", "latlon": x["centroid"]})
    cases.append({"id": "ROD-001", "type": "New road / access track",
        "sev": "Critical" if road_cross else "High", "conf": random.randint(88, 96),
        "ch": chainage_str(road_ch), "status": "New", "latlon": road_mid})
    for s2 in structures:
        sev = ("Critical" if (s2["type"] == "Permanent" and s2["in_rou"]) else
               "High" if s2["within"] else "Medium")
        cases.append({"id": s2["id"], "type": f"Structure ({s2['type']})", "sev": sev,
            "conf": s2["conf"], "ch": chainage_str(s2["ch_m"]),
            "status": random.choice(["New", "Under review", "Field dispatch"]),
            "latlon": s2["centroid"]})
    cases.sort(key=lambda c: (-SEV_RANK[c["sev"]], -c["conf"]))

    # ── chainage ticks + bbox for the Cartosat overlay ──────────────────────────
    chainage_ticks = [(ll(REF.interpolate(dd)), chainage_str(dd))
                      for dd in range(0, int(L) + 1, 250)]
    minx, miny, maxx, maxy = detect_wgs.bounds
    img_bounds = [[miny, minx], [maxy, maxx]]
    all_lat = [la for ln in lines_lonlat for lo, la in ln]
    all_lon = [lo for ln in lines_lonlat for lo, la in ln]

    counts = dict(
        n_total=len(cases),
        n_crit=sum(1 for c in cases if c["sev"] == "Critical"),
        n_high=sum(1 for c in cases if c["sev"] == "High"),
        n_med=sum(1 for c in cases if c["sev"] == "Medium"),
        n_low=sum(1 for c in cases if c["sev"] == "Low"),
        n_new=sum(1 for c in cases if c["status"] == "New"),
        n3=sum(1 for v in veg if v["level"] == 3),
        n2=sum(1 for v in veg if v["level"] == 2),
        n1=sum(1 for v in veg if v["level"] == 1),
        n_perm=sum(1 for s in structures if s["type"] == "Permanent"),
        n_temp=sum(1 for s in structures if s["type"] == "Temporary"),
    )

    return dict(
        cfg=cfg, lines_lonlat=lines_lonlat,
        rou_wgs=rou_wgs, detect_wgs=detect_wgs,
        veg=veg, floods=floods, excs=excs, structures=structures,
        segments=segments, cases=cases,
        road=dict(wgs=road_wgs, len=road_len, dist=road_dist, cross=road_cross,
                  ch=road_ch, flag=road_flag, mid=road_mid, chainage=chainage_str(road_ch)),
        chainage_ticks=chainage_ticks, img_bounds=img_bounds,
        L=L, clat=sum(all_lat) / len(all_lat), clon=sum(all_lon) / len(all_lon),
        counts=counts,
        chainage_str=chainage_str,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MAP BUILDER
# ═══════════════════════════════════════════════════════════════════════════════
def build_map(data, cfg=None, basemap="Google Satellite", visible_layers=None,
              cartosat=None, severities=None, center=None, zoom=16,
              overlays=None, change_geojson=None, max_bounds=None):
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    visible = set(visible_layers if visible_layers is not None else ALL_LAYERS)
    severities = set(severities) if severities is not None else set(SEV_RANK)
    cs = data["chainage_str"]
    ROW_MARGIN_M, DETECT_BUFFER_M = cfg["ROW_MARGIN_M"], cfg["DETECT_BUFFER_M"]
    SCAN_DATE, PREV_SCAN = cfg["SCAN_DATE"], cfg["PREV_SCAN"]

    m = folium.Map(location=center or [data["clat"], data["clon"]],
                   zoom_start=zoom, tiles=None, control_scale=True, zoom_control=True,
                   max_bounds=False)

    if max_bounds:
        bounds_json = json.dumps(max_bounds)
        # Fit initial view to the permitted rectangle. The client-side guard below
        # then keeps the ENTIRE Leaflet viewport inside that rectangle.
        m.fit_bounds(max_bounds)
        m.get_root().script.add_child(Element(f"""
        (function() {{
            var map = {m.get_name()};
            var allowed = L.latLngBounds({bounds_json});
            var enforcing = false;

            function enforceAllowedViewport() {{
                if (enforcing || !map || !map.getSize().x || !map.getSize().y) return;
                enforcing = true;

                // inside=true means the map viewport must fit within allowed.
                var minZoom = map.getBoundsZoom(allowed, true);
                if (isFinite(minZoom) && map.getZoom() < minZoom) {{
                    map.setZoom(minZoom, {{animate: false}});
                }}

                // maxBounds limits dragging; panInsideBounds corrects any edge
                // overshoot after drag, keyboard movement, or programmatic pan.
                map.setMaxBounds(allowed);
                map.options.maxBoundsViscosity = 1.0;
                if (!allowed.contains(map.getBounds())) {{
                    map.panInsideBounds(allowed, {{animate: false}});
                }}

                enforcing = false;
            }}

            map.whenReady(function() {{
                // Wait until the Streamlit iframe has its final dimensions.
                window.setTimeout(function() {{
                    map.invalidateSize({{animate: false}});
                    enforceAllowedViewport();
                    map.on('zoomend moveend dragend', enforceAllowedViewport);
                    map.on('resize', function() {{
                        window.setTimeout(enforceAllowedViewport, 0);
                    }});
                }}, 150);
            }});
        }})();
        """))

    # basemap (only the selected one is added)
    url, attr, subs, mx = BASEMAPS.get(basemap, BASEMAPS["Google Satellite"])
    if url == "OpenStreetMap":
        folium.TileLayer("OpenStreetMap", name=basemap, max_zoom=mx).add_to(m)
    else:
        folium.TileLayer(url, attr=attr, name=basemap, subdomains=subs or "abc",
                         max_zoom=mx, show=True).add_to(m)

    # Optional georeferenced raster overlays supplied by the imagery manifest.
    for ov in (overlays or []):
        image_path = ov.get("png") or ov.get("path")
        bounds = ov.get("bounds")
        if image_path and bounds and os.path.exists(image_path):
            folium.raster_layers.ImageOverlay(
                image=image_path, bounds=bounds,
                opacity=ov.get("opacity", 0.85),
                name=ov.get("name", "Imagery"),
                zindex=ov.get("zindex", 3),
            ).add_to(m)

    # Optional candidate-change polygons from the imagery workflow.
    if change_geojson and change_geojson.get("features"):
        folium.GeoJson(
            change_geojson,
            name="Imagery change candidates",
            style_function=lambda feature: {
                "color": "#ff1744", "weight": 2,
                "fillColor": "#ff1744", "fillOpacity": 0.28,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[k for k in ("id", "area_m2", "conf")
                        if k in (change_geojson["features"][0].get("properties") or {})]
            ) if any(k in (change_geojson["features"][0].get("properties") or {})
                     for k in ("id", "area_m2", "conf")) else None,
        ).add_to(m)

    # optional Cartosat overlay (ImageOverlay — no tile server needed)
    if cartosat and cartosat.get("path") and os.path.exists(cartosat["path"]):
        folium.raster_layers.ImageOverlay(
            image=cartosat["path"], bounds=cartosat.get("bounds") or data["img_bounds"],
            opacity=cartosat.get("opacity", 0.9), name="Cartosat", zindex=2).add_to(m)

    # ① corridor + lines + towers + chainage
    if "corridor" in visible:
        fg = folium.FeatureGroup(name="corridor", show=True)
        folium.GeoJson(data["detect_wgs"].__geo_interface__,
            style_function=lambda f: {"color": "#9fe0ff", "weight": 1.1,
                                      "dashArray": "5,5", "fillOpacity": 0.0},
            tooltip=f"Monitoring band · {DETECT_BUFFER_M} m").add_to(fg)
        folium.GeoJson(data["rou_wgs"].__geo_interface__,
            style_function=lambda f: {"color": "#ffa500", "weight": 1.6,
                                      "fillColor": "#ffa500", "fillOpacity": 0.10},
            tooltip=f"RoW corridor · {ROW_MARGIN_M} m beyond outer lines").add_to(fg)
        for ln in data["lines_lonlat"]:
            pts = [(la, lo) for lo, la in ln]
            folium.PolyLine(pts, color="#000000", weight=4, opacity=0.35).add_to(fg)
            folium.PolyLine(pts, color="#ffffff", weight=1.8, opacity=0.95).add_to(fg)
            for lo, la in ln:
                folium.map.Marker((la, lo), icon=DivIcon(icon_size=(8, 8), icon_anchor=(4, 4),
                    html="<div style='width:6px;height:6px;background:#fff;border:1px solid #333;"
                         "transform:rotate(45deg);'></div>")).add_to(fg)
        for (lat, lon), label in data["chainage_ticks"]:
            folium.map.Marker((lat, lon), icon=DivIcon(icon_size=(46, 16), icon_anchor=(23, 8),
                html=(f"<div style='font:600 9px Segoe UI;color:#111;background:#ffd700;"
                      f"border-radius:7px;padding:1px 4px;text-align:center;"
                      f"box-shadow:0 1px 2px rgba(0,0,0,.4);'>CH {label}</div>"))).add_to(fg)
        fg.add_to(m)

    # ② vegetation
    if "vegetation" in visible:
        fg = folium.FeatureGroup(name="vegetation", show=True)
        for v in data["veg"]:
            stl = VEG_STYLE[v["level"]]; lat, lon = v["latlon"]
            folium.Circle([lat, lon], radius=v["r"] * 1.9, color=None, fill=True,
                fill_color=stl["halo"], fill_opacity=0.32, weight=0).add_to(fg)
            folium.Circle([lat, lon], radius=v["r"], color=stl["core"], weight=0.6, fill=True,
                fill_color=stl["core"], fill_opacity=0.80,
                class_name=("vy-pulse" if v["level"] == 3 else ""),
                popup=folium.Popup(
                    f"<div style='font-family:Segoe UI;min-width:195px'>"
                    f"<div style='background:{stl['core']};color:#fff;font-weight:700;padding:4px 8px;"
                    f"border-radius:4px 4px 0 0;'>Vegetation — {stl['label']}</div>"
                    f"<div style='padding:6px 8px;font-size:12px;line-height:1.5'>"
                    f"Level: <b>{v['level']}/3</b> · CH <b>{cs(v['ch'])}</b><br>"
                    f"Area: <b>{v['area_m2']} m²</b> · dist to line <b>{v['dist_m']} m</b><br>"
                    f"Signature: NDVI <b>{v['ndvi']}</b> · Confidence: <b>{v['conf']}%</b>"
                    f"</div></div>", max_width=260)).add_to(fg)
        fg.add_to(m)

    # ③ water / flood
    if "water" in visible:
        fg = folium.FeatureGroup(name="water", show=True)
        for f in data["floods"]:
            folium.GeoJson(f["poly_wgs"].__geo_interface__,
                style_function=lambda ft: {"color": "#1e88e5", "weight": 1.6,
                                           "fillColor": "#2196f3", "fillOpacity": 0.45},
                tooltip=f"{f['id']} · water extent {f['area_m2']} m²").add_to(fg)
            if f["inRou_wgs"] is not None and f["within_rou"]:
                folium.GeoJson(f["inRou_wgs"].__geo_interface__,
                    style_function=lambda ft: {"color": "#ff1744", "weight": 1.4,
                        "fillColor": "#ff1744", "fillOpacity": 0.55, "dashArray": "3,3"}).add_to(fg)
            inside_txt = (f"<span style='color:#ff6b6b;font-weight:700'>{f['pct_rou']}% inside RoW "
                          f"({f['rou_area_m2']} m²)</span>" if f["within_rou"] else
                          (f"within {DETECT_BUFFER_M} m band ({f['pct_band']}%)" if f["within_band"]
                           else "<span style='color:#8b949e'>outside band (advisory)</span>"))
            folium.Marker(f["centroid"], icon=folium.Icon(color="blue", icon="tint", prefix="fa"),
                popup=folium.Popup(
                    f"<div style='font-family:Segoe UI;min-width:220px'>"
                    f"<div style='background:#1e88e5;color:#fff;font-weight:700;padding:4px 8px;"
                    f"border-radius:4px 4px 0 0;'>{f['id']} · Water / Flood</div>"
                    f"<div style='padding:6px 8px;font-size:12px;line-height:1.5'>"
                    f"CH <b>{cs(f['ch'])}</b> · dist to line <b>{f['dist_m']} m</b><br>"
                    f"Surface extent: <b>{f['area_m2']} m²</b><br>"
                    f"RoW encroachment: {inside_txt}<br>"
                    f"<span style='color:#8b949e'>Signature (SAR C-band):</span><br>"
                    f"VV {f['vv_b']} &rarr; <b>{f['vv_a']} dB</b> (&Delta;{f['d_vv']} dB, specular drop)<br>"
                    f"NDWI: <b>+{f['ndwi']}</b><br>"
                    f"First detected: <b>{SCAN_DATE}</b> (new vs {PREV_SCAN})<br>"
                    f"Confidence: <b>{f['conf']}%</b></div></div>", max_width=300)).add_to(fg)
        fg.add_to(m)

    # ④ excavation
    if "excavation" in visible:
        fg = folium.FeatureGroup(name="excavation", show=True)
        for x in data["excs"]:
            crit = x["within_rou"]; edge = "#b71c1c" if crit else "#6d4c41"
            folium.GeoJson(x["poly_wgs"].__geo_interface__,
                style_function=(lambda c: lambda ft: {"color": c, "weight": 2.2,
                    "fillColor": "#8d6e63", "fillOpacity": 0.6})(edge),
                class_name=("vy-pulse" if crit else ""),
                tooltip=f"{x['id']} · excavation {x['area_m2']} m²").add_to(fg)
            rou_txt = (f"<span style='color:#ff6b6b;font-weight:700'>&#9888; {x['pct_rou']}% INSIDE RoW "
                       f"— third-party interference</span>" if crit else
                       (f"within {DETECT_BUFFER_M} m band" if x["within_band"] else "outside band"))
            folium.Marker(x["centroid"],
                icon=folium.Icon(color=("red" if crit else "orange"), icon="warning-sign"),
                popup=folium.Popup(
                    f"<div style='font-family:Segoe UI;min-width:230px'>"
                    f"<div style='background:{edge};color:#fff;font-weight:700;padding:4px 8px;"
                    f"border-radius:4px 4px 0 0;'>{x['id']} · Excavation / Earthwork"
                    f"{' · CRITICAL' if crit else ''}</div>"
                    f"<div style='padding:6px 8px;font-size:12px;line-height:1.5'>"
                    f"CH <b>{cs(x['ch'])}</b> · dist to line <b>{x['dist_m']} m</b><br>"
                    f"{rou_txt}<br>Area: <b>{x['area_m2']} m²</b><br>"
                    f"Est. depth: <b>{x['depth_m']} m</b> (InSAR/stereo)<br>"
                    f"Est. volume: <b>{x['vol_m3']:,} m³</b><br>"
                    f"<span style='color:#8b949e'>Signatures:</span><br>"
                    f"SAR VV {x['vv_b']} &rarr; <b>{x['vv_a']} dB</b> (&Delta;+{x['d_vv']} dB, roughening)<br>"
                    f"NDVI drop <b>-{x['ndvi_drop']}</b> · BSI <b>+{x['bsi']}</b><br>{x['note']}<br>"
                    f"First detected: <b>{SCAN_DATE}</b> · Confidence: <b>{x['conf']}%</b>"
                    f"</div></div>", max_width=320)).add_to(fg)
        fg.add_to(m)

    # ⑤ new road
    if "road" in visible:
        fg = folium.FeatureGroup(name="road", show=True)
        rd = data["road"]
        folium.PolyLine([(la, lo) for lo, la in rd["wgs"].coords], color="#d500f9",
            weight=4.5, opacity=0.92, class_name="vy-pulse",
            popup=folium.Popup(
                f"<div style='font-family:Segoe UI;min-width:205px'>"
                f"<div style='background:#d500f9;color:#fff;font-weight:700;padding:4px 8px;"
                f"border-radius:4px 4px 0 0;'>ROD-001 · New Road</div>"
                f"<div style='padding:6px 8px;font-size:12px;line-height:1.5'>"
                f"Linear feature (access track)<br>"
                f"Length: <b>{rd['len']} m</b> · CH <b>{rd['chainage']}</b><br>"
                f"Nearest distance: <b>{rd['dist']} m</b><br>"
                f"<span style='color:#d500f9;font-weight:700'>{rd['flag']}</span><br>"
                f"Signature: NDVI collapse along track<br>"
                f"First detected: <b>{SCAN_DATE}</b></div></div>", max_width=300),
            tooltip=f"New road · {rd['len']} m").add_to(fg)
        for lo, la in [rd["wgs"].coords[0], rd["wgs"].coords[-1]]:
            folium.CircleMarker([la, lo], radius=3, color="#d500f9", fill=True,
                fill_color="#d500f9", fill_opacity=1).add_to(fg)
        fg.add_to(m)

    # ⑥ structures
    if "structures" in visible:
        fg = folium.FeatureGroup(name="structures", show=True)
        STR_COL = {"Permanent": "#ff1744", "Temporary": "#ff9100"}
        for s in data["structures"]:
            col = STR_COL[s["type"]]
            folium.GeoJson(s["poly_wgs"].__geo_interface__,
                style_function=(lambda c: lambda ft: {"color": c, "weight": 2,
                    "fillColor": c, "fillOpacity": 0.45})(col),
                tooltip=f"{s['id']} · {s['type']}",
                popup=folium.Popup(
                    f"<div style='font-family:Segoe UI;min-width:200px'>"
                    f"<div style='background:{col};color:#fff;font-weight:700;padding:4px 8px;"
                    f"border-radius:4px 4px 0 0;'>{s['id']} · {s['type']} Structure</div>"
                    f"<div style='padding:6px 8px;font-size:12px;line-height:1.5'>"
                    f"CH <b>{cs(s['ch_m'])}</b><br>"
                    f"Area: <b>{s['area_m2']} m²</b> · dist to line <b>{s['dist_m']} m</b><br>"
                    f"Within RoW: <b>{'YES' if s['in_rou'] else 'no'}</b> · "
                    f"within band: <b>{'YES' if s['within'] else 'no'}</b><br>"
                    f"Signature: NDBI rise, NDVI drop · Conf: <b>{s['conf']}%</b>"
                    f"</div></div>", max_width=280)).add_to(fg)
        fg.add_to(m)

    # ⑦ segment risk ribbon
    if "risk" in visible:
        fg = folium.FeatureGroup(name="risk", show=True)
        for sg in data["segments"]:
            folium.GeoJson(sg["poly"].__geo_interface__,
                style_function=(lambda c: lambda ft: {"color": c, "weight": 0.4,
                    "fillColor": c, "fillOpacity": 0.5})(sg["color"]),
                tooltip=f"Segment CH {cs(sg['ch'])} · Risk: {sg['label']}").add_to(fg)
        fg.add_to(m)

    # ⑧ case-ID markers (respects the severity filter)
    if "caseids" in visible:
        fg = folium.FeatureGroup(name="caseids", show=True)
        for c in data["cases"]:
            if c["sev"] not in severities:
                continue
            col = SEV_COL[c["sev"]]
            folium.map.Marker(c["latlon"], icon=DivIcon(icon_size=(70, 18), icon_anchor=(35, 26),
                html=(f"<div style='font:700 9px Segoe UI;color:#fff;background:{col};"
                      f"border:1px solid #fff;border-radius:9px;padding:1px 5px;text-align:center;"
                      f"white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,.5);'>{c['id']}</div>"))).add_to(fg)
        fg.add_to(m)

    # map controls + pulse animation for critical features
    Fullscreen(position="topleft").add_to(m)
    MeasureControl(position="topleft", primary_length_unit="meters",
                   primary_area_unit="sqmeters").add_to(m)
    MousePosition(position="bottomleft", prefix="Lat/Lon:", num_digits=5).add_to(m)
    m.get_root().html.add_child(Element(
        "<style>@keyframes vyPulse{0%{stroke-opacity:1;stroke-width:1;}"
        "50%{stroke-opacity:.2;stroke-width:6;}100%{stroke-opacity:1;stroke-width:1;}}"
        ".vy-pulse{animation:vyPulse 1.8s ease-in-out infinite;}</style>"))
    return m
