# Sistem Partisi Wilayah Petugas Sensus

Aplikasi berbasis Streamlit untuk membagi wilayah SubSLS (Sub-Lingkungan Setempat) kepada petugas sensus secara otomatis, mempertimbangkan aksesibilitas geografis dan keseimbangan beban kerja.

---

## Fitur Utama

- **Pilih area** yang ingin dipartisi berdasarkan kecamatan, desa, SLS, atau SubSLS
- **Bangun matriks koneksi** antar SubSLS secara otomatis menggunakan jaringan jalan OpenStreetMap (OSM) dan deteksi polygon bersinggungan
- **Partisi seimbang** — minimisasi selisih beban kerja (muatan) antara petugas yang paling banyak dan paling sedikit
- **Prioritas satu desa per petugas** — soft constraint opsional agar setiap petugas mendapat wilayah dalam satu desa
- **Visualisasi peta interaktif** dengan warna per petugas
- **Download hasil** dalam format Excel dan CSV

---

## Persyaratan

### Dependensi Python

```bash
pip install -r requirements.txt
```

### Format GeoJSON

File GeoJSON harus memiliki kolom-kolom berikut di setiap feature:

| Kolom | Contoh | Keterangan |
|---|---|---|
| `idsubsls` | `"7316010018000200"` | Identifier unik SubSLS (wajib) |
| `Perkiraan_Jumlah_Muatan` | `242.5` | Beban kerja per SubSLS (wajib, nama kolom bisa dikustomisasi) |
| `nmkec` | `"MAIWA"` | Nama kecamatan (untuk filter area) |
| `nmdesa` | `"LIMBUANG"` | Nama desa (untuk filter area & prioritas desa) |
| `nmsls` | `"DUSUN LIMBUANG"` | Nama SLS (untuk filter area & label) |
| `kdsubsls` | `"01"` | Kode SubSLS (untuk label tooltip peta) |

> **Catatan:** Kolom muatan (`Perkiraan_Jumlah_Muatan`) harus sudah ada di dalam GeoJSON sebelum digunakan. Jika muatan masih di file Excel terpisah, lakukan merge terlebih dahulu menggunakan `idsubsls` sebagai key.

Simpan file GeoJSON ke dalam folder `data/` agar bisa dipilih langsung dari dropdown aplikasi.

---

## Menjalankan Aplikasi

```bash
streamlit run app.py
```

Buka browser dan akses **http://localhost:8501**

---

## Panduan Penggunaan

### Langkah 1 — Pilih File GeoJSON

Di **sidebar sebelah kiri**, pilih sumber file GeoJSON:

- **Pilih dari /data** — aplikasi otomatis mendeteksi file `.geojson` di folder `data/`. Pilih file dari dropdown.
- **Upload file** — upload file GeoJSON langsung dari komputer.

Isi kolom **"Kolom muatan di GeoJSON"** sesuai nama kolom muatan di file kamu (default: `Perkiraan_Jumlah_Muatan`).

---

### Langkah 2 — Pilih Area (Tab "Pilih Area")

Buka tab **🗂️ Pilih Area** untuk memilih SubSLS yang akan dipartisi.

Tersedia 4 filter multi-select (pilih salah satu atau kombinasi, kosongkan = semua):

| Filter | Keterangan |
|---|---|
| **Kecamatan** | Filter berdasarkan nama kecamatan |
| **Desa / Kelurahan** | Filter berdasarkan nama desa |
| **SLS** | Filter berdasarkan nama SLS |
| **SubSLS (idsubsls)** | Filter berdasarkan kode idsubsls spesifik |

Filter dikombinasikan dengan logika **AND**. Contoh: pilih kecamatan "MAIWA" dan desa "LIMBUANG" → hanya SubSLS yang ada di MAIWA **dan** LIMBUANG yang masuk.

Setelah memilih filter, tampil:
- **Ringkasan seleksi** — jumlah SubSLS terpilih, total muatan, rata-rata muatan per SubSLS
- **Preview peta** — warna biru = terpilih, abu = tidak terpilih

---

### Langkah 3 — Atur Parameter

Di sidebar, atur:

| Parameter | Keterangan |
|---|---|
| **Jumlah Petugas** | Berapa petugas yang akan bertugas di area terpilih (1–50) |

Di bagian **⚡ Parameter Lanjutan**:

| Parameter | Default | Keterangan |
|---|---|---|
| **Jumlah Restart** | 20 | Berapa kali algoritma diulang untuk menemukan solusi terbaik. Makin banyak = hasil lebih baik tapi lebih lama. |
| **Prioritas satu desa per petugas** | Off | Centang untuk mengaktifkan preferensi agar setiap petugas mendapat SubSLS dari satu desa saja. |
| **Toleransi lintas desa** | 500 | Muncul jika prioritas desa aktif. Nilai penalti per petugas yang lintas desa. Makin tinggi = makin ketat. Makin rendah = makin longgar (boleh lintas desa jika gap-nya membaik signifikan). |

