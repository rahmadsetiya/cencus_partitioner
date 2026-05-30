"""
config.py
=========
Konfigurasi global sistem partisi wilayah sensus.
Sesuaikan parameter ini sesuai kondisi lapangan.
"""

# =============================================================================
# ROAD NETWORK SETTINGS
# =============================================================================

# Jarak maksimum centroid ke node jalan terdekat (meter).
# Node yang lebih jauh dari ini dianggap tidak memiliki akses jalan di OSM —
# fallback ke polygon touching.
MAX_SNAP_DISTANCE_M = 500

# Threshold jarak jalan (meter) untuk membuat edge antar dua SLS.
# SLS yang jaraknya di atas ini via jaringan jalan tidak akan dihubungkan,
# kecuali polygon mereka bersinggungan langsung.
ROAD_DISTANCE_THRESHOLD_M = 8_000

# Tipe jaringan jalan untuk OSMnx.
# "drive"  → jalan yang bisa dilalui kendaraan
# "walk"   → semua jalur termasuk pejalan kaki
# "all"    → semua edge di OSM
NETWORK_TYPE = "drive"

# Buffer tambahan di luar bounding box SLS untuk download OSM (derajat).
# ~0.05° ≈ 5.5 km. Perbesar jika ada SLS di pinggir wilayah.
OSM_BUFFER_DEG = 0.05

# =============================================================================
# ADJACENCY SETTINGS
# =============================================================================

# Buffer (meter) untuk deteksi polygon touching.
# Diperlukan karena floating-point precision geometry.
TOUCHING_BUFFER_M = 2.0

# Jika True, hanya polygon yang bersinggungan yang dijadikan kandidat edge.
# Jika False, semua pasangan SLS dalam ROAD_DISTANCE_THRESHOLD bisa jadi edge.
# Rekomendasi: True untuk wilayah padat, False untuk wilayah terpencil.
TOUCHING_ONLY = False

# =============================================================================
# DIFFICULTY / EDGE WEIGHT SETTINGS
# =============================================================================

# Difficulty score edge dihitung sebagai:
#   weight = WEIGHT_DISTANCE * (road_dist_m / 1000)
#           + WEIGHT_TOUCHING * (0 jika touching, 1 jika tidak)
# Makin kecil weight → akses makin mudah.

WEIGHT_DISTANCE = 1.0  # bobot untuk jarak jalan (km)
WEIGHT_TOUCHING = 0.5  # penalti jika polygon tidak bersinggungan langsung

# Jika OSM gagal, edge dari polygon touching diberi weight default ini (km).
DEFAULT_TOUCHING_WEIGHT = 1.0

# =============================================================================
# PARTITIONING ALGORITHM SETTINGS
# =============================================================================

# Jumlah restart multi-start. Makin banyak → hasil lebih baik, tapi lebih lama.
N_RESTARTS = 15

# Jumlah maksimum iterasi local search per restart.
MAX_LOCAL_SEARCH_ITER = 2_000

# Tolerance imbalance yang diterima (rasio terhadap mean). Dipakai oleh _imbalance_cv (referensi).
IMBALANCE_TOLERANCE = 0.05

# Tolerance untuk objektif max-min (satuan muatan absolut).
# Berhenti lebih awal jika selisih maks-min ≤ nilai ini.
IMBALANCE_TOLERANCE_MAXMIN = 50

# Penalti default per petugas yang mendapat SubSLS dari lebih dari satu desa.
# score = gap + DESA_PENALTY × jumlah_petugas_lintas_desa
DESA_PENALTY_DEFAULT = 500

# =============================================================================
# CRS SETTINGS
# =============================================================================

# EPSG untuk proyeksi metrik (UTM).
# 32750 = WGS84 / UTM Zone 50S → cocok untuk Sulawesi, Kalimantan, Maluku.
# 32748 = WGS84 / UTM Zone 48S → cocok untuk Sumatera, Jawa barat.
# 32749 = WGS84 / UTM Zone 49S → cocok untuk Jawa tengah-timur, Bali, NTB.
EPSG_METRIC = 32750

# EPSG untuk output koordinat (WGS84 geographic).
EPSG_GEO = 4326

# =============================================================================
# OUTPUT SETTINGS
# =============================================================================

OUTPUT_EXCEL = "hasil_partisi.xlsx"
OUTPUT_MAP_HTML = "peta_partisi.html"

# Nama kolom wajib di GeoJSON
COL_KODE_SLS = "kode_sls"
COL_MUATAN = "muatan"
COL_MUATAN_GEO = "muatan"  # nama kolom muatan default di GeoJSON
