"""
visualizer.py
=============
Membuat visualisasi interaktif hasil partisi di atas peta.

Output: file HTML dengan peta Folium yang bisa dibuka di browser.

Fitur peta:
- Polygon SLS diwarnai berbeda per petugas
- Tooltip menampilkan kode_sls, muatan, dan nama petugas
- Popup menampilkan detail lengkap
- Layer control untuk toggle per petugas
- Minimap dan fullscreen control
"""

import logging

import geopandas as gpd
import numpy as np

import config

logger = logging.getLogger(__name__)

Partition = dict[str, int]

# Palet warna untuk tiap petugas (hex tanpa #)
GROUP_COLORS_HEX = [
    "#4472C4",
    "#ED7D31",
    "#A9D18E",
    "#FF6B6B",
    "#FFD700",
    "#70AD47",
    "#26547C",
    "#9E480E",
    "#636363",
    "#997300",
    "#255E91",
    "#843C0C",
    "#622E44",
    "#2D6A4F",
    "#6A0572",
    "#0563C1",
    "#954F72",
    "#C55A11",
    "#538135",
    "#833C00",
]


class MapVisualizer:
    """
    Visualisasi hasil partisi SLS pada peta interaktif menggunakan Folium.
    """

    def __init__(
        self,
        gdf: gpd.GeoDataFrame,
        partition: Partition,
        n_groups: int,
    ):
        """
        Parameters
        ----------
        gdf : gpd.GeoDataFrame
            GeoDataFrame SLS dalam CRS WGS84.
        partition : Partition
            Hasil partisi: kode_sls → group_id.
        n_groups : int
            Jumlah kelompok petugas.
        """
        self.gdf = gdf.copy()
        self.partition = partition
        self.n_groups = n_groups

        # Tambahkan kolom group assignment ke GDF
        self.gdf["group_id"] = self.gdf[config.COL_KODE_SLS].map(partition)
        self.gdf["petugas"] = self.gdf["group_id"].apply(
            lambda g: f"Petugas {int(g) + 1}" if g is not None and not np.isnan(g) else "Unassigned"
        )
        self.gdf["color"] = self.gdf["group_id"].apply(
            lambda g: (
                GROUP_COLORS_HEX[int(g) % len(GROUP_COLORS_HEX)]
                if g is not None and not np.isnan(g)
                else "#808080"
            )
        )

    # =========================================================================
    # PUBLIC: Save HTML
    # =========================================================================

    def save_html(self, filepath: str) -> None:
        """
        Buat dan simpan peta HTML.

        Parameters
        ----------
        filepath : str
            Path output file HTML.
        """
        try:
            import folium
            from folium.plugins import Fullscreen, MeasureControl, MiniMap
        except ImportError:
            raise ImportError("Folium tidak terinstall. Jalankan: pip install folium")

        # Pusat peta
        center_lat = self.gdf.geometry.centroid.y.mean()
        center_lon = self.gdf.geometry.centroid.x.mean()

        # Buat base map
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=12,
            tiles=None,  # kita tambahkan tiles sendiri
        )

        # ----------------------------------------------------------------
        # Base tiles
        # ----------------------------------------------------------------
        folium.TileLayer(
            tiles="CartoDB positron",
            name="Peta Dasar",
            attr="CartoDB",
        ).add_to(m)

        folium.TileLayer(
            tiles="OpenStreetMap",
            name="OpenStreetMap",
            attr="OSM contributors",
        ).add_to(m)

        # Satelit (Esri)
        folium.TileLayer(
            tiles=(
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}"
            ),
            attr="Esri",
            name="Satelit",
        ).add_to(m)

        # ----------------------------------------------------------------
        # Layer per petugas
        # ----------------------------------------------------------------
        for group_id in range(self.n_groups):
            group_gdf = self.gdf[self.gdf["group_id"] == group_id]
            if group_gdf.empty:
                continue

            color = GROUP_COLORS_HEX[group_id % len(GROUP_COLORS_HEX)]
            layer_name = f"Petugas {group_id + 1} ({len(group_gdf)} SLS)"

            feature_group = folium.FeatureGroup(name=layer_name, show=True)

            for _, row in group_gdf.iterrows():
                kode = row[config.COL_KODE_SLS]
                muatan = row[config.COL_MUATAN]
                petugas = row["petugas"]

                # Tooltip singkat (muncul saat hover)
                tooltip = folium.Tooltip(
                    f"<b>{kode}</b><br>Muatan: {muatan:,.0f}<br>{petugas}",
                    sticky=True,
                )

                # Popup detail (muncul saat klik)
                popup_html = f"""
                <div style="font-family: Arial; min-width: 160px;">
                    <h4 style="margin:0; color:{color};">{kode}</h4>
                    <hr style="margin:4px 0;">
                    <b>Muatan:</b> {muatan:,.0f}<br>
                    <b>Petugas:</b> {petugas}<br>
                    <b>Group ID:</b> {group_id + 1}
                </div>
                """
                popup = folium.Popup(popup_html, max_width=220)

                # Gambar polygon
                try:
                    folium.GeoJson(
                        row.geometry.__geo_interface__,
                        style_function=lambda feat, c=color: {
                            "fillColor": c,
                            "color": "white",
                            "weight": 1.5,
                            "fillOpacity": 0.55,
                        },
                        highlight_function=lambda feat, c=color: {
                            "fillColor": c,
                            "color": "#333",
                            "weight": 3,
                            "fillOpacity": 0.80,
                        },
                        tooltip=tooltip,
                        popup=popup,
                    ).add_to(feature_group)
                except Exception as e:
                    logger.debug(f"  Skip polygon {kode}: {e}")

            feature_group.add_to(m)

        # ----------------------------------------------------------------
        # Tambahkan centroid markers (opsional, nonaktif by default)
        # ----------------------------------------------------------------
        centroid_group = folium.FeatureGroup(name="Centroid SLS", show=False)
        for _, row in self.gdf.iterrows():
            lon = row.get("centroid_lon", 0)
            lat = row.get("centroid_lat", 0)
            if lon == 0 and lat == 0:
                continue

            group_id = row.get("group_id", 0)
            color = row.get("color", "#808080")

            folium.CircleMarker(
                location=[lat, lon],
                radius=4,
                color="white",
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                weight=1,
                tooltip=row[config.COL_KODE_SLS],
            ).add_to(centroid_group)

        centroid_group.add_to(m)

        # ----------------------------------------------------------------
        # Tambahkan legenda
        # ----------------------------------------------------------------
        legend_html = self._build_legend_html()
        m.get_root().html.add_child(folium.Element(legend_html))

        # ----------------------------------------------------------------
        # Plugins
        # ----------------------------------------------------------------
        MiniMap(toggle_display=True).add_to(m)
        Fullscreen().add_to(m)
        MeasureControl(primary_length_unit="meters").add_to(m)

        # Layer control (harus setelah semua layer)
        folium.LayerControl(collapsed=False).add_to(m)

        # ----------------------------------------------------------------
        # Simpan
        # ----------------------------------------------------------------
        m.save(filepath)
        logger.info(f"  Peta tersimpan: {filepath}")

    # =========================================================================
    # PRIVATE
    # =========================================================================

    def _build_legend_html(self) -> str:
        """Build HTML legenda untuk peta."""
        items_html = ""
        for group_id in range(self.n_groups):
            color = GROUP_COLORS_HEX[group_id % len(GROUP_COLORS_HEX)]
            n_sls = (self.gdf["group_id"] == group_id).sum()
            total_load = self.gdf.loc[self.gdf["group_id"] == group_id, config.COL_MUATAN].sum()
            items_html += (
                f'<div style="display:flex; align-items:center; margin-bottom:4px;">'
                f'  <div style="width:16px; height:16px; background:{color}; '
                f'     border-radius:3px; margin-right:8px; flex-shrink:0;"></div>'
                f'  <span style="font-size:12px;">'
                f"     Petugas {group_id + 1} — {n_sls} SLS, muatan {total_load:,.0f}"
                f"  </span>"
                f"</div>"
            )

        return f"""
        <div style="
            position: fixed;
            bottom: 30px;
            left: 30px;
            z-index: 1000;
            background: white;
            padding: 14px 18px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.25);
            font-family: Arial, sans-serif;
            max-height: 400px;
            overflow-y: auto;
        ">
            <h4 style="margin:0 0 10px 0; font-size:13px; color:#333;">
                Pembagian Wilayah Petugas
            </h4>
            {items_html}
        </div>
        """


