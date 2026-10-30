# ═══════════════════════════════════════════════════════════════════════════════
# prep.py  ·  one-time preprocessing: run this on your laptop before the dashboard
#
#   python prep.py
#
# It turns heavy raw data into small, web-ready layers the dashboard loads:
#   data/raw/cartosat/BAND1..4.tif      (your NRSC Cartosat-2S bands)
#   data/raw/gep/<date>.jpg             (your 5 Google Earth Pro exports)
#        ->  data/derived/cartosat_rgb.png      (+ .tif, clipped to corridor)
#            data/derived/gep_<date>.png
#            data/derived/change_<a>_<b>.png     (heatmaps)
#            data/derived/change_cases.geojson
#            data/derived/layers_manifest.json   (the dashboard reads this)
#
# Edit the CONFIG block for your band order, GEP dates, and the shared GEP bounds.
# ═══════════════════════════════════════════════════════════════════════════════

import json
import os

import numpy as np
from PIL import Image
import rasterio
from rasterio.warp import transform_bounds

import change_detection as cd
import pipeline as P

# ── CONFIG ──────────────────────────────────────────────────────────────────────
RAW_CARTOSAT = "data/raw/cartosat"       # folder with BAND1.tif ... BAND4.tif
RAW_GEP = "data/raw/gep"                 # folder with your 5 GEP exports
DERIVED = "data/derived"

# Cartosat-2S MX band order is usually B1=Blue, B2=Green, B3=Red, B4=NIR.
# CHECK BAND_META to confirm. Natural colour = (R,G,B) = (B3,B2,B1).
RGB_BANDS = ("BAND3.tif", "BAND2.tif", "BAND1.tif")   # (R, G, B) filenames
STRETCH_PCT = (2, 98)                     # percentile contrast stretch

# Your 5 Google Earth Pro epochs, OLDEST → NEWEST, with their capture dates.
# File names are whatever you saved them as in data/raw/gep/.
GEP_EPOCHS = [
    ("2014-03", "gep_2014.jpg"),
    ("2017-11", "gep_2017.jpg"),
    ("2020-02", "gep_2020.jpg"),
    ("2022-12", "gep_2022.jpg"),
    ("2024-10", "gep_2024.jpg"),
]

# Shared geographic bounds of ALL GEP exports, in lat/lon. Because you export
# every historical frame at the SAME view/altitude, they share these bounds.
# Fill these in once (read the view corners in GEP, or georeference one frame).
# Leave as None to auto-use the Cartosat footprint bounds instead.
GEP_BOUNDS = None     # e.g. [[26.78, 75.78], [26.86, 75.86]]  ->  [[S,W],[N,E]]

CHANGE_THRESH = 0.18
MIN_CHANGE_AREA_M2 = 150
# ────────────────────────────────────────────────────────────────────────────────


def _stretch(a, lo_pct, hi_pct):
    a = a.astype("float32")
    lo, hi = np.percentile(a[a > 0] if (a > 0).any() else a, [lo_pct, hi_pct])
    if hi <= lo:
        hi = lo + 1
    return np.clip((a - lo) / (hi - lo) * 255, 0, 255).astype("uint8")


def stack_rgb(cartosat_dir, rgb_bands, out_tif):
    """Read 3 single-band GeoTIFFs, stretch, stack to an 8-bit RGB GeoTIFF."""
    paths = [os.path.join(cartosat_dir, b) for b in rgb_bands]
    with rasterio.open(paths[0]) as src0:
        prof = src0.profile
    chans = []
    for p in paths:
        with rasterio.open(p) as src:
            chans.append(_stretch(src.read(1), *STRETCH_PCT))
    rgb = np.stack(chans, 0)
    prof.update(count=3, dtype="uint8", compress="deflate",
                photometric="RGB", nodata=0)
    with rasterio.open(out_tif, "w", **prof) as dst:
        dst.write(rgb)
    return out_tif


def bounds_4326(tif):
    with rasterio.open(tif) as src:
        w, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
    return [[s, w], [n, e]]


def rgb_tif_to_png(tif, out_png, max_px=2000):
    """Write a web-friendly PNG from an RGB GeoTIFF (downsampled if large)."""
    with rasterio.open(tif) as src:
        scale = min(1.0, max_px / max(src.width, src.height))
        ow, oh = int(src.width * scale), int(src.height * scale)
        data = src.read(out_shape=(3, oh, ow))
    Image.fromarray(np.transpose(data, (1, 2, 0)), "RGB").save(out_png)
    return out_png


