"""
app.py  —  Sistem Partisi Wilayah Petugas Sensus
UI berbasis Streamlit. Jalankan dengan: streamlit run app.py
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

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Partisi Wilayah Sensus",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS: WCAG AA compliant, force light mode ──────────────────────────────────
st.markdown(
    """
<style>
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stApp"],
[data-testid="stMain"],
.main, .block-container              { background-color: #ffffff !important; color: #0f172a !important; }

[data-testid="stSidebar"],
[data-testid="stSidebarContent"]     { background-color: #f1f5f9 !important; color: #0f172a !important; }
[data-testid="stSidebar"] *          { color: #0f172a !important; }
[data-testid="stSidebar"] label      { color: #1e3a5f !important; font-weight: 600 !important; }

[data-testid="stSidebar"] input,
[data-testid="stSidebar"] select,
[data-testid="stSidebar"] [data-baseweb="select"] div,
[data-testid="stSidebar"] [data-baseweb="input"] input {
    background: #ffffff !important; color: #0f172a !important;
    border: 1.5px solid #94a3b8 !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label { color: #0f172a !important; }
[data-testid="stTabs"] button               { color: #475569 !important; font-weight: 600; }
[data-testid="stTabs"] button[aria-selected="true"] { color: #1d4ed8 !important; border-bottom-color: #1d4ed8 !important; }
[data-testid="stDataFrame"] th              { background: #e2e8f0 !important; color: #0f172a !important; }
[data-testid="stAlert"]                     { color: #0f172a !important; }
[data-testid="stExpander"] summary          { color: #0f172a !important; }
hr                                          { border-color: #cbd5e1 !important; }

.c-header {
    background: #1e3a5f; padding: 1.75rem 2rem;
    border-radius: 10px; border-left: 6px solid #f59e0b; margin-bottom: 1.5rem;
}
.c-header h1 { color: #ffffff; font-size: 1.6rem; font-weight: 700; margin: 0 0 .25rem; }
.c-header p  { color: #cbd5e1; font-size: 0.88rem; margin: 0; }

.c-metric {
    background: #ffffff; border: 2px solid #e2e8f0;
    border-radius: 10px; padding: 1.1rem 1rem; text-align: center;
}
.c-metric .lbl { font-size:.72rem; color:#475569; font-weight:700;
                 text-transform:uppercase; letter-spacing:.08em; margin-bottom:.3rem; }
.c-metric .val { font-size:1.75rem; font-weight:800; color:#0f172a; line-height:1; }
.c-metric .sub { font-size:.73rem; color:#64748b; margin-top:.25rem; }

.c-section {
    font-size:.78rem; font-weight:700; text-transform:uppercase;
    letter-spacing:.1em; color:#1e3a5f; border-bottom:2px solid #1d4ed8;
    padding-bottom:5px; margin:1.25rem 0 .75rem; display:inline-block;
}

.b-ok   { background:#dcfce7; color:#14532d; padding:3px 10px; border-radius:99px;
          font-size:.75rem; font-weight:700; }
.b-warn { background:#fee2e2; color:#7f1d1d; padding:3px 10px; border-radius:99px;
          font-size:.75rem; font-weight:700; }

.leg-chip {
    display:inline-block; padding:4px 12px; border-radius:99px;
    font-size:.78rem; font-weight:700; color:#ffffff; margin:2px;
}

.sb-title {
    font-size:.72rem; font-weight:700; text-transform:uppercase;
    letter-spacing:.08em; color:#1e3a5f; margin:.6rem 0 .3rem;
}

[data-testid="stFileUploader"] { border:2px dashed #94a3b8 !important; border-radius:8px !important; }

[data-testid="stButton"] button[kind="primary"],
button[data-testid="baseButton-primary"] {
    background:#1d4ed8 !important; color:#ffffff !important;
    font-weight:700 !important; border:none !important;
}
[data-testid="stButton"] button[kind="primary"]:hover { background:#1e40af !important; }

[data-testid="stDownloadButton"] button {
    background:#ffffff !important; color:#1d4ed8 !important;
    border:2px solid #1d4ed8 !important; font-weight:700 !important;
}

#MainMenu, footer { visibility:hidden; }
</style>
""",
    unsafe_allow_html=True,
)

# ── Import backend modules ────────────────────────────────────────────────────
try:
    import config
    from matrix_builder import AutoMatrixBuilder
    from partitioner import BalancedPartitioner

    import_error = None
except ImportError as e:
    BalancedPartitioner = AutoMatrixBuilder = config = None  # type: ignore[assignment]
    import_error = str(e)

# ── Constants ─────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"

GROUP_COLORS = [
    "#1d4ed8",
    "#b45309",
    "#15803d",
    "#b91c1c",
    "#7c3aed",
    "#0369a1",
    "#a16207",
    "#047857",
    "#9f1239",
    "#4338ca",
    "#0891b2",
    "#c2410c",
    "#16a34a",
    "#d97706",
    "#6d28d9",
    "#0e7490",
    "#dc2626",
    "#059669",
    "#ea580c",
    "#7e22ce",
]

# Kolom hierarki yang diharapkan ada di GeoJSON
COL_KEC = "nmkec"
COL_DESA = "nmdesa"
COL_SLS = "nmsls"
COL_SUBSLS = "idsubsls"


# ── Helper: Load GeoJSON ──────────────────────────────────────────────────────
@st.cache_data
def load_geojson_path(path: str) -> gpd.GeoDataFrame:
    return gpd.read_file(path)


def load_geojson_upload(f) -> gpd.GeoDataFrame:
    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as tmp:
        tmp.write(f.getbuffer())
        p = tmp.name
    gdf = gpd.read_file(p)
    Path(p).unlink(missing_ok=True)
    return gdf


# ── Helper: Filter ────────────────────────────────────────────────────────────
def apply_filters(
    gdf: gpd.GeoDataFrame,
    sel_kec: list,
    sel_desa: list,
    sel_sls: list,
    sel_subsls: list,
) -> gpd.GeoDataFrame:
    mask = pd.Series(True, index=gdf.index)
    if sel_kec:
        mask &= gdf[COL_KEC].isin(sel_kec)
    if sel_desa:
        mask &= gdf[COL_DESA].isin(sel_desa)
    if sel_sls:
        mask &= gdf[COL_SLS].isin(sel_sls)
    if sel_subsls:
        mask &= gdf[COL_SUBSLS].isin(sel_subsls)
    return gdf[mask].copy()


# ── Helper: Stats ─────────────────────────────────────────────────────────────
def compute_stats(G: nx.Graph, partition: dict, n: int) -> list:
    stats = []
    for gid in range(n):
        nodes = [nd for nd, g in partition.items() if g == gid]
        if not nodes:
            continue
        loads = [G.nodes[nd].get("muatan", 0) for nd in nodes]
        sub = G.subgraph(nodes)
        stats.append(
            {
                "Petugas": f"Petugas {gid + 1}",
                "Jml SLS": len(nodes),
                "Total Muatan": int(sum(loads)),
                "Min SLS": int(min(loads)),
                "Max SLS": int(max(loads)),
                "Connected": nx.is_connected(sub) if len(nodes) > 1 else True,
                "SLS List": sorted(nodes),
                "group_id": gid,
            }
        )
    return stats


# ── Helper: Excel export ──────────────────────────────────────────────────────
def make_excel_bytes(G: nx.Graph, partition: dict, n: int) -> bytes:
    stats = compute_stats(G, partition, n)
    df_s = pd.DataFrame(
        [
            {
                "Petugas": s["Petugas"],
                "Jumlah SLS": s["Jml SLS"],
                "Total Muatan": s["Total Muatan"],
                "Connected": "Ya" if s["Connected"] else "TIDAK",
                "Daftar SLS": ", ".join(s["SLS List"]),
            }
            for s in stats
        ]
    )
    df_d = pd.DataFrame(
        [
            {
                "idsubsls": nd,
                "muatan": int(G.nodes[nd].get("muatan", 0)),
                "petugas": f"Petugas {g + 1}",
                "group_id": g + 1,
            }
            for nd, g in partition.items()
        ]
    ).sort_values(["petugas", "idsubsls"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df_s.to_excel(w, sheet_name="Ringkasan", index=False)
        df_d.to_excel(w, sheet_name="Detail SLS", index=False)
    buf.seek(0)
    return buf.read()


# ── Helper: Preview map (area selection) ─────────────────────────────────────
def make_preview_map(gdf_all: gpd.GeoDataFrame, gdf_sel: gpd.GeoDataFrame) -> str:
    try:
        import folium

        cl = gdf_all.to_crs(epsg=4326)
        cy = cl.geometry.centroid.y.mean()
        cx = cl.geometry.centroid.x.mean()
        m = folium.Map(location=[cy, cx], zoom_start=11, tiles="CartoDB positron")

        sel_ids = set(gdf_sel[COL_SUBSLS].astype(str).tolist())

        for _, row in cl.iterrows():
            is_sel = str(row.get(COL_SUBSLS, "")) in sel_ids
            color = "#1d4ed8" if is_sel else "#94a3b8"
            opacity = 0.65 if is_sel else 0.2
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda f, c=color, o=opacity: {
                    "fillColor": c,
                    "color": "#ffffff",
                    "weight": 1,
                    "fillOpacity": o,
                },
                tooltip=folium.Tooltip(str(row.get(COL_SUBSLS, "")), sticky=True),
            ).add_to(m)
        return m._repr_html_()
    except Exception as e:
        return f"<p style='color:#7f1d1d;'>Preview map error: {e}</p>"


# ── Helper: Partition result map ──────────────────────────────────────────────
def make_partition_map(
    gdf: gpd.GeoDataFrame,
    partition: dict,
    G: nx.Graph,
    selected_groups: set | None = None,
) -> tuple[str, bytes]:
    """
    Buat peta partisi. Kembalikan (html_string, html_bytes) untuk render + export.
    selected_groups: set of group_id (0-indexed) yang ditampilkan penuh.
                     None = tampilkan semua. Grup lain ditampilkan abu transparan.
    """
    try:
        import folium

        cl = gdf.to_crs(epsg=4326)
        cy = cl.geometry.centroid.y.mean()
        cx = cl.geometry.centroid.x.mean()
        m = folium.Map(location=[cy, cx], zoom_start=12, tiles="CartoDB positron")

        for _, row in cl.iterrows():
            node = str(row.get(COL_SUBSLS, ""))
            gid = partition.get(node, -1)

            is_selected = selected_groups is None or gid in selected_groups
            if is_selected:
                color = GROUP_COLORS[gid % len(GROUP_COLORS)] if gid >= 0 else "#64748b"
                fill_opacity = 0.65
                weight = 1.5
                border = "#ffffff"
            else:
                color = "#94a3b8"
                fill_opacity = 0.15
                weight = 0.5
                border = "#cbd5e1"

            mu = int(G.nodes[node].get("muatan", 0)) if node in G.nodes else 0
            nama_sls = str(row.get("nmsls", ""))
            kd_subsls = str(row.get("kdsubsls", ""))

            tooltip_html = (
                f"<b>{node}</b>"
                f"{'<br>' + nama_sls if nama_sls else ''}"
                f"{'<br>Sub-SLS: ' + kd_subsls if kd_subsls else ''}"
                f"<br>Muatan: <b>{mu:,}</b>"
                f"<br>Petugas {gid + 1}"
            )
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda f, c=color, o=fill_opacity, w=weight, b=border: {
                    "fillColor": c,
                    "color": b,
                    "weight": w,
                    "fillOpacity": o,
                },
                highlight_function=lambda f, c=color, sel=is_selected: {
                    "fillColor": c,
                    "color": "#0f172a" if sel else "#94a3b8",
                    "weight": 3 if sel else 1,
                    "fillOpacity": 0.85 if sel else 0.25,
                },
                tooltip=folium.Tooltip(tooltip_html, sticky=True),
            ).add_to(m)

        html_str = m._repr_html_()
        html_bytes = html_str.encode("utf-8")
        return html_str, html_bytes
    except Exception as e:
        err = f"<p style='color:#7f1d1d;'>Map error: {e}</p>"
        return err, err.encode("utf-8")


# ── Helper: Build edge DataFrame untuk data_editor ────────────────────────────
def build_edge_df(G: nx.Graph, label_map: dict) -> pd.DataFrame:
    rows = []
    for u, v, data in G.edges(data=True):
        road_m = data.get("road_dist_m", -1)
        rows.append(
            {
                "_u": u,
                "_v": v,
                "Node A": label_map.get(u, u),
                "Node B": label_map.get(v, v),
                "Jarak Jalan (km)": round(road_m / 1000, 2) if road_m > 0 else None,
                "Touching": bool(data.get("is_touching", False)),
                "Bobot": round(float(data.get("weight", 1.0)), 3),
                "Putuskan": False,
            }
        )
    return pd.DataFrame(rows)


def apply_edge_edits(
    G_original: nx.Graph, df_edited: pd.DataFrame, df_original: pd.DataFrame
) -> tuple[nx.Graph, dict]:
    G = G_original.copy()
    # Lookup berdasarkan key (u,v) — tahan sorting tabel oleh user
    orig_bobot: dict = {(row["_u"], row["_v"]): row["Bobot"] for _, row in df_original.iterrows()}
    deleted = reweighted = 0
    for _, row in df_edited.iterrows():
        u, v = row["_u"], row["_v"]
        if not G.has_edge(u, v):
            continue
        if row["Putuskan"]:
            G.remove_edge(u, v)
            deleted += 1
        elif abs(row["Bobot"] - orig_bobot.get((u, v), row["Bobot"])) > 1e-6:
            G[u][v]["weight"] = row["Bobot"]
            reweighted += 1
    return G, {"deleted": deleted, "reweighted": reweighted}


def run_partition(
    G: nx.Graph,
    n_officers: int,
    prioritas_desa: bool,
    desa_penalty: int,
    gdf_filtered: gpd.GeoDataFrame,
) -> tuple[dict, list]:
    if config:
        config.N_RESTARTS = st.session_state.get("_restarts", 20)
    desa_map = None
    if prioritas_desa and gdf_filtered is not None and "nmdesa" in gdf_filtered.columns:
        desa_map = dict(
            zip(gdf_filtered[COL_SUBSLS].astype(str), gdf_filtered["nmdesa"].astype(str))
        )
    p = BalancedPartitioner(G, n_groups=n_officers, desa_map=desa_map, desa_penalty=desa_penalty)
    partition = p.run()
    return partition, compute_stats(G, partition, n_officers)


# ── Session state init ────────────────────────────────────────────────────────
for k in [
    "gdf_raw",
    "gdf_filtered",
    "G",
    "G_original",
    "G_edited",
    "edit_summary",
    "edge_df",
    "partition",
    "n_officers",
    "stats",
    "muatan_col",
]:
    if k not in st.session_state:
        st.session_state[k] = None
if "edge_df_key" not in st.session_state:
    st.session_state["edge_df_key"] = 0

# ── HEADER ────────────────────────────────────────────────────────────────────
st.markdown(
    """
<div class="c-header">
  <h1>🗺️ Sistem Partisi Wilayah Petugas Sensus</h1>
  <p>BPS — Pembagian SubSLS berdasarkan aksesibilitas &amp; keseimbangan muatan</p>
</div>
""",
    unsafe_allow_html=True,
)

if import_error:
    st.error(f"❌ Modul tidak ditemukan: `{import_error}`")
    st.stop()

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sb-title">Sumber GeoJSON</div>', unsafe_allow_html=True)

    file_source = st.radio(
        "Pilih sumber file",
        ["Pilih dari /data", "Upload file"],
        label_visibility="collapsed",
    )

    geo_path = None
    uploaded_file = None

    if file_source == "Pilih dari /data":
        geojson_files = sorted(DATA_DIR.glob("*.geojson")) if DATA_DIR.exists() else []
        if geojson_files:
            sel_filename = st.selectbox(
                "File GeoJSON",
                [f.name for f in geojson_files],
            )
            geo_path = str(DATA_DIR / sel_filename)
        else:
            st.warning(f"Tidak ada file .geojson di `{DATA_DIR}`")
    else:
        uploaded_file = st.file_uploader("Upload GeoJSON", type=["geojson", "json"])

    st.divider()
    st.markdown('<div class="sb-title">Parameter</div>', unsafe_allow_html=True)

    muatan_col_input = st.text_input("Kolom muatan di GeoJSON", value="Perkiraan_Jumlah_Muatan")
    n_officers = st.number_input("Jumlah Petugas", min_value=1, max_value=50, value=5, step=1)

    with st.expander("⚡ Parameter Lanjutan"):
        n_restarts = st.slider("Jumlah Restart", 5, 50, 20)
        st.session_state["_restarts"] = n_restarts

        st.divider()
        prioritas_desa = st.checkbox(
            "Prioritas satu desa per petugas",
            value=False,
            help="Algoritma akan berusaha memberi setiap petugas SubSLS dari desa yang sama.",
        )
        if prioritas_desa:
            desa_penalty = st.slider(
                "Toleransi lintas desa (penalti per petugas)",
                min_value=0,
                max_value=5000,
                value=500,
                step=100,
                help=(
                    "Nilai tinggi = ketat (hampir tidak boleh lintas desa). "
                    "Nilai rendah = longgar (boleh lintas desa jika gap-nya membaik signifikan)."
                ),
            )
        else:
            desa_penalty = 0

    st.divider()
    run_btn = st.button("▶ Jalankan Partisi", type="primary", use_container_width=True)

# ── Load GeoJSON ──────────────────────────────────────────────────────────────
if geo_path:
    try:
        gdf_raw = load_geojson_path(geo_path)
        st.session_state["gdf_raw"] = gdf_raw
    except Exception as e:
        st.error(f"❌ Gagal load GeoJSON: {e}")
        st.session_state["gdf_raw"] = None
elif uploaded_file:
    try:
        gdf_raw = load_geojson_upload(uploaded_file)
        st.session_state["gdf_raw"] = gdf_raw
    except Exception as e:
        st.error(f"❌ Gagal load GeoJSON: {e}")
        st.session_state["gdf_raw"] = None

# ── Filter selections (default empty = all) ───────────────────────────────────
sel_kec: list = []
sel_desa: list = []
sel_sls: list = []
sel_subsls: list = []

# ── TABS ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["🗂️ Pilih Area", "🔗 Edit Koneksi", "📊 Hasil Partisi", "🗺️ Peta"])

# ── TAB 1: Pilih Area ─────────────────────────────────────────────────────────
with tab1:
    gdf_raw = st.session_state["gdf_raw"]

    if gdf_raw is None:
        st.info("⬆️ Pilih atau upload file GeoJSON di sidebar untuk memulai.")
    else:
        # Cek kolom hierarki
        hier_cols = [COL_KEC, COL_DESA, COL_SLS, COL_SUBSLS]
        missing_cols = [c for c in hier_cols if c not in gdf_raw.columns]

        if missing_cols:
            st.warning(
                f"Kolom hierarki tidak lengkap di GeoJSON: `{'`, `'.join(missing_cols)}`. "
                f"Filter area tidak tersedia — semua SubSLS akan diikutkan."
            )
        else:
            st.markdown('<div class="c-section">Filter Area</div>', unsafe_allow_html=True)
            st.caption(
                "Kosongkan semua filter = semua SubSLS diikutkan. Filter dikombinasikan dengan AND."
            )

            col_a, col_b = st.columns(2)
            with col_a:
                sel_kec = st.multiselect(
                    "Kecamatan",
                    sorted(gdf_raw[COL_KEC].dropna().unique()),
                    placeholder="Semua kecamatan",
                )
                sel_sls = st.multiselect(
                    "SLS",
                    sorted(gdf_raw[COL_SLS].dropna().unique()),
                    placeholder="Semua SLS",
                )
            with col_b:
                sel_desa = st.multiselect(
                    "Desa / Kelurahan",
                    sorted(gdf_raw[COL_DESA].dropna().unique()),
                    placeholder="Semua desa",
                )
                sel_subsls = st.multiselect(
                    "SubSLS (idsubsls)",
                    sorted(gdf_raw[COL_SUBSLS].dropna().unique()),
                    placeholder="Semua SubSLS",
                )

        # Hitung filtered GDF
        gdf_preview = apply_filters(gdf_raw, sel_kec, sel_desa, sel_sls, sel_subsls)
        n_sel = len(gdf_preview)
        n_total = len(gdf_raw)

        muatan_ok = muatan_col_input in gdf_raw.columns
        total_muatan = int(gdf_preview[muatan_col_input].sum()) if muatan_ok else None

        st.markdown('<div class="c-section">Ringkasan Seleksi</div>', unsafe_allow_html=True)

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            st.markdown(
                f"""
            <div class="c-metric">
              <div class="lbl">SubSLS terpilih</div>
              <div class="val">{n_sel:,}</div>
              <div class="sub">dari {n_total:,} total</div>
            </div>""",
                unsafe_allow_html=True,
            )
        with mc2:
            st.markdown(
                f"""
            <div class="c-metric">
              <div class="lbl">Total Muatan</div>
              <div class="val">{f"{total_muatan:,}" if total_muatan is not None else "—"}</div>
              <div class="sub">{"kolom: " + muatan_col_input if muatan_ok else "⚠ kolom tidak ditemukan"}</div>
            </div>""",
                unsafe_allow_html=True,
            )
        with mc3:
            st.markdown(
                f"""
            <div class="c-metric">
              <div class="lbl">Rata-rata / SubSLS</div>
              <div class="val">{f"{total_muatan // n_sel:,}" if (total_muatan and n_sel) else "—"}</div>
              <div class="sub">muatan per node</div>
            </div>""",
                unsafe_allow_html=True,
            )

        # Preview map
        st.markdown('<div class="c-section">Preview Wilayah</div>', unsafe_allow_html=True)
        if n_sel == 0:
            st.warning("Tidak ada SubSLS yang cocok dengan filter yang dipilih.")
        elif n_sel > 2000:
            st.info(
                f"Preview peta dilewati ({n_sel:,} SubSLS terlalu banyak untuk dirender). Langsung jalankan partisi."
            )
        else:
            with st.spinner("Membuat preview peta..."):
                html_preview = make_preview_map(gdf_raw, gdf_preview)
            st.components.v1.html(html_preview, height=420)
            st.caption("🔵 Terpilih  ·  ⬜ Tidak terpilih")

# ── RUN ───────────────────────────────────────────────────────────────────────
if run_btn:
    gdf_raw = st.session_state["gdf_raw"]

    if gdf_raw is None:
        st.error("❌ Pilih atau upload file GeoJSON di sidebar dulu!")
        st.stop()

    gdf_filtered = apply_filters(gdf_raw, sel_kec, sel_desa, sel_sls, sel_subsls)

    if len(gdf_filtered) < 2:
        st.error("❌ Minimal 2 SubSLS harus terpilih untuk partisi.")
        st.stop()

    if n_officers > len(gdf_filtered):
        st.error(
            f"❌ Jumlah petugas ({n_officers}) tidak boleh melebihi "
            f"jumlah SubSLS terpilih ({len(gdf_filtered)})."
        )
        st.stop()

    muatan_col = muatan_col_input
    if muatan_col not in gdf_filtered.columns:
        st.error(f"❌ Kolom muatan `{muatan_col}` tidak ditemukan di GeoJSON.")
        st.stop()

    prog = st.progress(0, "Membangun connection matrix (OSM + polygon touching)...")
    try:
        builder = AutoMatrixBuilder(gdf_filtered)
        G, err = builder.build_from_geojson(muatan_col=muatan_col)
        if err:
            st.error(f"❌ Matrix builder: {err}")
            st.stop()
    except Exception as e:
        st.error(f"❌ Matrix builder: {type(e).__name__}: {e}\n```\n{traceback.format_exc()}\n```")
        st.stop()

    prog.progress(50, f"Mempartisi {G.number_of_nodes()} SubSLS ke {n_officers} petugas...")
    try:
        partition, stats_new = run_partition(
            G, n_officers, prioritas_desa, desa_penalty, gdf_filtered
        )
    except Exception as e:
        st.error(f"❌ Partisi: {type(e).__name__}: {e}\n```\n{traceback.format_exc()}\n```")
        st.stop()

    st.session_state["G"] = G
    st.session_state["G_original"] = G.copy()
    st.session_state["G_edited"] = None
    st.session_state["edit_summary"] = None
    st.session_state["edge_df"] = None
    st.session_state["edge_df_key"] = st.session_state.get("edge_df_key", 0) + 1
    st.session_state["partition"] = partition
    st.session_state["n_officers"] = n_officers
    st.session_state["gdf_filtered"] = gdf_filtered
    st.session_state["stats"] = stats_new
    st.session_state["muatan_col"] = muatan_col

    prog.progress(100, "Selesai!")
    st.success("✅ Partisi berhasil! Buka tab **Edit Koneksi**, **Hasil Partisi**, atau **Peta**.")

# ── TAB 2: EDIT KONEKSI ───────────────────────────────────────────────────────
with tab2:
    G_orig = st.session_state.get("G_original")
    gdf_fe = st.session_state.get("gdf_filtered")

    if G_orig is None:
        st.info("⬆️ Jalankan Partisi dulu untuk membangun matriks koneksi.")
    else:
        # Build label_map dari gdf_filtered
        lmap: dict = {}
        if gdf_fe is not None and "nmsls" in gdf_fe.columns and "kdsubsls" in gdf_fe.columns:
            for _, row in gdf_fe.iterrows():
                key = str(row.get(COL_SUBSLS, ""))
                nama = str(row.get("nmsls", ""))
                kd = str(row.get("kdsubsls", ""))
                lmap[key] = f"{nama} ({kd})" if nama else key

        # Inisialisasi edge_df sekali dari G_original
        if st.session_state["edge_df"] is None:
            st.session_state["edge_df"] = build_edge_df(G_orig, lmap)

        n_nodes = G_orig.number_of_nodes()
        n_edges = G_orig.number_of_edges()

        st.markdown(
            '<div class="c-section">Matriks Koneksi Antar SubSLS</div>', unsafe_allow_html=True
        )
        st.caption(
            f"Graph: **{n_nodes}** node · **{n_edges}** edge. "
            "Centang **Putuskan ❌** untuk memutus koneksi yang tidak bisa diakses di lapangan, "
            "atau ubah nilai **Bobot** untuk menyesuaikan tingkat kesulitan akses."
        )

        if n_edges > 500:
            st.warning(f"⚠ Tabel memiliki {n_edges:,} edge. Gunakan sorting kolom untuk navigasi.")

        edge_df_key = st.session_state["edge_df_key"]
        edited_df = st.data_editor(
            st.session_state["edge_df"],
            key=f"edge_editor_{edge_df_key}",
            use_container_width=True,
            hide_index=True,
            column_config={
                "_u": None,
                "_v": None,
                "Node A": st.column_config.TextColumn("Node A", disabled=True),
                "Node B": st.column_config.TextColumn("Node B", disabled=True),
                "Jarak Jalan (km)": st.column_config.NumberColumn(
                    "Jarak Jalan (km)", disabled=True, format="%.2f"
                ),
                "Touching": st.column_config.CheckboxColumn("Touching", disabled=True),
                "Bobot": st.column_config.NumberColumn(
                    "Bobot", min_value=0.0, max_value=9999.0, format="%.3f"
                ),
                "Putuskan": st.column_config.CheckboxColumn("Putuskan ❌"),
            },
        )

        # Ringkasan perubahan tertunda
        n_putus = int(edited_df["Putuskan"].sum())
        n_ubah = int((abs(edited_df["Bobot"] - st.session_state["edge_df"]["Bobot"]) > 1e-6).sum())
        if n_putus > 0 or n_ubah > 0:
            st.caption(
                f"Perubahan tertunda: **{n_putus}** edge akan diputuskan · "
                f"**{n_ubah}** edge diubah bobotnya."
            )

        bc1, bc2 = st.columns(2)

        with bc1:
            if st.button("🔄 Reset ke Original", use_container_width=True):
                st.session_state["edge_df"] = build_edge_df(G_orig, lmap)
                st.session_state["edge_df_key"] += 1
                st.session_state["G_edited"] = None
                st.session_state["edit_summary"] = None
                st.session_state["G"] = G_orig.copy()
                st.session_state["stats"] = compute_stats(
                    G_orig,
                    st.session_state["partition"],
                    st.session_state["n_officers"],
                )
                st.rerun()

        with bc2:
            if st.button("✅ Terapkan & Partisi Ulang", type="primary", use_container_width=True):
                G_edit, summary = apply_edge_edits(G_orig, edited_df, st.session_state["edge_df"])

                # Warning jika penghapusan edge menciptakan komponen terpisah
                components = list(nx.connected_components(G_edit))
                if len(components) > 1:
                    comp_sizes = sorted([len(c) for c in components], reverse=True)
                    small_nodes = sum(comp_sizes[1:])
                    size_str = " + ".join(str(s) for s in comp_sizes[1:])
                    st.warning(
                        f"⚠ Penghapusan edge membuat graph terpecah menjadi "
                        f"**{len(components)} komponen** terpisah "
                        f"({comp_sizes[0]} + {size_str} SubSLS). "
                        f"**{small_nodes} SubSLS** di komponen kecil akan mendapat kelompok "
                        "petugas tersendiri, terpisah dari area utama."
                    )

                n_off_edit = st.session_state["n_officers"]
                gdf_fc = st.session_state.get("gdf_filtered")

                with st.spinner("Menjalankan partisi ulang..."):
                    try:
                        partition_new, stats_new = run_partition(
                            G_edit, n_off_edit, prioritas_desa, desa_penalty, gdf_fc
                        )
                    except Exception as e:
                        st.error(f"❌ Partisi gagal: {type(e).__name__}: {e}")
                        st.stop()

                st.session_state["G"] = G_edit
                st.session_state["G_edited"] = G_edit
                st.session_state["edit_summary"] = summary
                st.session_state["partition"] = partition_new
                st.session_state["stats"] = stats_new
                st.success(
                    f"✅ Partisi ulang selesai! "
                    f"**{summary['deleted']}** edge diputuskan, "
                    f"**{summary['reweighted']}** edge diubah bobotnya. "
                    "Buka tab **Hasil Partisi**."
                )

# ── TAB 3: HASIL PARTISI ──────────────────────────────────────────────────────
with tab3:
    if st.session_state["partition"] is None:
        st.info("Belum ada hasil. Jalankan partisi dulu.")
    else:
        edit_summary = st.session_state.get("edit_summary")
        if edit_summary:
            st.info(
                f"ℹ️ Hasil dari matriks yang **diedit**: "
                f"**{edit_summary['deleted']}** edge diputuskan · "
                f"**{edit_summary['reweighted']}** edge diubah bobotnya."
            )
        else:
            st.caption("Hasil dari matriks original (belum diedit).")

        G = st.session_state["G"]
        partition = st.session_state["partition"]
        n_off = st.session_state["n_officers"]
        stats = st.session_state["stats"]

        loads = [s["Total Muatan"] for s in stats]
        mean_ = np.mean(loads)
        gap_ = max(loads) - min(loads)

        # Hitung desa violations untuk ditampilkan
        gdf_f2 = st.session_state.get("gdf_filtered")
        desa_viol = 0
        if gdf_f2 is not None and "nmdesa" in gdf_f2.columns:
            dm = dict(zip(gdf_f2[COL_SUBSLS].astype(str), gdf_f2["nmdesa"].astype(str)))
            for gid in range(n_off):
                nodes_g = [n for n, g in partition.items() if g == gid]
                if len({dm.get(n) for n in nodes_g if dm.get(n)}) > 1:
                    desa_viol += 1

        # Metric cards
        viol_label = (
            f"{desa_viol} dari {n_off}"
            if gdf_f2 is not None and "nmdesa" in gdf_f2.columns
            else "—"
        )
        cols = st.columns(6)
        for col, lbl, val, sub in zip(
            cols,
            ["Total SLS", "Petugas", "Maks Muatan", "Min Muatan", "Gap Muatan", "Lintas Desa"],
            [G.number_of_nodes(), n_off, max(loads), min(loads), f"{int(gap_):,}", viol_label],
            [
                "node",
                "kelompok",
                f"target {mean_:.0f}",
                f"min {min(loads):,}",
                "maks − min (↓ lebih baik)",
                "petugas lintas desa (↓ lebih baik)",
            ],
        ):
            with col:
                st.markdown(
                    f"""
                <div class="c-metric">
                  <div class="lbl">{lbl}</div>
                  <div class="val">{val}</div>
                  <div class="sub">{sub}</div>
                </div>""",
                    unsafe_allow_html=True,
                )

        # Lookup: idsubsls → "Nama SLS (kdsubsls)"
        gdf_f = st.session_state.get("gdf_filtered")
        label_map: dict = {}
        if gdf_f is not None and "nmsls" in gdf_f.columns and "kdsubsls" in gdf_f.columns:
            for _, row in gdf_f.iterrows():
                key = str(row.get(COL_SUBSLS, ""))
                nama = str(row.get("nmsls", ""))
                kd = str(row.get("kdsubsls", ""))
                label_map[key] = f"{nama} ({kd})" if nama else key

        def node_label(node_id: str) -> str:
            return label_map.get(node_id, node_id)

        st.markdown('<div class="c-section">Ringkasan Per Petugas</div>', unsafe_allow_html=True)

        tbl = []
        for s in stats:
            labels = [node_label(n) for n in s["SLS List"]]
            tbl.append(
                {
                    "Petugas": s["Petugas"],
                    "Jml SLS": s["Jml SLS"],
                    "Total Muatan": f"{s['Total Muatan']:,}",
                    "Min SLS": s["Min SLS"],
                    "Max SLS": s["Max SLS"],
                    "Connected": "✓ Ya" if s["Connected"] else "✗ Tidak",
                    "Daftar SLS": ", ".join(labels[:4]) + ("..." if len(labels) > 4 else ""),
                }
            )
        st.dataframe(pd.DataFrame(tbl), use_container_width=True, hide_index=True)

        st.markdown('<div class="c-section">Distribusi Muatan</div>', unsafe_allow_html=True)
        st.bar_chart(
            pd.DataFrame(
                {
                    "Petugas": [s["Petugas"] for s in stats],
                    "Muatan": [s["Total Muatan"] for s in stats],
                }
            ).set_index("Petugas"),
            color="#1d4ed8",
            use_container_width=True,
        )

        with st.expander("📋 Detail per SubSLS"):
            rows = []
            for nd, gid in sorted(partition.items(), key=lambda x: (x[1], x[0])):
                rows.append(
                    {
                        "idsubsls": nd,
                        "Nama SLS (Sub)": node_label(nd),
                        "Muatan": int(G.nodes[nd].get("muatan", 0)),
                        "Petugas": f"Petugas {gid + 1}",
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown('<div class="c-section">Download</div>', unsafe_allow_html=True)
        dc1, dc2 = st.columns(2)
        with dc1:
            st.download_button(
                "⬇️ Download Excel",
                data=make_excel_bytes(G, partition, n_off),
                file_name="hasil_partisi.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with dc2:
            df_csv = pd.DataFrame(
                [
                    {
                        "idsubsls": nd,
                        "muatan": int(G.nodes[nd].get("muatan", 0)),
                        "petugas": f"Petugas {g + 1}",
                        "group_id": g + 1,
                    }
                    for nd, g in partition.items()
                ]
            )
            st.download_button(
                "⬇️ Download CSV",
                data=df_csv.to_csv(index=False).encode("utf-8"),
                file_name="detail_subsls.csv",
                mime="text/csv",
                use_container_width=True,
            )

# ── TAB 4: PETA ───────────────────────────────────────────────────────────────
with tab4:
    if st.session_state["partition"] is None:
        st.info("Belum ada hasil. Jalankan partisi dulu.")
    elif st.session_state["gdf_filtered"] is None:
        st.warning("GeoJSON tidak tersedia.")
    else:
        partition = st.session_state["partition"]
        gdf_filtered = st.session_state["gdf_filtered"]
        stats = st.session_state["stats"]
        n_off = st.session_state["n_officers"]
        G = st.session_state["G"]

        # Filter petugas
        all_labels = [s["Petugas"] for s in stats]
        sel_officers = st.multiselect(
            "Tampilkan petugas",
            options=all_labels,
            default=all_labels,
            placeholder="Pilih petugas yang ditampilkan...",
        )
        selected_gids = (
            {s["group_id"] for s in stats if s["Petugas"] in sel_officers} if sel_officers else None
        )

        # Legenda chips (hanya petugas terpilih)
        chips = "".join(
            [
                f'<span class="leg-chip" style="background:{GROUP_COLORS[s["group_id"] % len(GROUP_COLORS)]};">'
                f"{s['Petugas']} &middot; {s['Jml SLS']} SLS &middot; {s['Total Muatan']:,}"
                f"</span>"
                for s in stats
                if s["Petugas"] in sel_officers
            ]
        )
        if chips:
            st.markdown(f"<div style='margin-bottom:12px;'>{chips}</div>", unsafe_allow_html=True)

        with st.spinner("Membuat peta partisi..."):
            html_str, html_bytes = make_partition_map(
                gdf_filtered, partition, G, selected_groups=selected_gids
            )
        st.components.v1.html(html_str, height=560)

        st.download_button(
            "⬇️ Download Peta HTML",
            data=html_bytes,
            file_name="peta_partisi.html",
            mime="text/html",
            use_container_width=True,
        )