# =============================================================================
# MATPLOTLIB fallback visualizer
# =============================================================================


def save_static_map(
    gdf: gpd.GeoDataFrame,
    partition: Partition,
    n_groups: int,
    filepath: str = "peta_partisi.png",
) -> None:
    """
    Simpan peta statis menggunakan matplotlib (fallback jika Folium tidak tersedia).

    Parameters
    ----------
    filepath : str
        Path output file gambar (.png, .pdf, .svg).
    """
    try:
        import matplotlib.patches as mpatches
        import matplotlib.pyplot as plt

        gdf = gdf.copy()
        gdf["group_id"] = gdf[config.COL_KODE_SLS].map(partition)

        fig, ax = plt.subplots(1, 1, figsize=(14, 10))

        cmap_colors = plt.cm.get_cmap("tab20", n_groups)

        # Plot tiap grup
        legend_patches = []
        for group_id in range(n_groups):
            group_gdf = gdf[gdf["group_id"] == group_id]
            if group_gdf.empty:
                continue

            color = cmap_colors(group_id)
            group_gdf.plot(
                ax=ax,
                color=color,
                edgecolor="white",
                linewidth=0.8,
                alpha=0.75,
            )

            # Tambahkan label centroid
            for _, row in group_gdf.iterrows():
                centroid = row.geometry.centroid
                ax.annotate(
                    row[config.COL_KODE_SLS],
                    xy=(centroid.x, centroid.y),
                    fontsize=5,
                    ha="center",
                    va="center",
                    color="black",
                )

            n_sls = len(group_gdf)
            total_load = group_gdf[config.COL_MUATAN].sum()
            patch = mpatches.Patch(
                color=color, label=f"Petugas {group_id + 1} ({n_sls} SLS, muatan {total_load:,.0f})"
            )
            legend_patches.append(patch)

        ax.legend(
            handles=legend_patches,
            loc="lower right",
            fontsize=8,
            title="Petugas Sensus",
        )
        ax.set_title("Pembagian Wilayah Petugas Sensus", fontsize=14, fontweight="bold")
        ax.set_axis_off()

        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close()

        logger.info(f"  Peta statis tersimpan: {filepath}")

    except Exception as e:
        logger.error(f"  Pembuatan peta statis gagal: {e}")
