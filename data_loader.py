"""
data_loader.py
==============
Memuat dan memvalidasi file GeoJSON berisi polygon SLS.

Fungsi utama:
- load_geojson()   → GeoDataFrame yang sudah bersih dan tervalidasi
"""

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.validation import make_valid

import config

logger = logging.getLogger(__name__)


# =============================================================================
# PUBLIC FUNCTION
# =============================================================================


def load_geojson(filepath: str) -> gpd.GeoDataFrame:
    """
    Load GeoJSON SLS, repair geometry yang invalid, dan validasi kolom wajib.

    Parameters
    ----------
    filepath : str
        Path ke file GeoJSON.

    Returns
    -------
    gpd.GeoDataFrame
        GeoDataFrame dengan kolom minimal: kode_sls, muatan, geometry.
        CRS: EPSG:4326 (WGS84).

    Raises
    ------
    FileNotFoundError
        Jika file tidak ditemukan.
    ValueError
        Jika kolom wajib tidak ada atau data kosong.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File GeoJSON tidak ditemukan: {filepath}")

    logger.info(f"  Membaca file: {filepath}")
    gdf = gpd.read_file(filepath)

    if gdf.empty:
        raise ValueError("GeoJSON kosong — tidak ada fitur yang ditemukan.")

    # -------------------------------------------------------------------------
    # 1. Validasi kolom wajib
    # -------------------------------------------------------------------------
    _validate_required_columns(gdf)

    # -------------------------------------------------------------------------
    # 2. Pastikan CRS = WGS84
    # -------------------------------------------------------------------------
    if gdf.crs is None:
        logger.warning("  CRS tidak ditemukan, diasumsikan EPSG:4326 (WGS84).")
        gdf = gdf.set_crs(epsg=config.EPSG_GEO)
    elif gdf.crs.to_epsg() != config.EPSG_GEO:
        logger.info(f"  Transformasi CRS: {gdf.crs} → EPSG:{config.EPSG_GEO}")
        gdf = gdf.to_crs(epsg=config.EPSG_GEO)

    # -------------------------------------------------------------------------
    # 3. Repair geometry yang invalid (self-intersection, dll.)
    # -------------------------------------------------------------------------
    gdf = _repair_geometries(gdf)

    # -------------------------------------------------------------------------
    # 4. Filter baris dengan geometry null
    # -------------------------------------------------------------------------
    n_before = len(gdf)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    n_removed = n_before - len(gdf)
    if n_removed > 0:
        logger.warning(f"  {n_removed} SLS dihapus karena geometry kosong/null.")

    # -------------------------------------------------------------------------
    # 5. Pastikan muatan bertipe numerik dan tidak negatif
    # -------------------------------------------------------------------------
    gdf[config.COL_MUATAN] = pd.to_numeric(gdf[config.COL_MUATAN], errors="coerce").fillna(0)

    n_zero = (gdf[config.COL_MUATAN] <= 0).sum()
    if n_zero > 0:
        logger.warning(
            f"  {n_zero} SLS memiliki muatan = 0. "
            f"Tetap dimasukkan, tapi bisa memengaruhi keseimbangan."
        )

    # -------------------------------------------------------------------------
    # 6. Pastikan kode_sls unik
    # -------------------------------------------------------------------------
    dupes = gdf[config.COL_KODE_SLS].duplicated()
    if dupes.any():
        n_dupes = dupes.sum()
        logger.warning(
            f"  {n_dupes} kode_sls duplikat ditemukan. Suffix _dup ditambahkan untuk membedakan."
        )
        # Buat kode_sls unik dengan menambahkan suffix
        kode_col = config.COL_KODE_SLS
        counts = {}
        new_kodes = []
        for kode in gdf[kode_col]:
            counts[kode] = counts.get(kode, 0) + 1
            if counts[kode] > 1:
                new_kodes.append(f"{kode}_dup{counts[kode]}")
            else:
                new_kodes.append(str(kode))
        gdf[kode_col] = new_kodes

    # -------------------------------------------------------------------------
    # 7. Reset index agar konsisten
    # -------------------------------------------------------------------------
    gdf = gdf.reset_index(drop=True)

    logger.info(
        f"  Data berhasil dimuat: {len(gdf)} SLS, total muatan = {gdf[config.COL_MUATAN].sum():,}"
    )
    return gdf


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def _validate_required_columns(gdf: gpd.GeoDataFrame) -> None:
    """Pastikan kolom wajib ada di GeoDataFrame."""
    required = [config.COL_KODE_SLS, config.COL_MUATAN]
    missing = [col for col in required if col not in gdf.columns]
    if missing:
        available = list(gdf.columns)
        raise ValueError(f"Kolom wajib tidak ditemukan: {missing}. Kolom tersedia: {available}")


def _repair_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Repair geometry yang invalid menggunakan shapely.make_valid().

    Geometry yang sering invalid di data Indonesia:
    - Self-intersecting polygon (bowtie)
    - Ring tidak tertutup
    - Koordinat terduplikat
    """
    invalid_mask = ~gdf.geometry.is_valid
    n_invalid = invalid_mask.sum()

    if n_invalid == 0:
        logger.info("  Semua geometry valid.")
        return gdf

    logger.info(f"  Memperbaiki {n_invalid} geometry yang tidak valid...")

    repaired = gdf.copy()
    repaired.loc[invalid_mask, "geometry"] = repaired.loc[invalid_mask, "geometry"].apply(
        make_valid
    )

    # Cek ulang setelah repair
    still_invalid = ~repaired.geometry.is_valid
    if still_invalid.any():
        kode_invalid = repaired.loc[still_invalid, config.COL_KODE_SLS].tolist()
        logger.warning(
            f"  {still_invalid.sum()} geometry masih invalid setelah repair: "
            f"{kode_invalid[:5]}{'...' if len(kode_invalid) > 5 else ''}"
        )

    logger.info(f"  Repair selesai. {n_invalid} geometry diperbaiki.")
    return repaired