---

### Langkah 4 — Jalankan Partisi

Klik tombol **▶ Jalankan Partisi** di sidebar.

Proses yang berjalan:
1. **Bangun matriks koneksi** — download jaringan jalan OSM, snap centroid SubSLS ke node jalan terdekat, hitung jarak antar SubSLS, buat weighted graph
2. **Partisi** — algoritma multi-start region growing + local search, minimize selisih muatan maks-min

> **Catatan:** Proses download OSM membutuhkan koneksi internet. Jika tidak tersedia, sistem otomatis fallback ke deteksi polygon bersinggungan saja.

---

### Langkah 5 — Lihat Hasil

#### Tab 📊 Hasil Partisi

Menampilkan:

| Metrik | Keterangan |
|---|---|
| **Total SLS** | Jumlah SubSLS yang dipartisi |
| **Petugas** | Jumlah kelompok/petugas |
| **Maks Muatan** | Muatan petugas dengan beban terberat |
| **Min Muatan** | Muatan petugas dengan beban teringan |
| **Gap Muatan** | Selisih maks-min (makin kecil makin baik) |
| **Lintas Desa** | Jumlah petugas yang mendapat SubSLS dari lebih dari satu desa |

Juga tersedia:
- **Tabel ringkasan per petugas** — jumlah SLS, total muatan, daftar SLS (nama + kode SubSLS), status konektivitas
- **Bar chart** distribusi muatan per petugas
- **Detail per SubSLS** (expandable) — tabel lengkap semua SubSLS dan penugasannya

#### Tab 🗺️ Peta

Peta interaktif dengan warna berbeda per petugas. Hover di atas polygon untuk melihat:
- `idsubsls`
- Nama SLS + kode SubSLS
- Jumlah muatan
- Nomor petugas

---

### Langkah 6 — Download Hasil

Di tab **Hasil Partisi**, tersedia tombol download:

| Format | Isi |
|---|---|
| **Excel (.xlsx)** | Sheet "Ringkasan" (per petugas) + Sheet "Detail SLS" (per SubSLS) |
| **CSV** | Satu baris per SubSLS: idsubsls, muatan, petugas, group_id |

---

## Struktur Folder

```
cencus_partitioner/
├── app.py                  # Aplikasi Streamlit (entry point)
├── partitioner.py          # Algoritma partisi utama
├── matrix_builder.py       # Builder weighted graph dari GeoJSON
├── adjacency_builder.py    # Deteksi adjacency antar SubSLS
├── road_network.py         # Handler jaringan jalan OSM
├── config.py               # Konfigurasi parameter algoritma
├── requirements.txt        # Dependensi Python
├── data/                   # Folder untuk file GeoJSON input
│   └── *.geojson
└── output/                 # Folder output (untuk CLI)
```

---

## Konfigurasi Lanjutan (config.py)

Parameter di `config.py` bisa disesuaikan untuk hasil yang lebih optimal:

| Parameter | Default | Keterangan |
|---|---|---|
| `EPSG_METRIC` | `32750` | UTM zone. Sulawesi/Kalimantan: 32750, Jawa Tengah-Timur/Bali: 32749, Sumatera/Jawa Barat: 32748 |
| `ROAD_DISTANCE_THRESHOLD_M` | `8000` | Jarak jalan maksimum (meter) untuk membuat edge antar SubSLS |
| `N_RESTARTS` | `15` | Jumlah restart default algoritma |
| `IMBALANCE_TOLERANCE_MAXMIN` | `50` | Gap maks-min yang dianggap cukup baik untuk early stop |
| `DESA_PENALTY_DEFAULT` | `500` | Penalti default per petugas lintas desa |
| `TOUCHING_ONLY` | `False` | Jika `True`, hanya gunakan polygon touching (tanpa OSM) |

---

## Tips Penggunaan

- **Area kecil (< 50 SubSLS):** Kurangi jumlah restart ke 5–10 agar lebih cepat.
- **Area besar (> 300 SubSLS):** Tambah restart ke 30–50 untuk hasil lebih optimal.
- **OSM lambat:** Set `TOUCHING_ONLY = True` di `config.py` untuk skip download OSM.
- **Prioritas desa:** Mulai dari toleransi 300–500. Jika hasilnya masih banyak lintas desa, naikkan ke 1000–2000.
- **Gap masih besar:** Tambah jumlah restart atau kurangi jumlah petugas.
