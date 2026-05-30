"""
adjacency_builder.py
====================
Membangun weighted accessibility graph antar SLS.

Pendekatan hybrid:
1. Polygon touching sebagai kandidat adjacency awal
2. Validasi dan pembobotan via jarak jalan (OSM)
3. Fallback ke polygon touching murni jika road network tidak tersedia

Output: nx.Graph dengan:
- Node: kode_sls, atribut muatan
- Edge: weight (difficulty score, makin kecil = makin mudah diakses)
"""

import logging

import geopandas as gpd
import networkx as nx
import numpy as np

import config
from road_network import RoadNetworkHandler

logger = logging.getLogger(__name__)


class AdjacencyBuilder:
    """
    Membangun graf aksesibilitas SLS dari kombinasi polygon touching dan road network.
    """

    def __init__(self, gdf: gpd.GeoDataFrame, road_handler: RoadNetworkHandler):
        """
        Parameters
        ----------
        gdf : gpd.GeoDataFrame
            GeoDataFrame SLS dengan kode_sls, muatan, dan geometry.
        road_handler : RoadNetworkHandler
            Handler road network yang sudah di-download dan di-snap.
        """
        self.gdf = gdf.copy()
        self.road_handler = road_handler

        # Proyeksikan ke CRS metrik untuk operasi spatial yang akurat
        self.gdf_proj = gdf.to_crs(epsg=config.EPSG_METRIC)

        # Buat dict untuk akses cepat: kode_sls → row
        self.sls_dict = {row[config.COL_KODE_SLS]: row for _, row in self.gdf.iterrows()}

    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================

    def build_graph(self) -> nx.Graph:
        """
        Bangun graf aksesibilitas lengkap.

        Returns
        -------
        nx.Graph
            Graf dengan node = kode_sls dan edge berbobot.
        """
        G = nx.Graph()

        # ----------------------------------------------------------------
        # 1. Tambahkan semua SLS sebagai node
        # ----------------------------------------------------------------
        for _, row in self.gdf.iterrows():
            kode = row[config.COL_KODE_SLS]
            G.add_node(
                kode,
                muatan=float(row[config.COL_MUATAN]),
                centroid_lon=row.get("centroid_lon", 0.0),
                centroid_lat=row.get("centroid_lat", 0.0),
            )
        logger.info(f"  {G.number_of_nodes()} node ditambahkan ke graph")

        # ----------------------------------------------------------------
        # 2. Generate kandidat pasangan SLS yang berpotensi terhubung
        # ----------------------------------------------------------------
        candidate_pairs = self._get_candidate_pairs()
        logger.info(f"  {len(candidate_pairs)} pasangan kandidat adjacency ditemukan")

        # ----------------------------------------------------------------
        # 3. Evaluasi setiap pasangan dan buat edge
        # ----------------------------------------------------------------
        edges_added = 0
        edges_road_validated = 0
        edges_polygon_only = 0

        for kode_a, kode_b, is_touching in candidate_pairs:
            # Coba dapatkan jarak jalan
            road_dist_m = self.road_handler.get_road_distance(kode_a, kode_b)

            # Tentukan apakah edge ini valid
            should_add_edge = False
            weight = None

            if road_dist_m is not None:
                # Road distance tersedia
                if road_dist_m <= config.ROAD_DISTANCE_THRESHOLD_M or is_touching:
                    should_add_edge = True
                    weight = self._compute_difficulty_score(
                        road_dist_m=road_dist_m,
                        is_touching=is_touching,
                    )
                    edges_road_validated += 1

            elif is_touching:
                # Tidak ada road distance, tapi polygon bersinggungan
                # Gunakan weight default
                should_add_edge = True
                weight = config.DEFAULT_TOUCHING_WEIGHT
                edges_polygon_only += 1

            if should_add_edge:
                G.add_edge(
                    kode_a,
                    kode_b,
                    weight=weight,
                    road_dist_m=road_dist_m if road_dist_m is not None else -1,
                    is_touching=is_touching,
                )
                edges_added += 1

        logger.info(
            f"  Total edge: {edges_added} "
            f"(road-validated: {edges_road_validated}, "
            f"polygon-only: {edges_polygon_only})"
        )

        # ----------------------------------------------------------------
        # 4. Cek konektivitas dan warn jika ada komponen terpisah
        # ----------------------------------------------------------------
        self._check_connectivity(G)

        return G

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _get_candidate_pairs(self) -> list[tuple[str, str, bool]]:
        """
        Generate kandidat pasangan SLS yang berpotensi bertetangga.

        Returns
        -------
        List of (kode_a, kode_b, is_touching)
        """
        pairs: set[tuple[str, str, bool]] = set()

        # ----------------------------------------------------------------
        # A. Polygon touching (dengan buffer kecil untuk toleransi numerik)
        # ----------------------------------------------------------------
        touching_pairs = self._get_touching_pairs()
        for kode_a, kode_b in touching_pairs:
            # Normalisasi urutan agar tidak duplikat
            key = (min(kode_a, kode_b), max(kode_a, kode_b))
            pairs.add((key[0], key[1], True))

        if config.TOUCHING_ONLY:
            # Hanya gunakan polygon touching
            return [(a, b, t) for a, b, t in pairs]

        # ----------------------------------------------------------------
        # B. Tambahkan pasangan berdasarkan road distance threshold
        #    (hanya jika road network tersedia)
        # ----------------------------------------------------------------
        if self.road_handler.is_road_available():
            road_pairs = self._get_road_proximity_pairs()
            touching_kodes = {(a, b) for a, b, _ in pairs}

            for kode_a, kode_b in road_pairs:
                key = (min(kode_a, kode_b), max(kode_a, kode_b))
                is_touching = key in touching_kodes
                pairs.add((key[0], key[1], is_touching))

        return [(a, b, t) for a, b, t in pairs]

    def _get_touching_pairs(self) -> list[tuple[str, str]]:
        """
        Deteksi pasangan SLS yang polygonnya bersinggungan.

        Menggunakan spatial index (STRtree) untuk efisiensi O(n log n).
        """
        touching_pairs = []
        kodes = list(self.gdf_proj[config.COL_KODE_SLS])
        geoms = list(self.gdf_proj.geometry)

        # Buffer kecil untuk toleransi floating point
        # (polygon yang "hampir touching" tapi tidak persis)
        buffer_m = config.TOUCHING_BUFFER_M
        buffered_geoms = [g.buffer(buffer_m) for g in geoms]

        # Gunakan spatial index untuk cari kandidat
        from shapely.strtree import STRtree

        tree = STRtree(buffered_geoms)

        for idx_a, (kode_a, buf_a) in enumerate(zip(kodes, buffered_geoms)):
            # Query spatial index untuk kandidat yang bounding box-nya overlap
            candidate_indices = tree.query(buf_a)

            for idx_b in candidate_indices:
                if idx_b <= idx_a:
                    # Hindari duplikat dan self-loop
                    continue

                kode_b = kodes[idx_b]
                buf_b = buffered_geoms[idx_b]

                # Cek apakah benar-benar bersentuhan/overlap
                if buf_a.intersects(buf_b):
                    # Double check: pastikan polygon asli (bukan buffer) juga
                    # minimal sangat dekat
                    orig_a = geoms[idx_a]
                    orig_b = geoms[idx_b]
                    dist = orig_a.distance(orig_b)
                    if dist <= buffer_m * 2:
                        touching_pairs.append((kode_a, kode_b))

        return touching_pairs

    def _get_road_proximity_pairs(self) -> list[tuple[str, str]]:
        """
        Generate pasangan SLS yang centroidnya dalam ROAD_DISTANCE_THRESHOLD.

        Menggunakan STRtree buffer query — O(n log n) bukan O(n²).
        """
        from shapely.geometry import Point
        from shapely.strtree import STRtree

        threshold = config.ROAD_DISTANCE_THRESHOLD_M
        # Faktor 0.5: Euclidean pre-filter sebelum road distance aktual
        euclidean_threshold = threshold * 0.5

        kodes = []
        centroid_pts = []
        for _, row in self.gdf_proj.iterrows():
            kodes.append(row[config.COL_KODE_SLS])
            centroid_pts.append(row.geometry.centroid)

        # Buffer tiap centroid, lalu query STRtree untuk overlap
        buffered = [pt.buffer(euclidean_threshold) for pt in centroid_pts]
        tree = STRtree(buffered)

        proximity_pairs = []
        for idx_a, buf_a in enumerate(buffered):
            for idx_b in tree.query(buf_a):
                if idx_b <= idx_a:
                    continue
                proximity_pairs.append((kodes[idx_a], kodes[idx_b]))

        return proximity_pairs

    def _compute_difficulty_score(
        self,
        road_dist_m: float,
        is_touching: bool,
    ) -> float:
        """
        Hitung difficulty score untuk sebuah edge.

        Score ini merepresentasikan "seberapa sulit" perjalanan dari
        satu SLS ke SLS lainnya. Makin kecil = makin mudah.

        Formula:
            score = WEIGHT_DISTANCE * (road_dist_m / 1000)  [dalam km]
                  + WEIGHT_TOUCHING * (0 jika touching, 1 jika tidak)

        Parameters
        ----------
        road_dist_m : float
            Jarak jalan dalam meter.
        is_touching : bool
            True jika polygon bersinggungan langsung.

        Returns
        -------
        float
            Difficulty score (≥ 0)
        """
        dist_km = road_dist_m / 1_000.0
        touching_penalty = 0.0 if is_touching else config.WEIGHT_TOUCHING

        score = (config.WEIGHT_DISTANCE * dist_km) + touching_penalty
        return round(score, 4)

    def _check_connectivity(self, G: nx.Graph) -> None:
        """Cek dan laporkan konektivitas graf."""
        if nx.is_connected(G):
            logger.info("  Graf aksesibilitas TERHUBUNG penuh (1 komponen).")
        else:
            components = list(nx.connected_components(G))
            n_comp = len(components)
            logger.warning(
                f"  PERINGATAN: Graf memiliki {n_comp} komponen terpisah! "
                f"Partisi akan dilakukan per komponen."
            )
            # Log ukuran tiap komponen
            for i, comp in enumerate(sorted(components, key=len, reverse=True)):
                logger.warning(
                    f"    Komponen {i + 1}: {len(comp)} SLS — "
                    f"{list(comp)[:3]}{'...' if len(comp) > 3 else ''}"
                )
