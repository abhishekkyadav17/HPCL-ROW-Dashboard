# RoW Sentinel — South Jaipur (Cartosat-2S + Google Earth historical)

An imaginary pipeline corridor over South Jaipur, with your Cartosat-2S imagery
and five Google Earth Pro historical frames, plus visual change detection between
epochs — wrapped in the same login dashboard as before.

```
prep.py             # ONE-TIME: turns raw imagery into small web-ready layers
change_detection.py # image-differencing + vectorized change polygons
pipeline.py         # corridor geometry + folium map engine (+ imagery overlays)
app.py              # the dashboard (login, map, imagery & change, cases)
config.yaml  .streamlit/config.toml  requirements.txt
data/raw/cartosat/  # <- put BAND1..4.tif + .tfw here
data/raw/gep/       # <- put your 5 Google Earth Pro exports here
data/derived/       # <- prep.py writes the dashboard's layers here
```

## The workflow (two steps)
```bash
pip install -r requirements.txt
python prep.py          # build data/derived/ from your raw imagery  (run once)
streamlit run app.py    # launch — login reviewer / Demo@Row2026
```
If `data/derived/` is empty the dashboard still opens on the imaginary corridor
with sample detections; it just won't have imagery until you run `prep.py`.

## Step 1 — your Cartosat-2S bands
Drop the NRSC product into `data/raw/cartosat/` (BAND1.tif … BAND4.tif + the
.tfw world files). `prep.py` stacks three bands into an RGB composite, stretches
the contrast, reprojects to lat/lon, and writes a small PNG the dashboard overlays.

⚠️ **Check the band order.** Cartosat-2S MX is usually B1=Blue, B2=Green, B3=Red,
B4=NIR, so natural colour is `(R,G,B) = (BAND3, BAND2, BAND1)` — the default in
`prep.py` (`RGB_BANDS`). Confirm against your `BAND_META` file; for a false-colour
(vegetation) view use `("BAND4.tif","BAND3.tif","BAND2.tif")`.

⚠️ **Size.** Each band is ~750 MB. `prep.py` downsamples the PNG to ≤2000 px, which
is plenty for a corridor demo and keeps the app light. The full-resolution GeoTIFF
is also written (`data/derived/cartosat_rgb.tif`) if you want it in QGIS. For
full-res *in the app*, see "Full-resolution option" below.

## Step 2 — the 5 Google Earth Pro historical frames
This is the part that needs care. In Google Earth Pro:

1. Fly to South Jaipur and frame your corridor area. **Do not move the view again.**
   Type a fixed eye altitude so every frame has the identical extent.
2. Open the historical imagery time slider (the clock icon) and step to each date.
3. Turn off the compass, legend, title and scale bar (Tools → Options, and the
   View menu) so the exported image is a clean frame.
4. File → Save → Save Image (Ctrl+Alt+S), max resolution, for each of the 5 dates.
5. Save them into `data/raw/gep/` and list their filenames + dates in the
   `GEP_EPOCHS` block at the top of `prep.py`, oldest → newest.

**Georeferencing:** because every frame is exported at the *same* view, they all
share one geographic footprint. Fill `GEP_BOUNDS` in `prep.py` once
(`[[south, west], [north, east]]`) — read the view corner coordinates in GEP, or
georeference a single frame in QGIS. If you leave it `None`, `prep.py` uses the
Cartosat footprint bounds, which is close if your GEP view matches the scene.

### Honest caveat on change detection
Google Earth Pro frames are **uncalibrated RGB screenshots** from mixed sources
with different sun angles and dates. So this is *visual* change detection — it
reliably flags new construction, cleared land, earthwork, and new tracks along
the corridor (exactly what RoW monitoring needs), but it is **not** radiometric
change detection and will show some noise from lighting/source differences. For
quantitative work you'd co-register calibrated scenes (Sentinel-2 / Cartosat
multidate). Tune `CHANGE_THRESH` and `MIN_CHANGE_AREA_M2` in `prep.py` to trade
sensitivity against noise.

## What the dashboard shows
- **Corridor map** — imaginary pipeline over your Cartosat scene, the detection
  layers, a dropdown to overlay any epoch (GEP years or Cartosat), and the
  detected-change layer.
- **Imagery & change** — before/after side by side for any epoch pair, with the
  change heatmap and polygons, plus a table of change features for that pair.
- **Case register** — live-scan detections and imagery change cases merged,
  filterable, CSV export.
- **Overview** — severity breakdown and change-features-per-epoch chart.

## Deploy / share
Same as before: public GitHub repo → share.streamlit.io, credentials in Streamlit
Secrets. Commit `data/derived/` (the small PNGs + manifest) so the deployed app
has the imagery — **not** the multi-GB raw bands. If the derived PNGs are large,
Hugging Face Spaces gives more room than Community Cloud's ~1 GB tier.

## Full-resolution option (local only)
To serve the full Cartosat GeoTIFF at native resolution on your own laptop
(instead of the downsampled PNG), uncomment `leafmap` and `localtileserver` in
`requirements.txt` and add, in `pipeline.build_map`:
```python
import leafmap.foliumap as leafmap
m.add_raster("data/derived/cartosat_rgb.tif", layer_name="Cartosat (full res)")
```
This serves tiles on the fly and handles the big file — but it needs the file
present locally, so it won't work on free cloud hosting. Keep the PNG path for
deployment, the tile path for the room demo.
