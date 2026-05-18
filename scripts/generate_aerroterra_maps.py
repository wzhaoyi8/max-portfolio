#!/usr/bin/env python3
"""
generate_aerroterra_maps.py
Processes ESA WorldCover 2021 data to produce styled map PNGs
for the AerroTerra UAE site intelligence section.

Output files (all in images/aerroterra/):
  map-uae-landcover.png        — UAE overview, land cover
  map-abudhabi-landcover.png   — Abu Dhabi urban zoom
  map-suitability.png          — AerroTerra deployment suitability
  map-bounds.json              — Lat/lon bounds for Leaflet imageOverlay
"""

import rasterio
from rasterio.merge import merge
import numpy as np
from PIL import Image
import json, os
from pathlib import Path
from scipy.ndimage import uniform_filter

TILE_DIR   = "/Users/max/Downloads/ESA_WORLDCOVER_10M_2021_V200/MAP"
OUTPUT_DIR = "/Users/max/max-portfolio/images/aerroterra"

# ── ESA WorldCover 2021 class → RGBA ─────────────────────────────────
# Palette tuned to portfolio aesthetic: warm, low-saturation, off-white bg
PALETTE = {
    10:  (142, 168,  97, 220),   # tree cover — sage green
    20:  (185, 175, 155, 160),   # shrubland  — warm tan
    30:  (185, 175, 155, 140),   # grassland
    40:  (185, 175, 155, 140),   # cropland
    50:  (165,  72,  57, 235),   # built-up   — terracotta
    60:  (215, 207, 190, 160),   # bare/sparse — sand
    70:  (230, 235, 240, 180),   # snow/ice
    80:  (148, 185, 210, 200),   # water       — pale blue
    90:  ( 82, 158, 158, 200),   # wetland     — teal
    95:  ( 82, 158, 158, 200),   # mangrove
    100: (185, 185, 195, 150),   # moss
}

# Suitability overlay colors
SUIT_HIGH   = (192,  90,  70, 240)   # hot terracotta — deploy here
SUIT_MED    = (215, 155,  90, 190)   # amber — moderate
SUIT_BUILT  = (165,  72,  57, 100)   # faint built-up wash

# Geographic extents  [west, south, east, north]
UAE_BOUNDS  = (51.0, 22.5, 56.5, 26.5)
AD_BOUNDS   = (53.8, 23.9, 56.0, 25.2)   # Abu Dhabi focus

# ── Tile handling ─────────────────────────────────────────────────────

def find_tifs(tile_dir):
    return sorted(str(f)
                  for d in Path(tile_dir).iterdir() if d.is_dir()
                  for f in d.glob("*_Map.tif"))

def merge_mosaic(tif_paths):
    srcs = [rasterio.open(p) for p in tif_paths]
    mosaic, transform = merge(srcs)
    crs = srcs[0].crs
    for s in srcs:
        s.close()
    return mosaic[0], transform, crs

# ── Clip & resample ───────────────────────────────────────────────────

def clip_resample(data, transform, bounds, target_w):
    """
    Clip raster to [west, south, east, north] bounds and
    bilinearly resample to target_w pixels wide.
    Returns (clipped_array, actual_bounds).
    """
    west, south, east, north = bounds
    res = transform.a  # pixel width in degrees

    # Convert geographic coords → pixel indices
    col0 = int((west  - transform.c) / res)
    col1 = int((east  - transform.c) / res)
    row0 = int((north - transform.f) / transform.e)   # e is negative
    row1 = int((south - transform.f) / transform.e)

    col0 = max(0, col0);  row0 = max(0, row0)
    col1 = min(data.shape[1], col1)
    row1 = min(data.shape[0], row1)

    clipped = data[row0:row1, col0:col1]
    aspect  = (row1 - row0) / max(col1 - col0, 1)
    target_h = int(target_w * aspect)

    # PIL NEAREST to preserve class values; we colour-map after
    img = Image.fromarray(clipped.astype(np.uint8))
    img = img.resize((target_w, target_h), Image.NEAREST)
    return np.array(img), (west, south, east, north)

# ── Colorisation ──────────────────────────────────────────────────────

def to_rgba(data):
    h, w = data.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for val, color in PALETTE.items():
        rgba[data == val] = color
    return rgba

def compute_suitability_overlay(data):
    """
    Suitability = f(built-up density, absence of tree cover)
    Kernel = 80px ≈ ~2km at Abu Dhabi zoom resolution.
    """
    built = (data == 50).astype(np.float32)
    tree  = (data == 10).astype(np.float32)

    built_density = uniform_filter(built, size=80)
    tree_density  = uniform_filter(tree,  size=80)

    h, w   = data.shape
    overlay = np.zeros((h, w, 4), dtype=np.uint8)

    high   = (built_density > 0.30) & (tree_density < 0.05)
    medium = (built_density > 0.08) & ~high & (data == 50)

    overlay[high]   = SUIT_HIGH
    overlay[medium] = SUIT_MED
    # Dim wash for any remaining built-up
    overlay[(data == 50) & ~high & ~medium] = SUIT_BUILT

    return overlay

