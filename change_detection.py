# ═══════════════════════════════════════════════════════════════════════════════
# change_detection.py  ·  visual change detection between co-registered RGB epochs
#
# Works on aligned RGB images (Google Earth Pro exports + Cartosat RGB) that share
# the SAME geographic bounds. Produces: a change-intensity raster, a colorized
# heatmap PNG for overlay, and vectorized change polygons with area + centroid.
#
# NOTE: this is *visual* change detection on uncalibrated RGB — good for spotting
# new construction / cleared land / earthwork along a corridor. It is NOT
# radiometric change detection; sun-angle and source differences between GEP
# epochs will add noise. Co-register your epochs to the same extent first.
# ═══════════════════════════════════════════════════════════════════════════════

import numpy as np
from PIL import Image, ImageFilter
from rasterio import features
from rasterio.transform import from_bounds
import pyproj
from shapely.geometry import shape
from shapely.ops import transform as shp_transform


def utm_epsg(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def load_rgb(path, size=None):
    """Load an image as an HxWx3 uint8 array (optionally resized to (W, H))."""
    im = Image.open(path).convert("RGB")
    if size:
        im = im.resize(size)
    return np.asarray(im)


def align(a, b):
    """Resize b to a's pixel shape so the two epochs line up pixel-for-pixel."""
    if a.shape[:2] != b.shape[:2]:
        im = Image.fromarray(b).resize((a.shape[1], a.shape[0]))
        b = np.asarray(im)
    return a, b


def change_intensity(a, b, blur=2.0):
    """Per-pixel RGB Euclidean distance, normalized 0..1, lightly blurred to
    suppress single-pixel noise."""
    a, b = align(a, b)
    af, bf = a.astype("float32"), b.astype("float32")
    d = np.sqrt(((af - bf) ** 2).sum(axis=-1)) / (np.sqrt(3) * 255.0)
    if blur:
        d8 = (d * 255).astype("uint8")
        d = np.asarray(Image.fromarray(d8).filter(ImageFilter.GaussianBlur(blur)),
                       dtype="float32") / 255.0
    return np.clip(d, 0, 1)


def change_features(intensity, bounds, thresh=0.18, min_area_m2=150):
    """Threshold the intensity, drop small blobs, vectorize to change polygons.

    bounds = [[south, west], [north, east]] in EPSG:4326 (lat/lon).
    Returns (features, cleaned_mask).
    """
    (s, w), (n, e) = bounds
    H, W = intensity.shape
    transform = from_bounds(w, s, e, n, W, H)
    mask = (intensity > thresh).astype("uint8")

    midlat = (s + n) / 2.0
    mperdeg_lat = 111320.0
    mperdeg_lon = 111320.0 * np.cos(np.radians(midlat))
    px_w = (e - w) / W * mperdeg_lon
    px_h = (n - s) / H * mperdeg_lat
    px_area = abs(px_w * px_h) or 1.0
    min_px = max(1, int(min_area_m2 / px_area))
    if mask.any():
        mask = features.sieve(mask, size=min_px)

    epsg = utm_epsg((w + e) / 2.0, midlat)
    to_utm = pyproj.Transformer.from_crs(4326, epsg, always_xy=True).transform

    feats = []
    for geom, val in features.shapes(mask, mask=mask.astype(bool), transform=transform):
        if val != 1:
            continue
        poly = shape(geom)
        if poly.is_empty:
            continue
        area = shp_transform(to_utm, poly).area
        if area < min_area_m2:
            continue
        c = poly.centroid
        feats.append({
            "geom": poly, "area_m2": round(area), "centroid": (c.y, c.x),
            "conf": int(min(99, 60 + 40 * min(1.0, area / 2000.0))),
        })
    feats.sort(key=lambda f: -f["area_m2"])
    return feats, mask


def colorize(intensity, thresh=0.18):
    """Map change intensity to an RGBA heatmap (transparent below threshold,
    yellow→red above). Returns an HxWx4 uint8 array for a PNG overlay."""
    h, w = intensity.shape
    rgba = np.zeros((h, w, 4), "uint8")
    t = np.clip((intensity - thresh) / (1 - thresh), 0, 1)
    on = intensity > thresh
    rgba[..., 0] = 255
    rgba[..., 1] = (255 * (1 - t)).astype("uint8")
    rgba[..., 2] = 0
    rgba[..., 3] = (on * (80 + 175 * t)).astype("uint8")
    return rgba


def detect_between(path_a, path_b, bounds, thresh=0.18, min_area_m2=150,
                   work_size=(900, 900)):
    """Full pipeline for one epoch pair → (features, heatmap_rgba, intensity)."""
    a = load_rgb(path_a, size=work_size)
    b = load_rgb(path_b, size=work_size)
    inten = change_intensity(a, b)
    feats, _ = change_features(inten, bounds, thresh, min_area_m2)
    heat = colorize(inten, thresh)
    return feats, heat, inten
