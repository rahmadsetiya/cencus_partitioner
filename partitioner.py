"""
partitioner.py
==============
Algoritma utama balanced connected graph partitioning.

Pendekatan hybrid:
1. Seed selection yang menyebar (k-means++ style)
2. Region growing dengan priority queue (selalu ekspansi grup terkecil)
3. Local search: swap boundary nodes untuk meningkatkan keseimbangan
4. Multi-restart: jalankan berkali-kali, ambil yang terbaik

Constraint keras:
- Setiap grup HARUS connected (subgraf yang menyambung)
- Semua SLS harus masuk ke salah satu grup
- Jumlah grup = jumlah petugas
"""

import random
import logging
import heapq
from typing import Dict, List, Optional, Set, Tuple
import numpy as np
import networkx as nx

import config

logger = logging.getLogger(__name__)


# =============================================================================
# TYPE ALIAS
# =============================================================================
Partition = Dict[str, int]   # kode_sls → group_id (0-indexed)


# =============================================================================
# MAIN CLASS
# =============================================================================

class BalancedPartitioner:
    """
    Partisi graf SLS menjadi n kelompok yang seimbang dan connected.

    Parameters
    ----------
    G : nx.Graph
        Graf aksesibilitas SLS. Node harus punya atribut 'muatan'.
        Edge harus punya atribut 'weight'.
    n_groups : int
        Jumlah kelompok (petugas sensus).
    """

    def __init__(self, G: nx.Graph, n_groups: int):
        self.G        = G
        self.n_groups = n_groups
        self.nodes    = list(G.nodes())
        self.n_nodes  = len(self.nodes)

        # Validasi input
        if n_groups < 1:
            raise ValueError("n_groups harus ≥ 1")
        if n_groups > self.n_nodes:
            raise ValueError(
                f"n_groups ({n_groups}) tidak boleh melebihi "
                f"jumlah SLS ({self.n_nodes})"
            )

        # Pre-compute muatan tiap node
        self.node_loads: Dict[str, float] = {
            node: float(G.nodes[node].get("muatan", 1))
            for node in self.nodes
        }
        self.total_load   = sum(self.node_loads.values())
        self.target_load  = self.total_load / n_groups

        logger.info(f"  Total muatan    : {self.total_load:,.0f}")
        logger.info(f"  Target per grup : {self.target_load:,.1f}")
        logger.info(f"  Jumlah grup     : {n_groups}")

        # Deteksi komponen (graf bisa tidak fully connected)
        self.components = list(nx.connected_components(G))
        if len(self.components) > 1:
            logger.warning(
                f"  Graf memiliki {len(self.components)} komponen terpisah. "
                f"Partisi dilakukan secara independen per komponen."
            )

    # =========================================================================
    # PUBLIC: Entry point
    # =========================================================================

    def run(self) -> Partition:
        """
        Jalankan partisi dengan multi-restart.

        Returns
        -------
        Partition
            Dict mapping kode_sls → group_id (0-indexed).
        """
        # Handle graf dengan multiple komponen
        if len(self.components) > 1:
            return self._partition_disconnected_graph()

        # Graf connected → jalankan multi-restart
        best_partition: Optional[Partition] = None
        best_score = float("inf")

        logger.info(f"  Menjalankan {config.N_RESTARTS} restart...")

        for restart_idx in range(config.N_RESTARTS):
            try:
                partition = self._single_run(seed=restart_idx * 31 + 13)
                score = self._imbalance_cv(partition)

                max_load = self._max_load(partition)
                min_load = self._min_load(partition)

                logger.info(
                    f"    Restart {restart_idx+1:2d}: "
                    f"CV={score:.4f}  "
                    f"max={max_load:,.0f}  "
                    f"min={min_load:,.0f}  "
                    f"selisih={max_load - min_load:,.0f}"
                )

                if score < best_score:
                    best_score = score
                    best_partition = partition.copy()

                # Early stopping jika sudah cukup seimbang
                if score <= config.IMBALANCE_TOLERANCE:
                    logger.info(
                        f"  Early stop: CV={score:.4f} ≤ "
                        f"tolerance={config.IMBALANCE_TOLERANCE}"
                    )
                    break

            except Exception as e:
                logger.warning(f"    Restart {restart_idx+1} error: {e}")
                continue

        if best_partition is None:
            logger.error("Semua restart gagal. Mencoba fallback...")
            best_partition = self._fallback_partition()

        # Log ringkasan hasil terbaik
        max_load = self._max_load(best_partition)
        min_load = self._min_load(best_partition)
        logger.info(
            f"  Hasil terbaik: CV={best_score:.4f}, "
            f"selisih maks-min = {max_load - min_load:,.0f}"
        )

        return best_partition

    # =========================================================================
    # SINGLE RUN: seed → grow → local search
    # =========================================================================

    def _single_run(self, seed: int) -> Partition:
        """Satu iterasi penuh: seed selection + region growing + local search."""
        random.seed(seed)
        np.random.seed(seed)

        seeds = self._select_seeds(seed)
        partition = self._region_growing(seeds)
        partition = self._local_search(partition)
        return partition

    # =========================================================================
    # PHASE 1: Seed selection (k-means++ style)
    # =========================================================================

    def _select_seeds(self, random_seed: int = 0) -> List[str]:
        """
        Pilih n seed node yang tersebar secara spasial.

        Algoritma (k-means++):
        - Pilih node pertama secara acak
        - Tiap node berikutnya dipilih proporsional terhadap
          jaraknya ke seed terdekat yang sudah ada
        - Sedikit random noise untuk variasi antar restart
        """
        random.seed(random_seed)
        seeds: List[str] = []

        # Node pertama: random dari semua node
        seeds.append(random.choice(self.nodes))

        # Cache jarak shortest path (komputasi berat, lakukan sekali)
        # Gunakan Euclidean-fallback jika centroid tersedia
        while len(seeds) < self.n_groups:
            max_min_dist = -1.0
            chosen_node  = None

            candidates = [n for n in self.nodes if n not in seeds]
            random.shuffle(candidates)

            # Untuk efisiensi, hitung jarak ke seed terdekat per node
            for candidate in candidates:
                min_dist = min(
                    self._graph_distance(candidate, s) for s in seeds
                )
                # Tambahkan noise proporsional untuk variasi
                noisy_dist = min_dist * (0.85 + 0.30 * random.random())

                if noisy_dist > max_min_dist:
                    max_min_dist = noisy_dist
                    chosen_node  = candidate

            if chosen_node is None:
                break
            seeds.append(chosen_node)

        return seeds

    def _graph_distance(self, node_a: str, node_b: str) -> float:
        """
        Jarak antar dua node di graph (weighted shortest path).
        Fallback ke 1.0 jika tidak ada path.
        """
        try:
            return nx.shortest_path_length(
                self.G, node_a, node_b, weight="weight"
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return 1e9  # Sangat jauh jika tidak terhubung

    # =========================================================================
    # PHASE 2: Region growing
    # =========================================================================

    def _region_growing(self, seeds: List[str]) -> Partition:
        """
        Tumbuhkan region dari seed menggunakan priority queue.

        Strategi:
        - Min-heap berisi (load_grup, group_id, node_kandidat, edge_weight)
        - Selalu ekspansi dari grup dengan total muatan TERKECIL
        - Sehingga distribusi muatan cenderung seimbang

        Edge weight digunakan sebagai tiebreaker:
        edge lebih ringan = akses lebih mudah → diprioritaskan.
        """
        partition: Partition = {}
        group_loads = [0.0] * self.n_groups

        # Assign seed nodes ke masing-masing group
        for group_id, seed in enumerate(seeds):
            partition[seed] = group_id
            group_loads[group_id] += self.node_loads[seed]

        # Inisialisasi frontier priority queue
        # Format: (group_load, random_tiebreak, group_id, candidate, edge_weight)
        frontier: List[Tuple] = []
        unassigned: Set[str] = set(self.nodes) - set(seeds)

        for group_id, seed in enumerate(seeds):
            for neighbor in self.G.neighbors(seed):
                if neighbor in unassigned:
                    edge_w = self.G[seed][neighbor].get("weight", 1.0)
                    # random untuk memecah tie secara acak (variasi antar restart)
                    heapq.heappush(
                        frontier,
                        (group_loads[group_id], random.random(), group_id, neighbor, edge_w)
                    )

        # Loop ekspansi
        while unassigned and frontier:
            load, _, group_id, candidate, edge_w = heapq.heappop(frontier)

            # Skip jika sudah di-assign (bisa masuk frontier beberapa kali)
            if candidate not in unassigned:
                continue

            # Assign candidate ke group terkecil
            partition[candidate] = group_id
            group_loads[group_id] += self.node_loads[candidate]
            unassigned.remove(candidate)

            # Tambahkan tetangga candidate ke frontier
            for neighbor in self.G.neighbors(candidate):
                if neighbor in unassigned:
                    edge_w = self.G[candidate][neighbor].get("weight", 1.0)
                    heapq.heappush(
                        frontier,
                        (group_loads[group_id], random.random(), group_id, neighbor, edge_w)
                    )

        # Handle node yang tidak terjangkau dari frontier (isolated)
        if unassigned:
            self._assign_isolated_nodes(unassigned, partition, group_loads)

        return partition

    def _assign_isolated_nodes(
        self,
        unassigned: Set[str],
        partition: Partition,
        group_loads: List[float],
    ) -> None:
        """
        Assign node yang tidak terjangkau dari frontier ke grup terdekat.
        Ini bisa terjadi jika ada isolated subcomponent.
        """
        logger.warning(
            f"  {len(unassigned)} node tidak terjangkau dari frontier. "
            f"Assigning ke grup dengan muatan terkecil..."
        )
        for node in list(unassigned):
            lightest = min(range(self.n_groups), key=lambda g: group_loads[g])
            partition[node] = lightest
            group_loads[lightest] += self.node_loads[node]

    # =========================================================================
    # PHASE 3: Local search (swap boundary nodes)
    # =========================================================================

    def _local_search(self, partition: Partition) -> Partition:
        """
        Optimasi lokal dengan memindahkan boundary node ke grup tetangga.

        Sebuah node bisa dipindah jika:
        1. Node berada di batas dua grup berbeda (boundary node)
        2. Source grup tetap CONNECTED setelah node dipindah
           (node bukan articulation point di source grup)
        3. Pemindahan mengurangi imbalance score (CV)

        Loop terus hingga tidak ada improvement atau batas iterasi tercapai.
        """
        partition = partition.copy()

        for iteration in range(config.MAX_LOCAL_SEARCH_ITER):
            improved = False

            # Identifikasi boundary nodes
            boundary = self._get_boundary_nodes(partition)
            random.shuffle(boundary)  # hindari bias posisi

            for node in boundary:
                src_group = partition[node]

                # Grup tetangga yang berbeda
                neighbor_groups = {
                    partition[nb]
                    for nb in self.G.neighbors(node)
                    if partition[nb] != src_group
                }
                if not neighbor_groups:
                    continue

                # Cek apakah node ini bisa dipindah tanpa memutus source group
                if not self._is_removable(node, src_group, partition):
                    continue

                # Evaluasi semua target group dan pilih yang terbaik
                current_cv = self._imbalance_cv(partition)
                best_target = None
                best_cv     = current_cv - 1e-8  # harus lebih baik dari sekarang

                for tgt_group in neighbor_groups:
                    # Simulasi pemindahan
                    partition[node] = tgt_group
                    new_cv = self._imbalance_cv(partition)

                    if new_cv < best_cv:
                        best_cv     = new_cv
                        best_target = tgt_group

                    # Kembalikan ke aslinya
                    partition[node] = src_group

                # Terapkan perpindahan terbaik
                if best_target is not None:
                    partition[node] = best_target
                    improved = True

            if not improved:
                logger.debug(f"    Local search konvergen di iterasi {iteration + 1}")
                break

        return partition

    # =========================================================================
    # HELPERS: Connectivity
    # =========================================================================

    def _is_removable(
        self,
        node: str,
        group_id: int,
        partition: Partition,
    ) -> bool:
        """
        Cek apakah `node` bisa dipindah dari `group_id` tanpa memutus
        konektivitas grup asal.

        Sebuah node tidak bisa dipindah jika dia adalah articulation point
        (cut vertex) dari subgraf grup asal.
        """
        # Ambil semua node di grup, kecuali node yang akan dipindah
        group_nodes = [
            n for n, g in partition.items()
            if g == group_id and n != node
        ]

        # Grup menjadi kosong → bisa dipindah (edge case)
        if not group_nodes:
            return True

        # Satu node tersisa → selalu connected
        if len(group_nodes) == 1:
            return True

        # Cek konektivitas subgraf setelah node dihapus
        subgraph = self.G.subgraph(group_nodes)
        return nx.is_connected(subgraph)

    def _get_boundary_nodes(self, partition: Partition) -> List[str]:
        """
        Identifikasi semua node yang memiliki setidaknya satu tetangga
        di grup yang berbeda.
        """
        boundary = []
        for node in self.nodes:
            node_group = partition[node]
            for nb in self.G.neighbors(node):
                if partition[nb] != node_group:
                    boundary.append(node)
                    break
        return boundary

    # =========================================================================
    # HELPERS: Scoring
    # =========================================================================

    def _compute_group_loads(self, partition: Partition) -> Dict[int, float]:
        """Hitung total muatan per grup."""
        loads = {g: 0.0 for g in range(self.n_groups)}
        for node, group_id in partition.items():
            loads[group_id] += self.node_loads[node]
        return loads

    def _imbalance_cv(self, partition: Partition) -> float:
        """
        Coefficient of Variation (CV) = std / mean.
        Makin kecil → makin seimbang.
        CV = 0 berarti semua grup sama persis muatannya.
        """
        loads = list(self._compute_group_loads(partition).values())
        mean  = np.mean(loads)
        if mean == 0:
            return 0.0
        return float(np.std(loads) / mean)

    def _max_load(self, partition: Partition) -> float:
        return max(self._compute_group_loads(partition).values())

    def _min_load(self, partition: Partition) -> float:
        return min(self._compute_group_loads(partition).values())

    # =========================================================================
    # FALLBACK: Graf dengan beberapa komponen
    # =========================================================================

    def _partition_disconnected_graph(self) -> Partition:
        """
        Partisi graf yang memiliki beberapa komponen terpisah.

        Strategi:
        - Alokasikan jumlah grup ke setiap komponen proporsional terhadap
          total muatannya.
        - Partisi tiap komponen secara independen.
        """
        partition: Partition = {}

        # Hitung muatan tiap komponen
        comp_loads = []
        for comp in self.components:
            comp_load = sum(self.node_loads[n] for n in comp)
            comp_loads.append(comp_load)

        total = sum(comp_loads)

        # Alokasi jumlah grup per komponen (proporsional, min 1)
        raw_allocs  = [max(1, round(self.n_groups * cl / total)) for cl in comp_loads]

        # Adjust agar jumlah total = n_groups
        diff = self.n_groups - sum(raw_allocs)
        if diff > 0:
            # Tambahkan ke komponen terbesar
            idx_largest = comp_loads.index(max(comp_loads))
            raw_allocs[idx_largest] += diff
        elif diff < 0:
            # Kurangi dari komponen terkecil yang ≥ 2
            for _ in range(abs(diff)):
                for i, alloc in sorted(enumerate(raw_allocs), key=lambda x: -x[1]):
                    if raw_allocs[i] > 1:
                        raw_allocs[i] -= 1
                        break

        group_offset = 0
        for comp, n_comp_groups in zip(self.components, raw_allocs):
            subgraph = self.G.subgraph(comp).copy()
            sub_part = BalancedPartitioner(subgraph, n_groups=n_comp_groups)
            sub_result = sub_part.run()

            # Offset group_id agar tidak konflik
            for node, grp in sub_result.items():
                partition[node] = grp + group_offset

            group_offset += n_comp_groups

        return partition

    def _fallback_partition(self) -> Partition:
        """
        Fallback jika semua restart gagal:
        assign setiap node ke grup berdasarkan urutan traversal BFS.
        """
        logger.warning("  Menggunakan fallback partition (BFS sequential)...")
        partition: Partition = {}
        nodes_bfs = list(nx.bfs_tree(self.G, source=self.nodes[0]).nodes())

        # Tambahkan node yang mungkin tidak terjangkau
        remaining = [n for n in self.nodes if n not in nodes_bfs]
        nodes_bfs.extend(remaining)

        chunk_size = max(1, len(nodes_bfs) // self.n_groups)
        for group_id in range(self.n_groups):
            start = group_id * chunk_size
            end   = start + chunk_size if group_id < self.n_groups - 1 else len(nodes_bfs)
            for node in nodes_bfs[start:end]:
                partition[node] = group_id

        return partition