# ── Composite legend bar ──────────────────────────────────────────────

def add_legend_bar(rgba, mode="landcover"):
    """Append a thin legend strip to the bottom of the image."""
    h, w = rgba.shape[:2]
    bar_h = max(24, h // 40)
    bar   = np.zeros((bar_h, w, 4), dtype=np.uint8)

    if mode == "landcover":
        items = [
            ("Built-up",         (165, 72,  57,  235)),
            ("Bare / Sparse",    (215, 207, 190, 220)),
            ("Tree cover",       (142, 168,  97, 220)),
            ("Water",            (148, 185, 210, 220)),
            ("Wetland",          ( 82, 158, 158, 220)),
        ]
    else:  # suitability
        items = [
            ("High priority",   SUIT_HIGH),
            ("Moderate",        SUIT_MED),
            ("Low / Other",     SUIT_BUILT),
        ]

    n  = len(items)
    sw = w // n
    for i, (_, color) in enumerate(items):
        bar[:, i*sw:(i+1)*sw] = color

    return np.vstack([rgba, bar])

# ── Main ──────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("1/5  Reading & merging tiles...")
    tifs = find_tifs(TILE_DIR)
    print(f"     {len(tifs)} tiles: {[Path(t).parent.name for t in tifs]}")
    mosaic, transform, _ = merge_mosaic(tifs)
    print(f"     Mosaic: {mosaic.shape}")

    print("2/5  Clipping — UAE overview (2400px)...")
    uae_data, uae_bounds = clip_resample(mosaic, transform, UAE_BOUNDS,  target_w=2400)
    uae_rgba = to_rgba(uae_data)
    uae_rgba = add_legend_bar(uae_rgba, mode="landcover")
    Image.fromarray(uae_rgba, "RGBA").save(f"{OUTPUT_DIR}/map-uae-landcover.png")
    print(f"     Saved map-uae-landcover.png  {uae_data.shape}")

    print("3/5  Clipping — Abu Dhabi zoom (2400px)...")
    ad_data, ad_bounds = clip_resample(mosaic, transform, AD_BOUNDS, target_w=2400)
    ad_rgba = to_rgba(ad_data)
    ad_rgba = add_legend_bar(ad_rgba, mode="landcover")
    Image.fromarray(ad_rgba, "RGBA").save(f"{OUTPUT_DIR}/map-abudhabi-landcover.png")
    print(f"     Saved map-abudhabi-landcover.png  {ad_data.shape}")

    print("4/5  Computing suitability overlay (Abu Dhabi)...")
    # Re-clip without legend for analysis
    ad_raw, _ = clip_resample(mosaic, transform, AD_BOUNDS, target_w=2400)
    suit_overlay = compute_suitability_overlay(ad_raw)
    # Composite: base landcover + suitability on top
    base = to_rgba(ad_raw).astype(np.float32)
    suit = suit_overlay.astype(np.float32)
    alpha = suit[:, :, 3:4] / 255.0
    composite = (base * (1 - alpha) + suit * alpha).astype(np.uint8)
    composite = add_legend_bar(composite, mode="suitability")
    Image.fromarray(composite, "RGBA").save(f"{OUTPUT_DIR}/map-suitability.png")
    print(f"     Saved map-suitability.png")

    print("5/5  Writing bounds JSON for Leaflet...")
    bounds = {
        "uae": {
            "image": "images/aerroterra/map-uae-landcover.png",
            "leaflet_bounds": [[UAE_BOUNDS[1], UAE_BOUNDS[0]],
                               [UAE_BOUNDS[3], UAE_BOUNDS[2]]],
            "center": [24.0, 53.5], "zoom": 7
        },
        "abu_dhabi": {
            "image": "images/aerroterra/map-abudhabi-landcover.png",
            "leaflet_bounds": [[AD_BOUNDS[1], AD_BOUNDS[0]],
                               [AD_BOUNDS[3], AD_BOUNDS[2]]],
            "center": [24.45, 54.35], "zoom": 10
        },
        "suitability": {
            "image": "images/aerroterra/map-suitability.png",
            "leaflet_bounds": [[AD_BOUNDS[1], AD_BOUNDS[0]],
                               [AD_BOUNDS[3], AD_BOUNDS[2]]],
            "center": [24.45, 54.35], "zoom": 10
        },
    }
    with open(f"{OUTPUT_DIR}/map-bounds.json", "w") as f:
        json.dump(bounds, f, indent=2)
    print(f"     Saved map-bounds.json")
    print("\nDone. Check images/aerroterra/ for outputs.")

if __name__ == "__main__":
    main()
