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

# ── Page config (harus paling atas) ──────────────────────────────────────────
st.set_page_config(
    page_title="Partisi Wilayah Sensus",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS: WCAG AA compliant, force light mode ─────────────────────────────────
# Semua kontras teks-ke-background ≥ 4.5:1
st.markdown(
    """
<style>
/* ── FORCE LIGHT MODE ─────────────────────────────── */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stApp"],
[data-testid="stMain"],
.main, .block-container              { background-color: #ffffff !important; color: #0f172a !important; }

[data-testid="stSidebar"],
[data-testid="stSidebarContent"]     { background-color: #f1f5f9 !important; color: #0f172a !important; }

/* Semua teks di dalam sidebar */
[data-testid="stSidebar"] *          { color: #0f172a !important; }
[data-testid="stSidebar"] label      { color: #1e3a5f !important; font-weight: 600 !important; }

/* Input, selectbox, number_input */
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] select,
[data-testid="stSidebar"] [data-baseweb="select"] div,
[data-testid="stSidebar"] [data-baseweb="input"] input  {
    background: #ffffff !important;
    color: #0f172a !important;
    border: 1.5px solid #94a3b8 !important;
}

/* Radio buttons */
[data-testid="stSidebar"] [data-testid="stRadio"] label { color: #0f172a !important; }

/* Tab labels */
[data-testid="stTabs"] button               { color: #475569 !important; font-weight: 600; }
[data-testid="stTabs"] button[aria-selected="true"] { color: #1d4ed8 !important; border-bottom-color: #1d4ed8 !important; }

/* Dataframe header */
[data-testid="stDataFrame"] th              { background: #e2e8f0 !important; color: #0f172a !important; }

/* Alert boxes */
[data-testid="stAlert"]                     { color: #0f172a !important; }

/* Expander */
[data-testid="stExpander"] summary          { color: #0f172a !important; }

/* Divider */
hr                                          { border-color: #cbd5e1 !important; }

/* ── KOMPONEN CUSTOM ──────────────────────────────── */

/* Header utama — bg gelap, teks putih, kontras > 7:1 */
.c-header {
    background: #1e3a5f;
    padding: 1.75rem 2rem;
    border-radius: 10px;
    border-left: 6px solid #f59e0b;
    margin-bottom: 1.5rem;
}
.c-header h1  { color: #ffffff; font-size: 1.6rem; font-weight: 700; margin: 0 0 .25rem; }
.c-header p   { color: #cbd5e1; font-size: 0.88rem; margin: 0; }

/* Metric card — bg putih, teks gelap, kontras > 4.5:1 */
.c-metric {
    background: #ffffff;
    border: 2px solid #e2e8f0;
    border-radius: 10px;
    padding: 1.1rem 1rem;
    text-align: center;
}
.c-metric .lbl  { font-size: .72rem; color: #475569; font-weight: 700;
                  text-transform: uppercase; letter-spacing: .08em; margin-bottom: .3rem; }
.c-metric .val  { font-size: 1.75rem; font-weight: 800; color: #0f172a; line-height: 1; }
.c-metric .sub  { font-size: .73rem; color: #64748b; margin-top: .25rem; }

/* Section title */
.c-section {
    font-size: .78rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .1em; color: #1e3a5f;
    border-bottom: 2px solid #1d4ed8;
    padding-bottom: 5px; margin: 1.25rem 0 .75rem;
    display: inline-block;
}

/* Status badge */
.b-ok   { background:#dcfce7; color:#14532d; padding:3px 10px; border-radius:99px;
          font-size:.75rem; font-weight:700; }
.b-warn { background:#fee2e2; color:#7f1d1d; padding:3px 10px; border-radius:99px;
          font-size:.75rem; font-weight:700; }

/* Legenda peta */
.leg-chip {
    display:inline-block; padding:4px 12px; border-radius:99px;
    font-size:.78rem; font-weight:700; color:#ffffff;
    margin:2px;
}

/* Sidebar section header */
.sb-title {
    font-size:.72rem; font-weight:700; text-transform:uppercase;
    letter-spacing:.08em; color:#1e3a5f; margin: .6rem 0 .3rem;
}

/* File uploader area */
[data-testid="stFileUploader"] { border: 2px dashed #94a3b8 !important; border-radius:8px !important; }

/* Tombol primer */
[data-testid="stButton"] button[kind="primary"],
button[data-testid="baseButton-primary"] {
    background:#1d4ed8 !important; color:#ffffff !important;
    font-weight:700 !important; border:none !important;
}
[data-testid="stButton"] button[kind="primary"]:hover {
    background:#1e40af !important;
}

/* Download button */
[data-testid="stDownloadButton"] button {
    background:#ffffff !important; color:#1d4ed8 !important;
    border:2px solid #1d4ed8 !important; font-weight:700 !important;
}

/* Hide Streamlit branding */
#MainMenu, footer { visibility:hidden; }
</style>
""",
    unsafe_allow_html=True,
)


# ── Import modul sistem ───────────────────────────────────────────────────────
@st.cache_resource
def import_modules():
    try:
        import config
        from matrix_builder import AutoMatrixBuilder
        from output_generator import OutputGenerator
        from partitioner import BalancedPartitioner

        return BalancedPartitioner, OutputGenerator, AutoMatrixBuilder, config, None
    except ImportError as e:
        return None, None, None, None, str(e)


BalancedPartitioner, OutputGenerator, AutoMatrixBuilder, config, import_error = import_modules()

# ── Konstanta ─────────────────────────────────────────────────────────────────
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


# ── Helper functions ──────────────────────────────────────────────────────────
def load_geojson_bytes(f) -> gpd.GeoDataFrame:
    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as tmp:
        tmp.write(f.getbuffer())
        p = tmp.name
    gdf = gpd.read_file(p)
    Path(p).unlink(missing_ok=True)
    return gdf


def run_partisi(G, n):
    try:
        if config:
            config.N_RESTARTS = st.session_state.get("_restarts", 20)
        p = BalancedPartitioner(G, n_groups=n)
        return p.run(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"


def compute_stats(G, partition, n):
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


def make_excel_bytes(G, partition, n):
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
                "kode": nd,
                "muatan": G.nodes[nd].get("muatan", 0),
                "idsubsls": G.nodes[nd].get("idsubsls", ""),
                "nama_sls": G.nodes[nd].get("nama_sls", ""),
                "petugas": f"Petugas {g + 1}",
                "group_id": g + 1,
            }
            for nd, g in partition.items()
        ]
    ).sort_values(["petugas", "kode"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df_s.to_excel(w, sheet_name="Ringkasan", index=False)
        df_d.to_excel(w, sheet_name="Detail SLS", index=False)
    buf.seek(0)
    return buf.read()


def make_folium_map(gdf, partition, col_kode, col_muatan, n, id_to_kode=None):
    try:
        import folium

        cl = gdf.to_crs(epsg=4326)
        cy = cl.geometry.centroid.y.mean()
        cx = cl.geometry.centroid.x.mean()
        m = folium.Map(location=[cy, cx], zoom_start=12, tiles="CartoDB positron")
        for _, row in gdf.iterrows():
            k = str(row[col_kode])
            mk = id_to_kode.get(k, k) if id_to_kode else k
            gid = partition.get(mk, -1)
            c = GROUP_COLORS[gid % len(GROUP_COLORS)] if gid >= 0 else "#64748b"
            mu = row.get(col_muatan, 0)
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda f, c=c: {
                    "fillColor": c,
                    "color": "#ffffff",
                    "weight": 1.5,
                    "fillOpacity": 0.6,
                },
                highlight_function=lambda f, c=c: {
                    "fillColor": c,
                    "color": "#0f172a",
                    "weight": 3,
                    "fillOpacity": 0.85,
                },
                tooltip=folium.Tooltip(
                    f"<b>{k}</b><br>Muatan: {mu}<br>Petugas {gid + 1}", sticky=True
                ),
                popup=folium.Popup(
                    f"<b>{k}</b><br>Muatan: {mu}<br><b>Petugas {gid + 1}</b>", max_width=200
                ),
            ).add_to(m)
        return m._repr_html_()
    except Exception as e:
        return f"<p style='color:#7f1d1d;'>Map error: {e}</p>"


# ── Session state init ────────────────────────────────────────────────────────
for k in [
    "G",
    "partition",
    "n_officers",
    "gdf_geo",
    "df_muatan_ref",
    "id_to_kode",
    "col_kode_geo",
    "col_muatan_geo",
    "stats",
]:
    if k not in st.session_state:
        st.session_state[k] = None

# ── HEADER ───────────────────────────────────────────────────────────────────
st.markdown(
    """
<div class="c-header">
  <h1>🗺️ Sistem Partisi Wilayah Petugas Sensus</h1>
  <p>BPS — Pembagian SLS berdasarkan aksesibilitas &amp; keseimbangan muatan</p>
</div>
""",
    unsafe_allow_html=True,
)

if import_error:
    st.error(
        f"❌ Modul tidak ditemukan: `{import_error}`\n\nPastikan semua file `.py` ada di folder yang sama."
    )
    st.stop()

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sb-title">Parameter Utama</div>', unsafe_allow_html=True)
    n_officers = st.number_input("Jumlah Petugas", min_value=1, max_value=50, value=11, step=1)

    with st.expander("⚡ Parameter Lanjutan"):
        n_restarts = st.slider("Jumlah Restart", 5, 50, 20)
        touching_buf = st.number_input("Toleransi Touching (m)", 0.5, 10.0, 2.0, 0.5)
        st.session_state["_restarts"] = n_restarts

    st.divider()
    st.markdown('<div class="sb-title">Upload File</div>', unsafe_allow_html=True)
    geo_file = st.file_uploader("GeoJSON SLS", type=["geojson", "json"])
    xl_file = st.file_uploader("Excel (Muatan + Kode)", type=["xlsx", "xls"])

    if xl_file:
        with st.expander("🔧 Kolom & Sheet Excel"):
            sheet_muatan = st.text_input("Sheet muatan", "TOTAL MUATAN PER SLS")
            col_idsubsls = st.text_input("Kolom idsubsls", "idsubsls")
            col_muatan_xl = st.text_input("Kolom muatan", "Perkiraan_Jumlah_Muatan")
            col_kode = st.text_input("Kolom kode_sls", "kode_sls")

    st.divider()
    run_btn = st.button("▶ Jalankan Partisi", type="primary", use_container_width=True)

# ── TABS ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📋 Panduan & Status", "📊 Hasil Partisi", "🗺️ Peta"])

# ── TAB 1: Panduan ────────────────────────────────────────────────────────────
with tab1:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="c-section">Cara Pakai</div>', unsafe_allow_html=True)
        st.markdown("""
**Mode Otomatis (Polygon Touching + OSM):**
1. Upload file GeoJSON SLS di sidebar
2. Upload file Excel dengan sheet muatan:
   - Kolom: idsubsls, muatan, kode_sls
3. Atur jumlah petugas
4. Klik **Jalankan Partisi**
5. Akses otomatis dideteksi dari polygon & jalan OSM
6. Download hasil di tab **Hasil Partisi**

**Catatan:**
- Kolom Excel bisa dikustomisasi di Expander
- OSM digunakan untuk pembobotan akses antar SLS
- Fallback ke polygon touching jika OSM gagal
        """)

    with c2:
        st.markdown('<div class="c-section">Status File</div>', unsafe_allow_html=True)
        if geo_file:
            try:
                gdf_check = load_geojson_bytes(geo_file)
                st.success(f"✅ GeoJSON — **{len(gdf_check)} SLS** dimuat")
                st.caption(f"Kolom: {', '.join(gdf_check.columns.tolist()[:8])}...")
                st.caption(f"CRS: {gdf_check.crs}")
            except Exception as e:
                st.error(f"❌ GeoJSON error: {e}")
        else:
            st.info("⬆️ Upload GeoJSON di sidebar")

        if xl_file:
            try:
                sheets = pd.ExcelFile(xl_file).sheet_names
                st.success("✅ Excel dimuat")
                st.caption(f"Sheet: **{', '.join(sheets)}**")
            except Exception as e:
                st.error(f"❌ Excel error: {e}")
        else:
            st.info("⬆️ Upload Excel di sidebar")

        st.markdown('<div class="c-section">Konfigurasi Aktif</div>', unsafe_allow_html=True)
        st.json(
            {
                "mode": "Otomatis (Polygon + OSM)",
                "n_petugas": n_officers,
                "epsg": config.EPSG_METRIC,
            },
            expanded=False,
        )

# ── RUN ───────────────────────────────────────────────────────────────────────
if run_btn:
    if not geo_file:
        st.error("❌ Upload GeoJSON dulu!")
        st.stop()
    if not xl_file:
        st.error("❌ Upload file Excel dulu!")
        st.stop()

    prog = st.progress(0, "Memuat GeoJSON...")
    try:
        gdf_geo = load_geojson_bytes(geo_file)
        st.session_state["gdf_geo"] = gdf_geo
    except Exception as e:
        st.error(f"❌ GeoJSON: {e}")
        st.stop()

    prog.progress(20, "Membaca Excel muatan...")
    try:
        df_muatan = pd.read_excel(xl_file, sheet_name=sheet_muatan)
        # Normalize kolom names
        df_muatan.columns = [c.strip() for c in df_muatan.columns]
    except Exception as e:
        st.error(f"❌ Excel: {e}")
        st.stop()

    prog.progress(35, "Membangun graph dengan AutoMatrixBuilder...")
    try:
        if not AutoMatrixBuilder:
            raise ImportError("AutoMatrixBuilder tidak tersedia")

        builder = AutoMatrixBuilder(gdf_geo)
        G, err = builder.build_weighted_graph(
            df_muatan=df_muatan,
            muatan_col=col_muatan_xl,
            kode_col=col_kode,
            idsubsls_col=col_idsubsls,
        )

        if err:
            st.error(f"❌ Graph: {err}")
            st.stop()

        st.session_state["gdf_geo"] = gdf_geo
        st.session_state["col_kode_geo"] = col_idsubsls
        st.session_state["col_muatan_geo"] = col_muatan_xl

    except Exception as e:
        st.error(f"❌ Matrix Builder: {type(e).__name__}: {e}")
        st.stop()

    st.session_state["G"] = G

    prog.progress(50, f"Mempartisi {G.number_of_nodes()} SLS ke {n_officers} petugas...")
    partition, err = run_partisi(G, n_officers)
    if err:
        st.error(f"❌ Partisi:\n```\n{err}\n```")
        st.stop()

    st.session_state["partition"] = partition
    st.session_state["n_officers"] = n_officers
    st.session_state["stats"] = compute_stats(G, partition, n_officers)
    prog.progress(100, "Selesai!")
    st.success("✅ Partisi berhasil! Buka tab **Hasil Partisi** dan **Peta**.")

# ── TAB 2: HASIL ──────────────────────────────────────────────────────────────
with tab2:
    if st.session_state["partition"] is None:
        st.info("Belum ada hasil. Jalankan partisi dulu.")
    else:
        G = st.session_state["G"]
        partition = st.session_state["partition"]
        n_off = st.session_state["n_officers"]
        stats = st.session_state["stats"]
        loads = [s["Total Muatan"] for s in stats]
        mean_ = np.mean(loads)
        cv_ = np.std(loads) / mean_ if mean_ else 0

        # Metric cards
        cols = st.columns(5)
        for col, lbl, val, sub in zip(
            cols,
            ["Total SLS", "Petugas", "Maks Muatan", "Min Muatan", "CV Imbalance"],
            [G.number_of_nodes(), n_off, max(loads), min(loads), f"{cv_:.4f}"],
            [
                "node",
                "kelompok",
                f"target {mean_:.0f}",
                f"selisih {max(loads) - min(loads)}",
                "↓ makin kecil makin baik",
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

        st.markdown('<div class="c-section">Ringkasan Per Petugas</div>', unsafe_allow_html=True)

        tbl = []
        for s in stats:
            tbl.append(
                {
                    "Petugas": s["Petugas"],
                    "Jml SLS": s["Jml SLS"],
                    "Total Muatan": f"{s['Total Muatan']:,}",
                    "Min SLS": s["Min SLS"],
                    "Max SLS": s["Max SLS"],
                    "Connected": "✓ Ya" if s["Connected"] else "✗ Tidak",
                    "SLS": ", ".join(s["SLS List"][:6]) + ("..." if len(s["SLS List"]) > 6 else ""),
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

        with st.expander("📋 Detail per SLS"):
            rows = []
            for nd, gid in sorted(partition.items(), key=lambda x: (x[1], x[0])):
                rows.append(
                    {
                        "Kode": nd,
                        "IDSUBSLS": G.nodes[nd].get("idsubsls", nd),
                        "Nama": G.nodes[nd].get("nama_sls", ""),
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
            det = pd.DataFrame(
                [
                    {
                        "kode": nd,
                        "idsubsls": G.nodes[nd].get("idsubsls", nd),
                        "nama_sls": G.nodes[nd].get("nama_sls", ""),
                        "muatan": int(G.nodes[nd].get("muatan", 0)),
                        "petugas": f"Petugas {g + 1}",
                    }
                    for nd, g in partition.items()
                ]
            )
            st.download_button(
                "⬇️ Download CSV",
                data=det.to_csv(index=False).encode("utf-8"),
                file_name="detail_sls.csv",
                mime="text/csv",
                use_container_width=True,
            )

# ── TAB 3: PETA ───────────────────────────────────────────────────────────────
with tab3:
    if st.session_state["partition"] is None:
        st.info("Belum ada hasil. Jalankan partisi dulu.")
    elif st.session_state["gdf_geo"] is None:
        st.warning("GeoJSON tidak tersedia.")
    else:
        partition = st.session_state["partition"]
        gdf_geo = st.session_state["gdf_geo"]
        id_to_kode = st.session_state["id_to_kode"]
        stats = st.session_state["stats"]
        ck = st.session_state["col_kode_geo"]
        cm = st.session_state["col_muatan_geo"]

        # Legenda
        chips = "".join(
            [
                f'<span class="leg-chip" style="background:{GROUP_COLORS[s["group_id"] % len(GROUP_COLORS)]};">'
                f"{s['Petugas']} &middot; {s['Jml SLS']} SLS &middot; {s['Total Muatan']:,}"
                f"</span>"
                for s in stats
            ]
        )
        st.markdown(f"<div style='margin-bottom:12px;'>{chips}</div>", unsafe_allow_html=True)

        with st.spinner("Membuat peta..."):
            html = make_folium_map(
                gdf_geo, partition, ck, cm, st.session_state["n_officers"], id_to_kode
            )
        st.components.v1.html(html, height=560)
