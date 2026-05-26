"""
prepare_data.py
===============
Script persiapan data sebelum menjalankan sistem partisi.

Yang dilakukan script ini:
1. Filter GeoJSON hanya untuk kecamatan tertentu
2. Baca muatan dari file Excel (sheet terpisah)
3. Join muatan ke GeoJSON via idsubsls
4. Simpan file GeoJSON siap pakai

Jalankan script ini SEKALI sebelum main.py.

Cara pakai:
    python prepare_data.py

Atau edit bagian KONFIGURASI di bawah sesuai kebutuhan.
"""

import sys
from pathlib import Path
import pandas as pd
import geopandas as gpd

# =============================================================================
# KONFIGURASI — EDIT BAGIAN INI SESUAI FILE LO
# =============================================================================

# Path file GeoJSON asli (semua kecamatan)
GEOJSON_INPUT = "data/final_sls_202517316.geojson"

# Path file Excel yang berisi muatan
EXCEL_MUATAN = "data/matriks-cendana.xlsx"

# Nama sheet di Excel yang berisi muatan
# Sheet ini harus punya kolom: idsubsls dan muatan
SHEET_MUATAN = "sheet2"   # ← ganti sesuai nama sheet di Excel lo

# Nama kolom di sheet muatan
COL_KEY_EXCEL  = "idsubsls"   # ← kolom kunci di Excel (harus cocok dengan GeoJSON)
COL_MUATAN     = "MUATAN"     # ← kolom nilai muatan di Excel

# Nama kolom kunci di GeoJSON (unique identifier SLS)
COL_KEY_GEO = "idsubsls"

# Kecamatan yang mau diproses (isi nama kecamatan, HURUF KAPITAL)
# Contoh satu kecamatan:
TARGET_KECAMATAN = ["CENDANA"]
# Contoh beberapa kecamatan sekaligus:
# TARGET_KECAMATAN = ["CENDANA", "MAIWA", "ANGGERAJA"]
# Kosongkan untuk proses semua kecamatan:
# TARGET_KECAMATAN = []

# Kolom nama kecamatan di GeoJSON
COL_KECAMATAN = "nmkec"

# File output yang siap dipakai main.py
# (otomatis dinamai berdasarkan kecamatan)
OUTPUT_DIR = "data"

# =============================================================================
# JANGAN UBAH DI BAWAH INI KECUALI PERLU
# =============================================================================

