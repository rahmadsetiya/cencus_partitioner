# Sistem Partisi Wilayah Petugas Sensus

Sistem otomatis pembagian SLS (Satuan Lingkungan Setempat) ke petugas sensus,
mempertimbangkan konektivitas wilayah nyata dan keseimbangan muatan.

---

## Fitur Utama

- **Hybrid adjacency**: polygon touching + validasi jarak jalan OSM
- **Connected partition**: setiap kelompok dijamin terhubung secara geografis
- **Balanced load**: total muatan antar petugas semaksimal mungkin seimbang
- **Manual override**: koreksi adjacency dari pengetahuan lapangan via Excel
- **Visualisasi interaktif**: peta HTML berwarna per petugas
- **Output Excel**: laporan lengkap per SLS dan per petugas

---

## Instalasi

```bash
# Clone / copy project ke direktori kerja
cd census_partitioner/

# Install dependencies
pip install -r requirements.txt
```

> **Catatan**: `osmnx` membutuhkan internet untuk download data OSM.
> Jika tidak ada koneksi, sistem akan otomatis fallback ke polygon touching.

---

## Cara Penggunaan

### Minimal (CLI)

```bash
python main.py data/sls_enrekang.geojson 10
```

### Dengan override dan pengaturan lengkap

```bash
python main.py data/sls.geojson 8 \
    --override koreksi_lapangan.xlsx \
    --output-excel hasil_partisi_2026.xlsx \
    --output-map peta_petugas.html \
    --epsg 32750 \
    --restarts 20
```

### Generate template override

```bash
python main.py sls.geojson 1 --generate-template
```

### Via Python

```python
from main import run_pipeline

partition = run_pipeline(
    geojson_path="data/sls_enrekang.geojson",
    n_officers=10,
    override_path="koreksi.xlsx",
    output_excel="hasil.xlsx",
    output_map="peta.html",
    epsg_metric=32750,  # UTM Zone 50S (Sulawesi)
)
# partition = {'SLS_001': 0, 'SLS_002': 1, ...}
```

---

## Format Input GeoJSON

File GeoJSON harus berisi **Polygon** atau **MultiPolygon** dengan atribut minimal:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [...] },
      "properties": {
        "kode_sls": "1234567890",
        "muatan": 150
      }
    }
  ]
}
```

| Kolom      | Tipe    | Keterangan                           |
|------------|---------|--------------------------------------|
| `kode_sls` | string  | Kode unik SLS (bisa numerik atau teks) |
| `muatan`   | integer | Jumlah rumah tangga / muatan petugas |

---

## Format manual_override.xlsx

File Excel dengan dua sheet:

### Sheet `force_connect`

| kode_sls_a | kode_sls_b | catatan                    |
|------------|------------|----------------------------|
| SLS_001    | SLS_003    | Akses via jembatan desa    |
| SLS_015    | SLS_020    | Jalur setapak diketahui    |

### Sheet `force_disconnect`

| kode_sls_a | kode_sls_b | catatan                          |
|------------|------------|----------------------------------|
| SLS_007    | SLS_008    | Sungai tanpa jembatan            |
| SLS_012    | SLS_013    | Akses terputus musim hujan       |

---

## Parameter Konfigurasi (config.py)

| Parameter                  | Default  | Keterangan                                          |
|----------------------------|----------|-----------------------------------------------------|
| `ROAD_DISTANCE_THRESHOLD_M`| 8000     | Jarak maks antar SLS via jalan (meter)              |
| `MAX_SNAP_DISTANCE_M`      | 500      | Jarak maks centroid ke node jalan OSM (meter)       |
| `TOUCHING_ONLY`            | False    | True: hanya polygon touching yang jadi edge         |
| `N_RESTARTS`               | 15       | Jumlah restart algoritma (lebih banyak = lebih baik)|
| `MAX_LOCAL_SEARCH_ITER`    | 2000     | Iterasi maksimum local search per restart           |
| `EPSG_METRIC`              | 32750    | CRS proyeksi metrik (32750=Sulawesi, 32749=Jawa Timur) |

---

## Arsitektur Sistem

```
main.py                    ← Orkestrasi pipeline
├── data_loader.py         ← Load & validasi GeoJSON
├── road_network.py        ← Download OSM, snap centroid
├── adjacency_builder.py   ← Bangun weighted graph
├── manual_override.py     ← Terapkan koreksi lapangan
├── partitioner.py         ← Algoritma partisi utama
├── output_generator.py    ← Export Excel
├── visualizer.py          ← Peta HTML interaktif
└── config.py              ← Konfigurasi global
```

### Algoritma Partisi (partitioner.py)

```
1. Seed Selection (k-means++ style)
   └── Pilih n node yang tersebar di seluruh wilayah

2. Region Growing
   └── Min-heap: selalu ekspansi grup dengan muatan terkecil
       → mendorong distribusi yang seimbang secara organik

3. Local Search
   └── Swap boundary nodes antar grup tetangga
       Constraint: source grup harus tetap connected setelah swap
       Stop: tidak ada improvement atau max iterasi tercapai

4. Multi-restart (N_RESTARTS kali)
   └── Simpan solusi dengan Coefficient of Variation (CV) terkecil
```

---

## Pemilihan EPSG (UTM Zone)

| Wilayah                       | EPSG  |
|-------------------------------|-------|
| Sulawesi, Kalimantan, Maluku  | 32750 |
| Jawa Tengah, Timur, Bali, NTB | 32749 |
| Sumatera, Jawa Barat          | 32748 |
| Papua                         | 32754 |

---

## Output

### `hasil_partisi.xlsx`

- **Sheet Ringkasan**: statistik per petugas (muatan, jumlah SLS, travel cost, status connected)
- **Sheet Detail SLS**: setiap SLS dengan assignment petugas dan koordinat centroid
- **Sheet Adjacency Graph**: semua edge dalam graph untuk audit

### `peta_partisi.html`

Peta interaktif (buka di browser):
- Polygon SLS diwarnai berbeda per petugas
- Hover: info singkat (kode, muatan, petugas)
- Klik: detail lengkap
- Toggle per layer petugas
- Pilihan basemap: CartoDB, OSM, Satelit

---

## Troubleshooting

**OSM download lambat atau gagal**

```python
# Di config.py, perkecil buffer:
OSM_BUFFER_DEG = 0.02

# Atau aktifkan polygon-only mode:
TOUCHING_ONLY = True
```

**Graf tidak terhubung (disconnected)**

Tambahkan entri `force_connect` di manual_override.xlsx untuk
menghubungkan SLS yang terisolir secara administratif.

**Keseimbangan kurang optimal**

Tambahkan jumlah restart:
```bash
python main.py sls.geojson 10 --restarts 50
```

**Geometry invalid**

Sistem otomatis mencoba repair. Jika tetap gagal, perbaiki GeoJSON dulu:
```python
import geopandas as gpd
from shapely.validation import make_valid
gdf = gpd.read_file("sls.geojson")
gdf.geometry = gdf.geometry.apply(make_valid)
gdf.to_file("sls_fixed.geojson", driver="GeoJSON")
```

---

## Catatan Lapangan Sensus Indonesia

- OSM di wilayah pedesaan Indonesia seringkali **tidak lengkap**.
  Sistem sudah punya fallback ke polygon touching.
- Jarak jalan di OSM bisa **berbeda signifikan** dengan kondisi nyata
  (jalan rusak, musim hujan). Gunakan manual_override untuk koreksi.
- Muatan 0 dipertahankan tapi diberi warning — cek kembali datanya.
- Untuk SE2026: `muatan` biasanya = jumlah usaha/rumah tangga per SLS.
