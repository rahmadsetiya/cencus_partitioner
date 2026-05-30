"""
run_from_excel.py
=================
Entry point alternatif yang menggunakan Excel sebagai SUMBER UTAMA:
  - Sheet1 → adjacency matrix (siapa bisa akses siapa)
  - Sheet2 → mapping KODE → IDSUBSLS → MUATAN
  - GeoJSON → hanya untuk geometry (visualisasi peta)

Tidak membutuhkan OSM atau polygon touching sama sekali.
Adjacency dari Excel dianggap sudah benar secara lapangan.

FORMAT EXCEL YANG DIHARAPKAN:
  Sheet1 (adjacency matrix):
    - Baris 1 = header (label: A, B, C, ... AK)
    - Kolom 1 = label baris (A, B, C, ... AK)
    - Nilai: 1 (ada akses), 0 (tidak ada akses), - (diagonal/diri sendiri)

  Sheet2 (muatan):
    - Kolom KODE     → label huruf (A, B, C, ...)
    - Kolom IDSUBSLS → kode unik SLS (cocok dengan GeoJSON)
    - Kolom NAMA SLS → nama dusun (opsional)
    - Kolom MUATAN   → beban kerja petugas

CARA PAKAI:
  python run_from_excel.py

Edit bagian KONFIGURASI di bawah sesuai file lo.
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd

import config
from output_generator import OutputGenerator

# Import modul dari sistem
from partitioner import BalancedPartitioner
from visualizer import MapVisualizer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# =============================================================================
# KONFIGURASI — EDIT BAGIAN INI SESUAI FILE LO
# =============================================================================

# File Excel yang berisi adjacency matrix dan muatan
EXCEL_PATH = "data/matriks_cendana.xlsx"  # ← ganti nama file Excel lo

# Nama sheet di Excel
SHEET_MATRIX = "Sheet1"  # ← sheet adjacency matrix
SHEET_MUATAN = "Sheet2"  # ← sheet muatan/kode

# Nama kolom di sheet muatan (Sheet2)
# Sesuaikan jika nama kolom di Excel lo berbeda
COL_KODE = "KODE"  # kolom label huruf (A, B, C...)
COL_IDSUBSLS = "IDSUBSLS"  # kolom kode SLS
COL_NAMA_SLS = "NAMA SLS"  # kolom nama dusun (opsional)
COL_MUATAN = "MUATAN"  # kolom muatan/beban kerja

# File GeoJSON — hanya untuk geometry (visualisasi)
# Bisa juga None jika tidak mau visualisasi peta
GEOJSON_PATH = "data/final_sls_202517316.geojson"

# Kolom kunci di GeoJSON yang cocok dengan IDSUBSLS di Excel
COL_GEO_KEY = "idsubsls"

# Jumlah petugas sensus
N_OFFICERS = 11

# Output
OUTPUT_EXCEL = "output/hasil_partisi_cendana.xlsx"
OUTPUT_MAP = "output/peta_partisi_cendana.html"

# EPSG metric untuk wilayah (32750 = Sulawesi)
EPSG_METRIC = 32750


# =============================================================================
# FUNGSI UTAMA
# =============================================================================


def load_muatan_mapping(excel_path: str) -> pd.DataFrame:
    """
    Baca sheet muatan dari Excel.
    Returns DataFrame dengan kolom: kode, idsubsls, nama_sls, muatan
    """
    logger.info(f"  Membaca sheet muatan: {SHEET_MUATAN}")
    df = pd.read_excel(excel_path, sheet_name=SHEET_MUATAN)

    # Normalisasi nama kolom (case-insensitive, strip spasi)
    df.columns = [c.strip().upper() for c in df.columns]

    # Cek kolom wajib
    required = [COL_KODE.upper(), COL_IDSUBSLS.upper(), COL_MUATAN.upper()]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.error(
            f"  Kolom tidak ditemukan di sheet muatan: {missing}\n"
            f"  Kolom tersedia: {list(df.columns)}"
        )
        sys.exit(1)

    # Bersihkan data
    df = df.dropna(subset=[COL_KODE.upper(), COL_IDSUBSLS.upper()])
    df[COL_KODE.upper()] = df[COL_KODE.upper()].astype(str).str.strip()
    df[COL_IDSUBSLS.upper()] = df[COL_IDSUBSLS.upper()].astype(str).str.strip()
    df[COL_MUATAN.upper()] = pd.to_numeric(df[COL_MUATAN.upper()], errors="coerce").fillna(0)

    logger.info(f"  {len(df)} SLS dimuat dari sheet muatan")
    return df


def load_adjacency_matrix(excel_path: str, valid_kodes: list) -> pd.DataFrame:
    """
    Baca adjacency matrix dari Sheet1 Excel.
    Returns DataFrame (n x n) dengan index dan kolom = kode huruf (A, B, C...)
    """
    logger.info(f"  Membaca sheet adjacency: {SHEET_MATRIX}")
    df_raw = pd.read_excel(
        excel_path,
        sheet_name=SHEET_MATRIX,
        index_col=0,  # kolom pertama = label baris
        header=0,  # baris pertama = header
    )

    # Bersihkan label
    df_raw.index = [str(i).strip() for i in df_raw.index]
    df_raw.columns = [str(c).strip() for c in df_raw.columns]

    # Filter hanya kode yang ada di sheet muatan (buang baris/kolom kosong)
    valid_set = set(valid_kodes)
    rows_valid = [r for r in df_raw.index if r in valid_set]
    cols_valid = [c for c in df_raw.columns if c in valid_set]

    df_matrix = df_raw.loc[rows_valid, cols_valid].copy()

    # Konversi nilai ke numerik (handle '-', spasi, dll)
    def parse_value(v):
        s = str(v).strip()
        if s in ["-", "", "nan", "None"]:
            return 0  # diagonal atau kosong → tidak ada edge
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return 0

    # applymap diganti map di pandas >= 2.1.0
    df_matrix = (
        df_matrix.map(parse_value) if hasattr(df_matrix, "map") else df_matrix.applymap(parse_value)
    )

    logger.info(f"  Matrix {len(rows_valid)}×{len(cols_valid)} berhasil dibaca")
    return df_matrix


def build_graph_from_excel(
    df_matrix: pd.DataFrame,
    df_muatan: pd.DataFrame,
) -> nx.Graph:
    """
    Bangun NetworkX graph dari adjacency matrix dan muatan.

    Node  = kode SLS (label huruf dari Excel)
    Edge  = ada jika matrix[i][j] == 1
    Atribut node: muatan, idsubsls, nama_sls
    Atribut edge: weight = 1.0 (uniform, karena matrix tidak punya jarak)
    """
    G = nx.Graph()

    # Buat lookup: kode → row muatan
    muatan_lookup = {}
    for _, row in df_muatan.iterrows():
        kode = str(row[COL_KODE.upper()]).strip()
        muatan_lookup[kode] = {
            "muatan": float(row[COL_MUATAN.upper()]),
            "idsubsls": str(row[COL_IDSUBSLS.upper()]).strip(),
            "nama_sls": str(row.get(COL_NAMA_SLS.upper(), "")).strip(),
        }

    # Tambahkan node
    for kode in df_matrix.index:
        info = muatan_lookup.get(kode, {"muatan": 0, "idsubsls": "", "nama_sls": ""})
        G.add_node(
            kode,
            muatan=info["muatan"],
            idsubsls=info["idsubsls"],
            nama_sls=info["nama_sls"],
        )

    # Tambahkan edge dari adjacency matrix
    edges_added = 0
    for kode_a in df_matrix.index:
        for kode_b in df_matrix.columns:
            if kode_a >= kode_b:  # hindari duplikat (matrix simetris)
                continue
            val = df_matrix.loc[kode_a, kode_b]
            if val == 1:
                G.add_edge(kode_a, kode_b, weight=1.0)
                edges_added += 1

    logger.info(f"  Graph: {G.number_of_nodes()} node, {edges_added} edge")

    # Cek konektivitas
    if nx.is_connected(G):
        logger.info("  Graf TERHUBUNG penuh (1 komponen)")
    else:
        n_comp = nx.number_connected_components(G)
        logger.warning(f"  Graf memiliki {n_comp} komponen terpisah!")
        for i, comp in enumerate(sorted(nx.connected_components(G), key=len, reverse=True)):
            logger.warning(f"    Komponen {i + 1}: {sorted(comp)}")

    return G


def load_geometry(
    geojson_path: str,
    df_muatan: pd.DataFrame,
    partition: dict,
) -> gpd.GeoDataFrame:
    """
    Load GeoJSON dan gabungkan hasil partisi untuk visualisasi.
    Mapping: kode huruf → idsubsls → geometry di GeoJSON.
    """
    logger.info(f"  Load geometry dari: {geojson_path}")
    gdf_all = gpd.read_file(geojson_path)
    gdf_all[COL_GEO_KEY] = gdf_all[COL_GEO_KEY].astype(str).str.strip()

    # Buat mapping idsubsls → kode huruf (untuk join ke partisi)
    id_to_kode = {}
    for _, row in df_muatan.iterrows():
        id_to_kode[str(row[COL_IDSUBSLS.upper()]).strip()] = str(row[COL_KODE.upper()]).strip()

    # Buat mapping kode huruf → group_id dari partisi
    # (partisi sudah pakai kode huruf sebagai node)
    kode_to_group = partition  # kode → group_id

    # Filter GeoJSON ke SLS yang relevan
    relevant_ids = set(id_to_kode.keys())
    gdf = gdf_all[gdf_all[COL_GEO_KEY].isin(relevant_ids)].copy()

    # Tambahkan kolom untuk sistem output
    gdf["kode_sls"] = gdf[COL_GEO_KEY].map(id_to_kode)
    gdf["group_id"] = gdf["kode_sls"].map(kode_to_group)
    gdf["muatan"] = (
        gdf["kode_sls"].map({k: G_ref.nodes[k]["muatan"] for k in G_ref.nodes})
        if "G_ref" in globals()
        else 0
    )

    # Centroid untuk visualisasi
    gdf_proj = gdf.to_crs(epsg=EPSG_METRIC)
    centroids = gdf_proj.geometry.centroid.to_crs(epsg=config.EPSG_GEO)
    gdf["centroid_lon"] = centroids.x
    gdf["centroid_lat"] = centroids.y

    logger.info(f"  {len(gdf)} SLS berhasil di-load geometry-nya")
    return gdf


# =============================================================================
# PIPELINE UTAMA
# =============================================================================


def run():
    logger.info("=" * 60)
    logger.info("  PARTISI WILAYAH PETUGAS SENSUS (dari Excel)")
    logger.info("=" * 60)

    # Validasi file
    if not Path(EXCEL_PATH).exists():
        logger.error(f"File Excel tidak ditemukan: {EXCEL_PATH}")
        sys.exit(1)

    # Buat folder output jika belum ada
    Path(OUTPUT_EXCEL).parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Baca sheet muatan
    # ------------------------------------------------------------------
    logger.info("\n[1/6] Membaca data muatan dari Excel...")
    df_muatan = load_muatan_mapping(EXCEL_PATH)
    valid_kodes = df_muatan[COL_KODE.upper()].tolist()

    logger.info("  Preview data:")
    for _, r in df_muatan.iterrows():
        logger.info(
            f"    {r[COL_KODE.upper()]:>4} | "
            f"{r[COL_IDSUBSLS.upper()]} | "
            f"{str(r.get(COL_NAMA_SLS.upper(), '')):<35} | "
            f"muatan={r[COL_MUATAN.upper()]:.0f}"
        )

    # ------------------------------------------------------------------
    # 2. Baca adjacency matrix
    # ------------------------------------------------------------------
    logger.info("\n[2/6] Membaca adjacency matrix dari Excel...")
    df_matrix = load_adjacency_matrix(EXCEL_PATH, valid_kodes)

    # ------------------------------------------------------------------
    # 3. Bangun graph
    # ------------------------------------------------------------------
    logger.info("\n[3/6] Membangun graph...")
    G = build_graph_from_excel(df_matrix, df_muatan)
    global G_ref
    G_ref = G

    # ------------------------------------------------------------------
    # 4. Partisi
    # ------------------------------------------------------------------
    logger.info(f"\n[4/6] Mempartisi {G.number_of_nodes()} SLS ke {N_OFFICERS} petugas...")
    partitioner = BalancedPartitioner(G, n_groups=N_OFFICERS)
    partition = partitioner.run()

    # ------------------------------------------------------------------
    # 5. Output Excel
    # ------------------------------------------------------------------
    logger.info("\n[5/6] Membuat output Excel...")

    # Buat GeoDataFrame minimal untuk OutputGenerator
    # (pakai kode huruf sebagai identifier)
    gdf_out = _build_output_gdf(df_muatan, partition)

    output_gen = OutputGenerator(gdf_out, G, partition, N_OFFICERS)
    output_gen.save_excel(OUTPUT_EXCEL)
    output_gen.print_summary()

    # ------------------------------------------------------------------
    # 6. Visualisasi peta (opsional, butuh GeoJSON)
    # ------------------------------------------------------------------
    logger.info("\n[6/6] Membuat visualisasi peta...")
    if GEOJSON_PATH and Path(GEOJSON_PATH).exists():
        try:
            gdf_geo = _build_geo_gdf(df_muatan, partition)
            viz = MapVisualizer(gdf_geo, partition, N_OFFICERS)
            viz.save_html(OUTPUT_MAP)
            logger.info(f"  Peta tersimpan: {OUTPUT_MAP}")
        except Exception as e:
            logger.warning(f"  Visualisasi gagal: {e}")
    else:
        logger.info("  GeoJSON tidak tersedia, visualisasi dilewati.")

    logger.info("=" * 60)
    logger.info(f"  SELESAI. Output: {OUTPUT_EXCEL}")
    logger.info("=" * 60)


def _build_output_gdf(df_muatan: pd.DataFrame, partition: dict) -> gpd.GeoDataFrame:
    """
    Buat GeoDataFrame minimal (tanpa geometry) untuk OutputGenerator.
    Geometry diisi dengan titik dummy karena visualisasi peta ditangani terpisah.
    """
    from shapely.geometry import Point

    rows = []
    for _, row in df_muatan.iterrows():
        kode = str(row[COL_KODE.upper()]).strip()
        rows.append(
            {
                "kode_sls": kode,
                "muatan": float(row[COL_MUATAN.upper()]),
                "idsubsls": str(row[COL_IDSUBSLS.upper()]).strip(),
                "nama_sls": str(row.get(COL_NAMA_SLS.upper(), "")).strip(),
                "centroid_lon": 0.0,
                "centroid_lat": 0.0,
                "geometry": Point(0, 0),
            }
        )

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=config.EPSG_GEO)
    return gdf


def _build_geo_gdf(df_muatan: pd.DataFrame, partition: dict) -> gpd.GeoDataFrame:
    """
    Buat GeoDataFrame dengan geometry asli dari GeoJSON untuk visualisasi.
    """
    gdf_all = gpd.read_file(GEOJSON_PATH)
    gdf_all[COL_GEO_KEY] = gdf_all[COL_GEO_KEY].astype(str).str.strip()

    # Mapping idsubsls → kode huruf
    id_to_kode = {
        str(row[COL_IDSUBSLS.upper()]).strip(): str(row[COL_KODE.upper()]).strip()
        for _, row in df_muatan.iterrows()
    }
    # Mapping kode huruf → muatan
    kode_to_muatan = {
        str(row[COL_KODE.upper()]).strip(): float(row[COL_MUATAN.upper()])
        for _, row in df_muatan.iterrows()
    }

    # Filter dan tambahkan kolom
    relevant_ids = set(id_to_kode.keys())
    gdf = gdf_all[gdf_all[COL_GEO_KEY].isin(relevant_ids)].copy()
    gdf["kode_sls"] = gdf[COL_GEO_KEY].map(id_to_kode)
    gdf["muatan"] = gdf["kode_sls"].map(kode_to_muatan).fillna(0)

    # Centroid
    gdf_proj = gdf.to_crs(epsg=EPSG_METRIC)
    centroids = gdf_proj.geometry.centroid.to_crs(epsg=config.EPSG_GEO)
    gdf["centroid_lon"] = centroids.x
    gdf["centroid_lat"] = centroids.y

    return gdf


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    run()
