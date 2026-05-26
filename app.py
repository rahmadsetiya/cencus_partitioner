"""
app.py
======
UI berbasis Streamlit untuk sistem partisi wilayah petugas sensus.

Cara menjalankan:
    streamlit run app.py

Pastikan sudah install:
    pip install streamlit streamlit-folium
"""

import io
import tempfile
import traceback
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import streamlit as st

# ─────────────────────────────────────────────
# PAGE CONFIG (harus paling atas)
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Partisi Wilayah Sensus",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
}

/* Header utama */
.main-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    padding: 2rem 2.5rem;
    border-radius: 12px;
    margin-bottom: 1.5rem;
    border-left: 5px solid #e94560;
}
.main-header h1 {
    color: #ffffff;
    font-size: 1.8rem;
    font-weight: 700;
    margin: 0 0 0.3rem 0;
    letter-spacing: -0.5px;
}
.main-header p {
    color: #8892b0;
    font-size: 0.9rem;
    margin: 0;
    font-family: 'IBM Plex Mono', monospace;
}

/* Metric cards */
.metric-card {
    background: #ffffff;
    border: 1px solid #e8ecf0;
    border-radius: 10px;
    padding: 1.2rem 1.5rem;
    text-align: center;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.metric-card .label {
    font-size: 0.75rem;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-weight: 600;
    margin-bottom: 0.4rem;
}
.metric-card .value {
    font-size: 1.8rem;
    font-weight: 700;
    color: #111827;
    font-family: 'IBM Plex Mono', monospace;
}
.metric-card .sub {
    font-size: 0.78rem;
    color: #9ca3af;
    margin-top: 0.2rem;
}

/* Badge connected */
.badge-ok   { background:#d1fae5; color:#065f46; padding:3px 10px; border-radius:99px; font-size:0.75rem; font-weight:600; }
.badge-warn { background:#fee2e2; color:#991b1b; padding:3px 10px; border-radius:99px; font-size:0.75rem; font-weight:600; }

/* Tabel hasil */
.result-table th {
    background: #f3f4f6 !important;
    font-weight: 600 !important;
    font-size: 0.82rem !important;
}

/* Section titles */
.section-title {
    font-size: 0.85rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #374151;
    border-bottom: 2px solid #e94560;
    padding-bottom: 6px;
    margin: 1.5rem 0 1rem 0;
    display: inline-block;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: #f8fafc;
    border-right: 1px solid #e2e8f0;
}

/* Hide streamlit branding */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# IMPORT MODUL SISTEM (dengan error handling)
# ─────────────────────────────────────────────
@st.cache_resource
def import_modules():
    """Import modul partisi — di-cache agar tidak reimport tiap interaksi."""
    try:
        from partitioner import BalancedPartitioner
        from output_generator import OutputGenerator
        import config
        return BalancedPartitioner, OutputGenerator, config, None
    except ImportError as e:
        return None, None, None, str(e)


BalancedPartitioner, OutputGenerator, config, import_error = import_modules()


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
GROUP_COLORS = [
    "#4472C4","#ED7D31","#70AD47","#FF6B6B","#FFD700",
    "#9B59B6","#1ABC9C","#E67E22","#3498DB","#E74C3C",
    "#2ECC71","#F39C12","#8E44AD","#16A085","#C0392B",
    "#27AE60","#2980B9","#D35400","#7F8C8D","#BDC3C7",
]

EPSG_OPTS = {
    "32750 — Sulawesi, Kalimantan, Maluku": 32750,
    "32749 — Jawa Tengah/Timur, Bali, NTB": 32749,
    "32748 — Sumatera, Jawa Barat":         32748,
    "32754 — Papua":                         32754,
}


# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def load_geojson_bytes(uploaded_file) -> gpd.GeoDataFrame:
    """Load GeoJSON dari UploadedFile Streamlit."""
    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name
    gdf = gpd.read_file(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)
    return gdf


def build_graph_from_excel(
    excel_bytes,
    sheet_matrix: str,
    sheet_muatan: str,
    col_kode: str,
    col_idsubsls: str,
    col_muatan: str,
    col_nama: str,
) -> tuple:
    """
    Baca Excel dan bangun NetworkX graph.
    Returns: (G, df_muatan, error_msg)
    """
    try:
        xl = pd.ExcelFile(excel_bytes)

        # ── Sheet muatan ──
        df_m = pd.read_excel(xl, sheet_name=sheet_muatan)
        df_m.columns = [c.strip().upper() for c in df_m.columns]

        ck  = col_kode.upper()
        cid = col_idsubsls.upper()
        cm  = col_muatan.upper()
        cn  = col_nama.upper() if col_nama else None

        for req in [ck, cid, cm]:
            if req not in df_m.columns:
                return None, None, f"Kolom '{req}' tidak ditemukan di sheet muatan.\nKolom ada: {list(df_m.columns)}"

        df_m = df_m.dropna(subset=[ck, cid])
        df_m[ck]  = df_m[ck].astype(str).str.strip()
        df_m[cid] = df_m[cid].astype(str).str.strip()
        df_m[cm]  = pd.to_numeric(df_m[cm], errors="coerce").fillna(0)

        valid_kodes = df_m[ck].tolist()

        # ── Sheet matrix ──
        df_raw = pd.read_excel(xl, sheet_name=sheet_matrix, index_col=0, header=0)
        df_raw.index   = [str(i).strip() for i in df_raw.index]
        df_raw.columns = [str(c).strip() for c in df_raw.columns]

        valid_set = set(valid_kodes)
        rows_v = [r for r in df_raw.index   if r in valid_set]
        cols_v = [c for c in df_raw.columns if c in valid_set]
        df_mat = df_raw.loc[rows_v, cols_v].copy()

        def parse_val(v):
            s = str(v).strip()
            if s in ["-", "", "nan", "None"]:
                return 0
            try:
                return int(float(s))
            except (ValueError, TypeError):
                return 0

        df_mat = df_mat.map(parse_val) if hasattr(df_mat, "map") else df_mat.applymap(parse_val)

        # ── Build graph ──
        G = nx.Graph()
        muatan_lkp = {
            str(r[ck]): {
                "muatan":   float(r[cm]),
                "idsubsls": str(r[cid]),
                "nama_sls": str(r.get(cn, "")) if cn and cn in df_m.columns else "",
            }
            for _, r in df_m.iterrows()
        }

        for kode in df_mat.index:
            info = muatan_lkp.get(kode, {"muatan": 0, "idsubsls": "", "nama_sls": ""})
            G.add_node(kode, **info)

        edges = 0
        for ka in df_mat.index:
            for kb in df_mat.columns:
                if ka >= kb:
                    continue
                if df_mat.loc[ka, kb] == 1:
                    G.add_edge(ka, kb, weight=1.0)
                    edges += 1

        return G, df_m, None

    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"


def build_graph_from_geojson(
    gdf: gpd.GeoDataFrame,
    col_kode: str,
    col_muatan: str,
    epsg: int,
    touching_buffer: float = 2.0,
) -> tuple:
    """
    Auto-build graph dari polygon touching.
    Returns: (G, error_msg)
    """
    try:
        from shapely.strtree import STRtree

        gdf_proj = gdf.to_crs(epsg=epsg)
        kodes = list(gdf_proj[col_kode].astype(str))
        geoms = list(gdf_proj.geometry)

        G = nx.Graph()
        for _, row in gdf.iterrows():
            G.add_node(
                str(row[col_kode]),
                muatan=float(row.get(col_muatan, 1)),
            )

        buffered = [g.buffer(touching_buffer) for g in geoms]
        tree = STRtree(buffered)
        edges = 0
        for i, (ka, buf_a) in enumerate(zip(kodes, buffered)):
            for j in tree.query(buf_a):
                if j <= i:
                    continue
                kb = kodes[j]
                if geoms[i].distance(geoms[j]) <= touching_buffer * 2:
                    G.add_edge(ka, kb, weight=1.0)
                    edges += 1

        return G, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def run_partisi(G: nx.Graph, n_officers: int) -> tuple:
    """Jalankan partisi. Returns: (partition, error_msg)"""
    try:
        config.N_RESTARTS = 20
        partitioner = BalancedPartitioner(G, n_groups=n_officers)
        partition   = partitioner.run()
        return partition, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"


def compute_stats(G: nx.Graph, partition: dict, n_officers: int) -> list:
    """Hitung statistik per grup."""
    stats = []
    for gid in range(n_officers):
        nodes = [n for n, g in partition.items() if g == gid]
        if not nodes:
            continue
        loads = [G.nodes[n].get("muatan", 0) for n in nodes]
        subg  = G.subgraph(nodes)
        stats.append({
            "Petugas":    f"Petugas {gid + 1}",
            "Jml SLS":    len(nodes),
            "Total Muatan": int(sum(loads)),
            "Min SLS":    int(min(loads)),
            "Max SLS":    int(max(loads)),
            "Connected":  nx.is_connected(subg) if len(nodes) > 1 else True,
            "SLS List":   sorted(nodes),
            "group_id":   gid,
        })
    return stats


def make_excel_bytes(
    G: nx.Graph,
    partition: dict,
    n_officers: int,
    df_muatan_ref: pd.DataFrame = None,
) -> bytes:
    """Generate Excel output sebagai bytes untuk download."""
    stats = compute_stats(G, partition, n_officers)

    # Sheet ringkasan
    df_sum = pd.DataFrame([{
        "Petugas":      s["Petugas"],
        "Jumlah SLS":   s["Jml SLS"],
        "Total Muatan": s["Total Muatan"],
        "Connected":    "Ya" if s["Connected"] else "TIDAK",
        "Daftar SLS":   ", ".join(s["SLS List"]),
    } for s in stats])

    # Sheet detail
    rows = []
    for node, gid in partition.items():
        rows.append({
            "kode":     node,
            "muatan":   G.nodes[node].get("muatan", 0),
            "idsubsls": G.nodes[node].get("idsubsls", ""),
            "nama_sls": G.nodes[node].get("nama_sls", ""),
            "petugas":  f"Petugas {gid + 1}",
            "group_id": gid + 1,
        })
    df_det = pd.DataFrame(rows).sort_values(["petugas", "kode"])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_sum.to_excel(writer, sheet_name="Ringkasan",   index=False)
        df_det.to_excel(writer, sheet_name="Detail SLS",  index=False)
    buf.seek(0)
    return buf.read()


def make_folium_map(
    gdf: gpd.GeoDataFrame,
    partition: dict,
    col_kode: str,
    col_muatan: str,
    n_officers: int,
    id_to_kode: dict = None,
) -> str:
    """Buat peta folium, return HTML string."""
    try:
        import folium

        center_lat = gdf.geometry.centroid.y.mean()
        center_lon = gdf.geometry.centroid.x.mean()

        m = folium.Map(location=[center_lat, center_lon], zoom_start=12,
                       tiles="CartoDB positron")

        # mapping kode GeoJSON → group_id
        def get_group(row_kode):
            k = str(row_kode)
            if id_to_kode:
                k = id_to_kode.get(k, k)
            return partition.get(k, -1)

        for _, row in gdf.iterrows():
            kode   = str(row[col_kode])
            gid    = get_group(kode)
            color  = GROUP_COLORS[gid % len(GROUP_COLORS)] if gid >= 0 else "#808080"
            muatan = row.get(col_muatan, 0)

            tooltip = folium.Tooltip(
                f"<b>{kode}</b><br>Muatan: {muatan}<br>Petugas {gid+1}",
                sticky=True
            )
            popup = folium.Popup(
                f"<b>{kode}</b><br>Muatan: {muatan}<br><b>Petugas {gid+1}</b>",
                max_width=200
            )

            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda f, c=color: {
                    "fillColor": c, "color": "white",
                    "weight": 1.5, "fillOpacity": 0.6,
                },
                highlight_function=lambda f, c=color: {
                    "fillColor": c, "color": "#333",
                    "weight": 3, "fillOpacity": 0.85,
                },
                tooltip=tooltip, popup=popup,
            ).add_to(m)

        return m._repr_html_()
    except Exception as e:
        return f"<p>Map error: {e}</p>"


# ─────────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────────
for key in ["G", "partition", "n_officers", "gdf_geo",
            "df_muatan_ref", "id_to_kode", "col_kode_geo",
            "col_muatan_geo", "stats"]:
    if key not in st.session_state:
        st.session_state[key] = None


# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🗺️ Sistem Partisi Wilayah Petugas Sensus</h1>
    <p>BPS — Pembagian SLS berdasarkan aksesibilitas & keseimbangan muatan</p>
</div>
""", unsafe_allow_html=True)

if import_error:
    st.error(f"❌ Modul sistem tidak ditemukan: `{import_error}`\n\nPastikan semua file `.py` (partitioner.py, config.py, dll.) ada di folder yang sama dengan app.py.")
    st.stop()


# ─────────────────────────────────────────────
# SIDEBAR — KONFIGURASI
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Konfigurasi")
    st.divider()

    mode = st.radio(
        "Mode Adjacency",
        ["📊 Dari Excel (Matriks Manual)", "🗺️ Auto dari Polygon GeoJSON"],
        help="Excel: pakai matriks relasi yang sudah dibuat manual.\nAuto: deteksi otomatis dari polygon yang bersinggungan."
    )
    use_excel = mode.startswith("📊")

    st.divider()
    n_officers = st.number_input(
        "Jumlah Petugas", min_value=1, max_value=50, value=11, step=1
    )

    epsg_label = st.selectbox("Proyeksi Wilayah (EPSG)", list(EPSG_OPTS.keys()))
    epsg_val   = EPSG_OPTS[epsg_label]

    with st.expander("⚡ Parameter Lanjutan"):
        n_restarts = st.slider("Jumlah Restart", 5, 50, 20)
        touching_buf = st.number_input("Toleransi Touching (meter)", 0.5, 10.0, 2.0, 0.5)

    st.divider()
    st.markdown("**📁 Upload File**")

    geo_file = st.file_uploader("GeoJSON SLS", type=["geojson", "json"])

    if use_excel:
        xl_file = st.file_uploader("Excel (Matriks + Muatan)", type=["xlsx", "xls"])
    else:
        xl_file = None

    # Konfigurasi kolom (expandable)
    if use_excel and xl_file:
        with st.expander("🔧 Nama Sheet & Kolom Excel"):
            sheet_matrix = st.text_input("Sheet adjacency matrix", "Sheet1")
            sheet_muatan = st.text_input("Sheet muatan",            "Sheet2")
            col_kode     = st.text_input("Kolom kode/label",        "KODE")
            col_idsubsls = st.text_input("Kolom IDSUBSLS",          "IDSUBSLS")
            col_nama     = st.text_input("Kolom nama SLS",          "NAMA SLS")
            col_muatan_xl= st.text_input("Kolom muatan",            "MUATAN")
    elif not use_excel and geo_file:
        with st.expander("🔧 Nama Kolom GeoJSON"):
            col_kode_geo    = st.text_input("Kolom kode unik SLS", "idsubsls")
            col_muatan_geo  = st.text_input("Kolom muatan",        "muatan")

    run_btn = st.button("▶ Jalankan Partisi", type="primary", use_container_width=True)


# ─────────────────────────────────────────────
# MAIN AREA — TABS
# ─────────────────────────────────────────────
tab_config, tab_result, tab_map = st.tabs([
    "📋 Panduan & Status",
    "📊 Hasil Partisi",
    "🗺️ Peta",
])


# ────────── TAB 1: Panduan ──────────
with tab_config:
    col1, col2 = st.columns(2)

    with col1:
        st.markdown('<div class="section-title">Cara Pakai</div>', unsafe_allow_html=True)
        if use_excel:
            st.markdown("""
**Mode Excel (Matriks Manual):**
1. Upload file GeoJSON SLS
2. Upload file Excel dengan 2 sheet:
   - **Sheet1**: matriks adjacency (baris & kolom = kode huruf)
   - **Sheet2**: tabel KODE, IDSUBSLS, NAMA SLS, MUATAN
3. Atur jumlah petugas di sidebar
4. Klik **Jalankan Partisi**
5. Download hasil di tab Hasil
            """)
        else:
            st.markdown("""
**Mode Auto (dari Polygon):**
1. Upload file GeoJSON SLS
   - Harus punya kolom kode unik dan muatan
2. Atur jumlah petugas di sidebar
3. Klik **Jalankan Partisi**
4. Download hasil di tab Hasil

> Adjacency dideteksi otomatis dari polygon yang bersinggungan.
            """)

    with col2:
        st.markdown('<div class="section-title">Status File</div>', unsafe_allow_html=True)

        # Status GeoJSON
        if geo_file:
            try:
                gdf_check = load_geojson_bytes(geo_file)
                st.success(f"✅ GeoJSON: **{len(gdf_check)} SLS** dimuat")
                st.caption(f"Kolom: {', '.join(gdf_check.columns.tolist()[:8])}...")
                st.caption(f"CRS: {gdf_check.crs}")
            except Exception as e:
                st.error(f"❌ GeoJSON error: {e}")
        else:
            st.info("⬆️ Upload GeoJSON di sidebar")

        # Status Excel
        if use_excel:
            if xl_file:
                try:
                    xl_check = pd.ExcelFile(xl_file)
                    st.success(f"✅ Excel dimuat")
                    st.caption(f"Sheet tersedia: **{', '.join(xl_check.sheet_names)}**")
                except Exception as e:
                    st.error(f"❌ Excel error: {e}")
            else:
                st.info("⬆️ Upload Excel di sidebar")

        # Summary konfigurasi
        st.markdown('<div class="section-title">Konfigurasi Aktif</div>', unsafe_allow_html=True)
        st.json({
            "mode":        "Excel" if use_excel else "Auto Polygon",
            "n_petugas":   n_officers,
            "epsg":        epsg_val,
            "n_restarts":  n_restarts,
        }, expanded=False)


# ────────── RUN PIPELINE ──────────
if run_btn:
    if not geo_file:
        st.error("❌ Upload GeoJSON dulu!")
        st.stop()
    if use_excel and not xl_file:
        st.error("❌ Upload file Excel dulu!")
        st.stop()

    with st.spinner("Memproses..."):
        progress = st.progress(0, text="Memuat GeoJSON...")

        # 1. Load GeoJSON
        try:
            gdf_geo = load_geojson_bytes(geo_file)
            st.session_state["gdf_geo"] = gdf_geo
        except Exception as e:
            st.error(f"❌ Gagal baca GeoJSON: {e}")
            st.stop()

        progress.progress(20, "Membangun graph...")

        # 2. Build graph
        if use_excel:
            G, df_m_ref, err = build_graph_from_excel(
                xl_file.getvalue(),
                sheet_matrix=sheet_matrix,
                sheet_muatan=sheet_muatan,
                col_kode=col_kode,
                col_idsubsls=col_idsubsls,
                col_muatan=col_muatan_xl,
                col_nama=col_nama,
            )
            if err:
                st.error(f"❌ Error baca Excel:\n```\n{err}\n```")
                st.stop()
            st.session_state["df_muatan_ref"] = df_m_ref
            # Buat id_to_kode mapping untuk peta
            st.session_state["id_to_kode"] = {
                str(r[col_idsubsls.upper()]): str(r[col_kode.upper()])
                for _, r in df_m_ref.iterrows()
            }
            st.session_state["col_kode_geo"]   = "idsubsls"
            st.session_state["col_muatan_geo"]  = "muatan"
        else:
            ck_geo = col_kode_geo
            cm_geo = col_muatan_geo
            G, err = build_graph_from_geojson(
                gdf_geo, ck_geo, cm_geo, epsg_val, touching_buf
            )
            if err:
                st.error(f"❌ Error build graph: {err}")
                st.stop()
            st.session_state["id_to_kode"]     = None
            st.session_state["col_kode_geo"]   = ck_geo
            st.session_state["col_muatan_geo"]  = cm_geo

        st.session_state["G"] = G

        progress.progress(50, f"Mempartisi {G.number_of_nodes()} SLS ke {n_officers} petugas...")

        # Override n_restarts
        if config:
            config.N_RESTARTS = n_restarts

        # 3. Partisi
        partition, err = run_partisi(G, n_officers)
        if err:
            st.error(f"❌ Error partisi:\n```\n{err}\n```")
            st.stop()

        st.session_state["partition"]  = partition
        st.session_state["n_officers"] = n_officers
        st.session_state["stats"]      = compute_stats(G, partition, n_officers)

        progress.progress(100, "Selesai!")
        st.success("✅ Partisi berhasil! Buka tab **Hasil Partisi** dan **Peta**.")


# ────────── TAB 2: HASIL ──────────
with tab_result:
    if st.session_state["partition"] is None:
        st.info("Belum ada hasil. Jalankan partisi dulu di sidebar.")
    else:
        G          = st.session_state["G"]
        partition  = st.session_state["partition"]
        n_off      = st.session_state["n_officers"]
        stats      = st.session_state["stats"]

        loads = [s["Total Muatan"] for s in stats]
        total = sum(loads)
        mean  = total / n_off if n_off else 0
        cv    = (np.std(loads) / np.mean(loads)) if loads else 0

        # ── Metric cards ──
        c1, c2, c3, c4, c5 = st.columns(5)
        for col, label, val, sub in [
            (c1, "Total SLS",     G.number_of_nodes(), "node"),
            (c2, "Petugas",       n_off,               "kelompok"),
            (c3, "Maks Muatan",   max(loads),          f"target {mean:.0f}"),
            (c4, "Min Muatan",    min(loads),           f"selisih {max(loads)-min(loads)}"),
            (c5, "CV Imbalance",  f"{cv:.4f}",         "makin kecil makin baik"),
        ]:
            with col:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="label">{label}</div>
                    <div class="value">{val}</div>
                    <div class="sub">{sub}</div>
                </div>""", unsafe_allow_html=True)

        st.markdown('<div class="section-title">Ringkasan Per Petugas</div>', unsafe_allow_html=True)

        # ── Tabel ringkasan ──
        tbl_data = []
        for s in stats:
            conn_badge = (
                '<span class="badge-ok">✓ Ya</span>' if s["Connected"]
                else '<span class="badge-warn">✗ Tidak</span>'
            )
            tbl_data.append({
                "Petugas":        s["Petugas"],
                "Jml SLS":        s["Jml SLS"],
                "Total Muatan":   f"{s['Total Muatan']:,}",
                "Min SLS":        s["Min SLS"],
                "Max SLS":        s["Max SLS"],
                "Connected":      "Ya" if s["Connected"] else "TIDAK ⚠",
                "SLS":            ", ".join(s["SLS List"][:6]) + ("..." if len(s["SLS List"]) > 6 else ""),
            })

        df_tbl = pd.DataFrame(tbl_data)
        st.dataframe(
            df_tbl,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Total Muatan": st.column_config.TextColumn("Total Muatan"),
                "Connected":    st.column_config.TextColumn("Connected"),
            }
        )

        # ── Bar chart muatan ──
        st.markdown('<div class="section-title">Distribusi Muatan</div>', unsafe_allow_html=True)
        chart_df = pd.DataFrame({
            "Petugas": [s["Petugas"] for s in stats],
            "Muatan":  [s["Total Muatan"] for s in stats],
        })
        st.bar_chart(chart_df.set_index("Petugas"), color="#4472C4", use_container_width=True)

        # ── Detail per SLS ──
        with st.expander("📋 Lihat Detail per SLS"):
            det_rows = []
            for node, gid in sorted(partition.items(), key=lambda x: (x[1], x[0])):
                det_rows.append({
                    "Kode":    node,
                    "Nama":    G.nodes[node].get("nama_sls", ""),
                    "IDSUBSLS":G.nodes[node].get("idsubsls", node),
                    "Muatan":  int(G.nodes[node].get("muatan", 0)),
                    "Petugas": f"Petugas {gid + 1}",
                })
            st.dataframe(pd.DataFrame(det_rows), use_container_width=True, hide_index=True)

        # ── Download ──
        st.markdown('<div class="section-title">Download</div>', unsafe_allow_html=True)
        dl_col1, dl_col2 = st.columns(2)

        with dl_col1:
            excel_bytes = make_excel_bytes(G, partition, n_off)
            st.download_button(
                "⬇️ Download Excel Hasil",
                data=excel_bytes,
                file_name="hasil_partisi.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        with dl_col2:
            # Download CSV detail
            det_df = pd.DataFrame([{
                "kode":    node,
                "idsubsls":G.nodes[node].get("idsubsls", node),
                "nama_sls":G.nodes[node].get("nama_sls",""),
                "muatan":  int(G.nodes[node].get("muatan",0)),
                "petugas": f"Petugas {gid+1}",
                "group_id":gid+1,
            } for node, gid in partition.items()])
            st.download_button(
                "⬇️ Download CSV Detail",
                data=det_df.to_csv(index=False).encode("utf-8"),
                file_name="detail_sls.csv",
                mime="text/csv",
                use_container_width=True,
            )


# ────────── TAB 3: PETA ──────────
with tab_map:
    if st.session_state["partition"] is None:
        st.info("Belum ada hasil. Jalankan partisi dulu.")
    elif st.session_state["gdf_geo"] is None:
        st.warning("GeoJSON tidak tersedia untuk visualisasi.")
    else:
        partition   = st.session_state["partition"]
        gdf_geo     = st.session_state["gdf_geo"]
        id_to_kode  = st.session_state["id_to_kode"]
        col_kode_g  = st.session_state["col_kode_geo"]
        col_muat_g  = st.session_state["col_muatan_geo"]

        with st.spinner("Membuat peta..."):
            map_html = make_folium_map(
                gdf_geo, partition,
                col_kode=col_kode_g,
                col_muatan=col_muat_g,
                n_officers=st.session_state["n_officers"],
                id_to_kode=id_to_kode,
            )

        # Legenda warna
        n_off = st.session_state["n_officers"]
        stats = st.session_state["stats"]
        leg_html = "<div style='display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;'>"
        for s in stats:
            gid   = s["group_id"]
            color = GROUP_COLORS[gid % len(GROUP_COLORS)]
            leg_html += (
                f"<span style='background:{color};color:white;"
                f"padding:3px 10px;border-radius:99px;font-size:0.78rem;"
                f"font-weight:600;'>"
                f"{s['Petugas']} · {s['Jml SLS']} SLS · {s['Total Muatan']:,}"
                f"</span>"
            )
        leg_html += "</div>"
        st.markdown(leg_html, unsafe_allow_html=True)

        st.components.v1.html(map_html, height=560, scrolling=False)