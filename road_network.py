"""
road_network.py
===============
Mengunduh jaringan jalan dari OpenStreetMap via OSMnx dan
menyediakan fungsi shortest path antar SLS.

Kelas utama:
- RoadNetworkHandler  → download, snap, dan hitung jarak jalan
"""

import logging
from typing import Optional, Dict, Tuple
import numpy as np
import geopandas as gpd
import networkx as nx

import config

logger = logging.getLogger(__name__)

# Import osmnx dengan graceful error jika tidak terinstall
try:
    import osmnx as ox
    OSMNX_AVAILABLE = True
except ImportError:
    OSMNX_AVAILABLE = False
    logger.warning(
        "OSMnx tidak terinstall. Sistem akan menggunakan "
        "polygon touching saja sebagai adjacency."
    )


class RoadNetworkHandler:
    """
    Mengelola jaringan jalan OSM dan perhitungan aksesibilitas.

    Atribut
    -------
    road_graph : nx.MultiDiGraph or None
        Graf jaringan jalan dari OSM. None jika download gagal.
    snap_node_map : dict
        Mapping kode_sls → nearest OSM node id.
    snap_distance_map : dict
        Mapping kode_sls → jarak snap ke OSM node (meter).
    """

    def __init__(self, gdf: gpd.GeoDataFrame):
        """
        Parameters
        ----------
        gdf : gpd.GeoDataFrame
            GeoDataFrame SLS dengan kolom kode_sls dan geometry.
        """
        self.gdf = gdf
        self.road_graph: Optional[nx.MultiDiGraph] = None
        self.snap_node_map: Dict[str, int] = {}
        self.snap_distance_map: Dict[str, float] = {}
        self._osm_available = OSMNX_AVAILABLE

    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================

    def download_network(self) -> None:
        """
        Download jaringan jalan dari OSM untuk area bounding box SLS.

        Jika download gagal (tidak ada internet, area terpencil, dll.),
        sistem akan otomatis fallback ke mode polygon touching.
        """
        if not self._osm_available:
            logger.warning("  OSMnx tidak tersedia, skip download.")
            return

        try:
            # Hitung bounding box dengan buffer
            bounds = self.gdf.total_bounds  # [minx, miny, maxx, maxy]
            north = bounds[3] + config.OSM_BUFFER_DEG
            south = bounds[1] - config.OSM_BUFFER_DEG
            east  = bounds[2] + config.OSM_BUFFER_DEG
            west  = bounds[0] - config.OSM_BUFFER_DEG

            logger.info(
                f"  Download road network: "
                f"N={north:.4f}, S={south:.4f}, "
                f"E={east:.4f}, W={west:.4f}"
            )

            # Download dari OSM
            # simplify=True menghapus node intermediate untuk efisiensi
            self.road_graph = ox.graph_from_bbox(
                north=north,
                south=south,
                east=east,
                west=west,
                network_type=config.NETWORK_TYPE,
                simplify=True,
            )

            n_nodes = self.road_graph.number_of_nodes()
            n_edges = self.road_graph.number_of_edges()
            logger.info(f"  Road network berhasil: {n_nodes:,} node, {n_edges:,} edge")

        except Exception as e:
            logger.warning(
                f"  Download road network gagal: {e}. "
                f"Sistem akan menggunakan polygon touching saja."
            )
            self.road_graph = None

    def snap_centroids(self, gdf: gpd.GeoDataFrame) -> None:
        """
        Snap centroid setiap SLS ke node jalan terdekat di OSM.

        Hasil disimpan di:
        - self.snap_node_map      → kode_sls: osm_node_id
        - self.snap_distance_map  → kode_sls: jarak_meter

        Node yang terlalu jauh (> MAX_SNAP_DISTANCE_M) dicatat
        sebagai unsnapped dan tidak akan punya akses road distance.
        """
        if self.road_graph is None:
            logger.info("  Snap centroid dilewati (road graph tidak tersedia).")
            return

        logger.info("  Melakukan snap centroid ke jaringan jalan...")

        unsnapped_count = 0

        for _, row in gdf.iterrows():
            kode = row[config.COL_KODE_SLS]
            lon = row["centroid_lon"]
            lat = row["centroid_lat"]

            try:
                # Cari OSM node terdekat
                nearest_node, dist = ox.nearest_nodes(
                    self.road_graph,
                    X=lon,
                    Y=lat,
                    return_dist=True,
                )

                if dist > config.MAX_SNAP_DISTANCE_M:
                    # Terlalu jauh dari jalan → tandai sebagai unsnapped
                    logger.debug(
                        f"    {kode}: centroid terlalu jauh dari jalan "
                        f"({dist:.0f}m > {config.MAX_SNAP_DISTANCE_M}m)"
                    )
                    unsnapped_count += 1
                    # Tetap simpan, tapi tandai dengan None
                    self.snap_node_map[kode] = nearest_node
                    self.snap_distance_map[kode] = dist
                else:
                    self.snap_node_map[kode] = nearest_node
                    self.snap_distance_map[kode] = dist

            except Exception as e:
                logger.debug(f"    Snap gagal untuk {kode}: {e}")
                unsnapped_count += 1

        snapped_count = len(self.snap_node_map)
        logger.info(
            f"  Snap selesai: {snapped_count} berhasil, "
            f"{unsnapped_count} di luar threshold jalan."
        )

    def get_road_distance(
        self,
        kode_a: str,
        kode_b: str,
    ) -> Optional[float]:
        """
        Hitung jarak terpendek via jaringan jalan antara dua SLS (meter).

        Parameters
        ----------
        kode_a, kode_b : str
            kode_sls dari dua SLS yang akan dihitung jaraknya.

        Returns
        -------
        float or None
            Jarak jalan dalam meter. None jika:
            - Road graph tidak tersedia
            - Salah satu SLS tidak ter-snap ke jalan
            - Tidak ada path yang menghubungkan keduanya
        """
        if self.road_graph is None:
            return None

        node_a = self.snap_node_map.get(kode_a)
        node_b = self.snap_node_map.get(kode_b)

        if node_a is None or node_b is None:
            return None

        try:
            # Shortest path berdasarkan panjang jalan (meter)
            path_length = nx.shortest_path_length(
                self.road_graph,
                source=node_a,
                target=node_b,
                weight="length",
            )
            return float(path_length)

        except nx.NetworkXNoPath:
            return None
        except nx.NodeNotFound:
            return None

    def is_road_available(self) -> bool:
        """Cek apakah road network berhasil dimuat."""
        return self.road_graph is not None

    def get_snap_quality_report(self) -> Dict:
        """
        Laporan kualitas snap — berguna untuk debugging.

        Returns
        -------
        dict dengan keys: total_snapped, within_threshold, mean_snap_dist_m
        """
        if not self.snap_distance_map:
            return {"total_snapped": 0, "within_threshold": 0, "mean_snap_dist_m": None}

        dists = list(self.snap_distance_map.values())
        within = sum(1 for d in dists if d <= config.MAX_SNAP_DISTANCE_M)

        return {
            "total_snapped": len(dists),
            "within_threshold": within,
            "beyond_threshold": len(dists) - within,
            "mean_snap_dist_m": float(np.mean(dists)),
            "max_snap_dist_m": float(np.max(dists)),
        }