def register_gep(epochs, src_dir, bounds, out_dir, size=(1600, 1600)):
    """Normalize GEP exports to a common size + save as PNG with shared bounds."""
    out = []
    for date, fname in epochs:
        p = os.path.join(src_dir, fname)
        if not os.path.exists(p):
            print(f"  ! missing GEP export: {p} (skipped)")
            continue
        im = Image.open(p).convert("RGB").resize(size)
        op = os.path.join(out_dir, f"gep_{date}.png")
        im.save(op)
        out.append({"date": date, "png": op, "bounds": bounds})
    return out


def main():
    os.makedirs(DERIVED, exist_ok=True)
    manifest = {"epochs": [], "change": [], "cartosat": None,
                "corridor": None, "center": None, "cases_geojson": None}

    # 1) Cartosat -> RGB overlay ------------------------------------------------
    cart_png = None
    cart_bounds = None
    have_cartosat = all(os.path.exists(os.path.join(RAW_CARTOSAT, b)) for b in RGB_BANDS)
    if have_cartosat:
        print("Cartosat: stacking RGB composite…")
        tif = stack_rgb(RAW_CARTOSAT, RGB_BANDS, os.path.join(DERIVED, "cartosat_rgb.tif"))
        cart_bounds = bounds_4326(tif)
        cart_png = rgb_tif_to_png(tif, os.path.join(DERIVED, "cartosat_rgb.png"))
        manifest["cartosat"] = {"date": "Cartosat-2S", "png": cart_png, "bounds": cart_bounds}
        print(f"  bounds (lat/lon): {cart_bounds}")
    else:
        print(f"Cartosat bands not found in {RAW_CARTOSAT} — skipping imagery.")

    # 2) corridor (imaginary pipeline) centred on the Cartosat scene ------------
    if cart_bounds:
        (s, w), (n, e) = cart_bounds
        clon, clat = (w + e) / 2, (s + n) / 2
    else:
        clat, clon = 26.80, 75.80        # South Jaipur fallback
    lines = P.make_synthetic_lines(clon, clat, length_m=1500, bearing_deg=18)
    manifest["center"] = [clat, clon]
    manifest["corridor_lines"] = lines

    # 3) GEP epochs -------------------------------------------------------------
    gep_bounds = GEP_BOUNDS or cart_bounds
    epochs = []
    if gep_bounds:
        epochs = register_gep(GEP_EPOCHS, RAW_GEP, gep_bounds, DERIVED)
        manifest["epochs"] = epochs
        if epochs:
            print(f"GEP: registered {len(epochs)} epochs.")
    else:
        print("No GEP bounds and no Cartosat footprint — skipping GEP epochs.")

    # 4) change detection across consecutive epochs (+ last GEP vs Cartosat) ----
    series = [(e["date"], e["png"], e["bounds"]) for e in epochs]
    if cart_png and gep_bounds:
        series.append(("Cartosat-2S", cart_png, gep_bounds))

    all_cases = {"type": "FeatureCollection", "features": []}
    cid = 1
    for (da, pa, ba), (db, pb, bb) in zip(series, series[1:]):
        print(f"Change: {da} → {db}")
        feats, heat, _ = cd.detect_between(pa, pb, bb, CHANGE_THRESH, MIN_CHANGE_AREA_M2)
        hp = os.path.join(DERIVED, f"change_{da}_{db}.png")
        Image.fromarray(heat, "RGBA").save(hp)
        manifest["change"].append({"from": da, "to": db, "png": hp, "bounds": bb,
                                   "n": len(feats)})
        for f in feats:
            all_cases["features"].append({
                "type": "Feature", "geometry": f["geom"].__geo_interface__,
                "properties": {"id": f"CHG-{cid:03d}", "type": "Surface change",
                               "from": da, "to": db, "area_m2": f["area_m2"],
                               "conf": f["conf"],
                               "lat": round(f["centroid"][0], 6),
                               "lon": round(f["centroid"][1], 6)}})
            cid += 1
        print(f"  {len(feats)} change features")

    if all_cases["features"]:
        cp = os.path.join(DERIVED, "change_cases.geojson")
        with open(cp, "w") as fh:
            json.dump(all_cases, fh)
        manifest["cases_geojson"] = cp

    with open(os.path.join(DERIVED, "layers_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"\nDone. {len(all_cases['features'])} change cases. "
          f"Manifest → {DERIVED}/layers_manifest.json")


if __name__ == "__main__":
    main()
