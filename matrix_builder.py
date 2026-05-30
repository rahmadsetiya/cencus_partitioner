"""
matrix_builder.py
=================
Automated accessibility matrix builder untuk Streamlit app.
Menggabungkan polygon touching + OSM road distance weighting.

Reuse: AdjacencyBuilder + RoadNetworkHandler dari main.py pipeline.
"""

import logging

import geopandas as gpd
import networkx as nx
import pandas as pd

import config
from adjacency_builder import AdjacencyBuilder
from road_network import RoadNetworkHandler

logger = logging.getLogger(__name__)


def detect_epsg(gdf: gpd.GeoDataFrame) -> int:
    """
    Auto-detect EPSG UTM zone dari centroid longitude GeoJSON.
    Batas: Sumatera/Jawa Barat <108°, Jawa Tengah-Timur/Bali/NTB 108–115°, sisanya ≥115°.
    """
    lon = gdf.to_crs(epsg=4326).geometry.centroid.x.mean()
    if lon < 108:
        return 32748
    elif lon < 115:
        return 32749
    else:
        return 32750


class AutoMatrixBuilder:
    """
    Auto-generate weighted accessibility graph dari GeoJSON + muatan data.
    """

    def __init__(self, gdf: gpd.GeoDataFrame):
        """
        Parameters
        ----------
        gdf : gpd.GeoDataFrame
            GeoDataFrame dengan geometry untuk setiap SLS.
            Harus punya kolom: idsubsls (atau custom kode_col).
        """
        self.gdf = gdf.copy()
        self.road_handler = None
        self.adj_builder = None

    def build_weighted_graph(
        self,
        df_muatan: pd.DataFrame,
        muatan_col: str,
        kode_col: str,
        idsubsls_col: str,
    ) -> tuple[nx.Graph, str | None]:
        """
        Bangun weighted graph dari GeoJSON + muatan data.

        Parameters
        ----------
        df_muatan : pd.DataFrame
            Tabel muatan dengan kolom idsubsls, muatan, dan optional kode_sls
        muatan_col : str
            Nama kolom muatan di df_muatan
        kode_col : str
            Nama kolom kode_sls di df_muatan (opsional, untuk node attributes)
        idsubsls_col : str
            Nama kolom idsubsls yang cocok dengan GeoJSON

        Returns
        -------
        Tuple[nx.Graph, Optional[str]]
            (graph, error_message)
            - graph: nx.Graph dengan node+edge dari GeoJSON + weights dari OSM
            - error_message: None jika sukses, string error jika gagal
        """
        try:
            logger.info("=[AutoMatrixBuilder] Mulai build weighted graph")

            # Step 1: Tambah kolom kode_sls ke GeoDataFrame (dari idsubsls)
            # Untuk kompatibilitas dengan AdjacencyBuilder yang expect config.COL_KODE_SLS
            self.gdf[config.COL_KODE_SLS] = (
                self.gdf.get(idsubsls_col, "")
                if idsubsls_col in self.gdf.columns
                else self.gdf.index.astype(str)
            )

            # Step 2: Setup muatan di node attributes
            muatan_map = {}
            kode_map = {}
            for _, row in df_muatan.iterrows():
                id_sls = str(row[idsubsls_col]).strip()
                muatan_map[id_sls] = float(row.get(muatan_col, 0))
                if kode_col and kode_col in df_muatan.columns:
                    kode_map[id_sls] = str(row[kode_col]).strip()

            # Step 3: Initialize road network handler
            logger.info("=[AutoMatrixBuilder] Download jaringan jalan OSM...")
            self.road_handler = RoadNetworkHandler(self.gdf)
            self.road_handler.download_network()

            if self.road_handler.is_road_available():
                logger.info("=[AutoMatrixBuilder] OSM tersedia, snap centroids...")
                self.road_handler.snap_centroids(self.gdf)
            else:
                logger.info("=[AutoMatrixBuilder] OSM tidak tersedia, fallback ke polygon touching")

            # Step 4: Build adjacency graph dengan bobot
            logger.info("=[AutoMatrixBuilder] Build adjacency graph...")
            self.adj_builder = AdjacencyBuilder(self.gdf, self.road_handler)
            G = self.adj_builder.build_graph()

            # Step 5: Attach muatan attributes dari df_muatan
            logger.info("=[AutoMatrixBuilder] Attach muatan attributes...")
            for node in G.nodes():
                if node in muatan_map:
                    G.nodes[node][config.COL_MUATAN] = muatan_map[node]
                    G.nodes[node]["idsubsls"] = node
                    if node in kode_map:
                        G.nodes[node]["kode_sls"] = kode_map[node]
                else:
                    # Node ada di GeoJSON tapi tidak ada di muatan
                    G.nodes[node][config.COL_MUATAN] = 0
                    G.nodes[node]["idsubsls"] = node
                    logger.warning(f"  Node {node} tidak ada di muatan, set muatan=0")

            logger.info(
                f"=[AutoMatrixBuilder] Graph built: "
                f"{G.number_of_nodes()} node, {G.number_of_edges()} edge"
            )

            return G, None

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"=[AutoMatrixBuilder] Error: {error_msg}")
            return None, error_msg

    def build_from_geojson(
        self,
        muatan_col: str = "muatan",
        idsubsls_col: str = "idsubsls",
    ) -> tuple[nx.Graph, str | None]:
        """
        Build weighted graph dari GeoDataFrame yang sudah punya kolom muatan.
        Tidak perlu Excel — muatan dibaca langsung dari GeoJSON.
        """
        try:
            logger.info("=[AutoMatrixBuilder] build_from_geojson mulai")

            if muatan_col not in self.gdf.columns:
                return None, f"Kolom muatan '{muatan_col}' tidak ditemukan di GeoJSON."
            if idsubsls_col not in self.gdf.columns:
                return None, f"Kolom '{idsubsls_col}' tidak ditemukan di GeoJSON."

            # Auto-detect EPSG dari centroid GeoJSON — tidak perlu ubah config.py manual
            detected_epsg = detect_epsg(self.gdf)
            if detected_epsg != config.EPSG_METRIC:
                logger.info(
                    f"=[AutoMatrixBuilder] Auto-detect EPSG: {detected_epsg} "
                    f"(sebelumnya config={config.EPSG_METRIC})"
                )
                config.EPSG_METRIC = detected_epsg
            self._detected_epsg = detected_epsg

            # Gunakan idsubsls sebagai node identifier (kompatibel dengan AdjacencyBuilder)
            self.gdf[config.COL_KODE_SLS] = self.gdf[idsubsls_col].astype(str)

            # AdjacencyBuilder baca config.COL_MUATAN ("muatan") dari GDF.
            # Jika nama kolom berbeda, buat alias agar kompatibel.
            if muatan_col != config.COL_MUATAN:
                self.gdf[config.COL_MUATAN] = self.gdf[muatan_col]

            # Muatan map: idsubsls → muatan value
            muatan_map = {
                str(row[idsubsls_col]): float(row[muatan_col]) for _, row in self.gdf.iterrows()
            }

            # OSM road network
            logger.info("=[AutoMatrixBuilder] Download jaringan jalan OSM...")
            self.road_handler = RoadNetworkHandler(self.gdf)
            self.road_handler.download_network()

            if self.road_handler.is_road_available():
                logger.info("=[AutoMatrixBuilder] OSM tersedia, snap centroids...")
                self.road_handler.snap_centroids(self.gdf)
            else:
                logger.info("=[AutoMatrixBuilder] OSM tidak tersedia, fallback ke polygon touching")

            # Build adjacency graph
            logger.info("=[AutoMatrixBuilder] Build adjacency graph...")
            self.adj_builder = AdjacencyBuilder(self.gdf, self.road_handler)
            G = self.adj_builder.build_graph()

            # Attach muatan + idsubsls ke setiap node
            for node in G.nodes():
                G.nodes[node][config.COL_MUATAN] = muatan_map.get(node, 0)
                G.nodes[node]["idsubsls"] = node
                if node not in muatan_map:
                    logger.warning(f"  Node {node} tidak ada di muatan, set muatan=0")

            logger.info(
                f"=[AutoMatrixBuilder] Selesai: "
                f"{G.number_of_nodes()} node, {G.number_of_edges()} edge"
            )
            return G, None

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"=[AutoMatrixBuilder] Error: {error_msg}")
            return None, error_msg

    def get_snap_quality_report(self) -> dict | None:
        """Get road snap quality info (untuk debugging)."""
        if self.road_handler:
            return self.road_handler.get_snap_quality_report()
        return None