def main():
    print("=" * 55)
    print("  PERSIAPAN DATA SLS")
    print("=" * 55)

    # -------------------------------------------------------------------------
    # 1. Load GeoJSON
    # -------------------------------------------------------------------------
    print(f"\n[1/4] Membaca GeoJSON: {GEOJSON_INPUT}")
    if not Path(GEOJSON_INPUT).exists():
        print(f"  ERROR: File tidak ditemukan — {GEOJSON_INPUT}")
        sys.exit(1)

    gdf = gpd.read_file(GEOJSON_INPUT)
    print(f"  Total SLS di file: {len(gdf)}")
    print(f"  Kecamatan tersedia: {sorted(gdf[COL_KECAMATAN].unique())}")

    # -------------------------------------------------------------------------
    # 2. Filter kecamatan
    # -------------------------------------------------------------------------
    if TARGET_KECAMATAN:
        print(f"\n[2/4] Filter kecamatan: {TARGET_KECAMATAN}")
        gdf = gdf[gdf[COL_KECAMATAN].isin(TARGET_KECAMATAN)].copy()
        print(f"  SLS setelah filter: {len(gdf)}")

        if gdf.empty:
            print(
                f"  ERROR: Tidak ada SLS ditemukan untuk {TARGET_KECAMATAN}.\n"
                f"  Periksa nama kecamatan (harus huruf kapital persis)."
            )
            sys.exit(1)
    else:
        print(f"\n[2/4] Tidak ada filter kecamatan — proses semua ({len(gdf)} SLS)")

    # -------------------------------------------------------------------------
    # 3. Baca muatan dari Excel
    # -------------------------------------------------------------------------
    print(f"\n[3/4] Membaca muatan dari Excel: {EXCEL_MUATAN}")

    if not Path(EXCEL_MUATAN).exists():
        print(f"  PERINGATAN: File Excel tidak ditemukan — {EXCEL_MUATAN}")
        print(f"  Menggunakan kolom 'luas' sebagai proxy muatan.")
        gdf["muatan"] = (gdf["luas"] * 100).round(0).astype(int)
        print(f"  Muatan dari luas × 100: min={gdf['muatan'].min()}, max={gdf['muatan'].max()}")

    else:
        # Cek sheet yang tersedia
        xl = pd.ExcelFile(EXCEL_MUATAN)
        print(f"  Sheet tersedia di Excel: {xl.sheet_names}")

        if SHEET_MUATAN not in xl.sheet_names:
            print(
                f"  ERROR: Sheet '{SHEET_MUATAN}' tidak ditemukan.\n"
                f"  Sheet yang ada: {xl.sheet_names}\n"
                f"  Ubah SHEET_MUATAN di bagian KONFIGURASI."
            )
            sys.exit(1)

        df_muatan = pd.read_excel(EXCEL_MUATAN, sheet_name=SHEET_MUATAN)
        df_muatan.columns = [c.strip().lower() for c in df_muatan.columns]

        print(f"  Kolom di sheet muatan: {list(df_muatan.columns)}")
        print(f"  Jumlah baris: {len(df_muatan)}")

        # Validasi kolom kunci
        if COL_KEY_EXCEL not in df_muatan.columns:
            print(
                f"  ERROR: Kolom '{COL_KEY_EXCEL}' tidak ditemukan di sheet muatan.\n"
                f"  Kolom tersedia: {list(df_muatan.columns)}\n"
                f"  Ubah COL_KEY_EXCEL di bagian KONFIGURASI."
            )
            sys.exit(1)

        if COL_MUATAN not in df_muatan.columns:
            print(
                f"  ERROR: Kolom '{COL_MUATAN}' tidak ditemukan di sheet muatan.\n"
                f"  Kolom tersedia: {list(df_muatan.columns)}\n"
                f"  Ubah COL_MUATAN di bagian KONFIGURASI."
            )
            sys.exit(1)

        # Pastikan tipe data konsisten untuk join
        df_muatan[COL_KEY_EXCEL] = df_muatan[COL_KEY_EXCEL].astype(str).str.strip()
        gdf[COL_KEY_GEO]         = gdf[COL_KEY_GEO].astype(str).str.strip()

        # Join muatan ke GeoDataFrame
        df_muatan_clean = df_muatan[[COL_KEY_EXCEL, COL_MUATAN]].rename(
            columns={COL_KEY_EXCEL: COL_KEY_GEO}
        )

        n_before = len(gdf)
        gdf = gdf.merge(df_muatan_clean, on=COL_KEY_GEO, how="left")

        # Cek hasil join
        n_matched = gdf[COL_MUATAN].notna().sum()
        n_missing = gdf[COL_MUATAN].isna().sum()

        print(f"  Join berhasil: {n_matched} SLS dapat muatan")
        if n_missing > 0:
            missing_ids = gdf.loc[gdf[COL_MUATAN].isna(), COL_KEY_GEO].tolist()
            print(
                f"  PERINGATAN: {n_missing} SLS tidak ada di Excel (muatan di-set 0):\n"
                f"    {missing_ids[:10]}{'...' if len(missing_ids) > 10 else ''}"
            )
            gdf[COL_MUATAN] = gdf[COL_MUATAN].fillna(0)

        gdf[COL_MUATAN] = pd.to_numeric(gdf[COL_MUATAN], errors="coerce").fillna(0)
        print(f"  Muatan: min={gdf[COL_MUATAN].min():.0f}, max={gdf[COL_MUATAN].max():.0f}, total={gdf[COL_MUATAN].sum():.0f}")

    # -------------------------------------------------------------------------
    # 4. Tambahkan kolom kode_sls dan simpan
    # -------------------------------------------------------------------------
    print(f"\n[4/4] Menyimpan file output...")

    # Kolom kode_sls wajib ada untuk main.py
    gdf["kode_sls"] = gdf[COL_KEY_GEO].astype(str)

    # Tentukan nama file output
    if TARGET_KECAMATAN:
        suffix = "_".join(
            [k.lower().replace(" ", "_") for k in TARGET_KECAMATAN]
        )
        output_path = f"{OUTPUT_DIR}/sls_{suffix}.geojson"
    else:
        output_path = f"{OUTPUT_DIR}/sls_all.geojson"

    # Kolom yang disimpan (geometry selalu disertakan otomatis)
    cols_to_save = ["kode_sls", "muatan", COL_KEY_GEO, "nmkec", "nmdesa", "nmsls"]
    cols_to_save = [c for c in cols_to_save if c in gdf.columns]

    gdf[cols_to_save].to_file(output_path, driver="GeoJSON")

    print(f"  File tersimpan: {output_path}")
    print(f"  Jumlah SLS: {len(gdf)}")
    print(f"  Total muatan: {gdf['muatan'].sum():,.0f}")
    print(f"  Target/petugas (jika 11 petugas): {gdf['muatan'].sum()/11:,.0f}")

    print()
    print("=" * 55)
    print("  SIAP. Sekarang jalankan:")
    print(f"  python main.py {output_path} 11")
    print("=" * 55)


if __name__ == "__main__":
    main()