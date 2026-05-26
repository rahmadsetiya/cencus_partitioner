"""
main.py
=======
Entry point sistem partisi wilayah petugas sensus.

Mengorkestrasi seluruh pipeline:
  1. Load GeoJSON
  2. Hitung centroid
  3. Download road network (OSM)
  4. Snap centroid ke jalan
  5. Bangun weighted accessibility graph
  6. Terapkan manual override (opsional)
  7. Partisi balanced connected
  8. Generate output Excel
  9. Buat visualisasi peta

Contoh penggunaan:
    # Via CLI
    python main.py sls_enrekang.geojson 10 --override manual_override.xlsx

    # Via kode Python
    from main import run_pipeline
    partition = run_pipeline("sls.geojson", n_officers=8)
"""

import sys
import logging
import argparse
from pathlib import Path

import geopandas as gpd

import config
from data_loader import load_geojson
from road_network import RoadNetworkHandler
from adjacency_builder import AdjacencyBuilder
from manual_override import apply_manual_override
from partitioner import BalancedPartitioner
from output_generator import OutputGenerator
from visualizer import MapVisualizer, save_static_map

# =============================================================================
# LOGGING SETUP
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run_pipeline(
    geojson_path: str,
    n_officers: int,
    override_path: str = None,
    output_excel: str = None,
    output_map: str = None,
    epsg_metric: int = None,
) -> dict:
    """
    Pipeline lengkap partisi wilayah petugas sensus.

    Parameters
    ----------
    geojson_path : str
        Path ke file GeoJSON berisi polygon SLS.
        Setiap fitur wajib memiliki kolom 'kode_sls' dan 'muatan'.
    n_officers : int
        Jumlah petugas sensus = jumlah kelompok yang diinginkan.
    override_path : str, optional
        Path ke file manual_override.xlsx untuk koreksi adjacency lapangan.
    output_excel : str, optional
        Path output Excel. Default: config.OUTPUT_EXCEL
    output_map : str, optional
        Path output peta HTML. Default: config.OUTPUT_MAP_HTML
    epsg_metric : int, optional
        EPSG CRS metrik untuk proyeksi. Default: config.EPSG_METRIC (32750).
        Ubah sesuai lokasi wilayah kerja:
        - 32750 → Sulawesi, Kalimantan, Maluku
        - 32749 → Jawa Tengah-Timur, Bali, NTB, NTT
        - 32748 → Sumatera, Jawa Barat

    Returns
    -------
    dict
        Partition result: {'kode_sls': group_id, ...}
    """
    # Override EPSG jika disediakan
    if epsg_metric:
        config.EPSG_METRIC = epsg_metric

    output_excel = output_excel or config.OUTPUT_EXCEL
    output_map   = output_map   or config.OUTPUT_MAP_HTML

    logger.info("=" * 60)
    logger.info("  SISTEM PARTISI WILAYAH PETUGAS SENSUS")
    logger.info("=" * 60)

    # =========================================================================
    # TAHAP 1: Load & validasi GeoJSON
    # =========================================================================
    logger.info("[1/9] Memuat data GeoJSON...")
    gdf = load_geojson(geojson_path)
    logger.info(f"      {len(gdf)} SLS dimuat, total muatan = {gdf[config.COL_MUATAN].sum():,.0f}")

    # Validasi jumlah petugas vs SLS
    if n_officers > len(gdf):
        raise ValueError(
            f"Jumlah petugas ({n_officers}) melebihi jumlah SLS ({len(gdf)}). "
            f"Maksimum petugas: {len(gdf)}"
        )
    if n_officers < 1:
        raise ValueError("Jumlah petugas harus ≥ 1")

    # =========================================================================
    # TAHAP 2: Hitung centroid
    # =========================================================================
    logger.info("[2/9] Menghitung centroid SLS...")
    gdf_proj   = gdf.to_crs(epsg=config.EPSG_METRIC)
    centroids  = gdf_proj.geometry.centroid.to_crs(epsg=config.EPSG_GEO)
    gdf["centroid_geom"] = centroids
    gdf["centroid_lon"]  = centroids.x
    gdf["centroid_lat"]  = centroids.y
    logger.info(f"      Centroid berhasil dihitung.")

    # =========================================================================
    # TAHAP 3: Download road network
    # =========================================================================
    logger.info("[3/9] Mengunduh jaringan jalan dari OSM...")
    road_handler = RoadNetworkHandler(gdf)
    road_handler.download_network()

    # Laporan kualitas snap (info saja)
    if road_handler.is_road_available():
        logger.info(f"      Road network tersedia.")
    else:
        logger.warning("      Road network tidak tersedia. Fallback ke polygon touching.")

    # =========================================================================
    # TAHAP 4: Snap centroid ke jaringan jalan
    # =========================================================================
    logger.info("[4/9] Snap centroid ke node jalan terdekat...")
    road_handler.snap_centroids(gdf)

    if road_handler.is_road_available():
        report = road_handler.get_snap_quality_report()
        logger.info(
            f"      Snap: {report['within_threshold']} dalam threshold, "
            f"{report['beyond_threshold']} di luar threshold, "
            f"rata-rata {report.get('mean_snap_dist_m', 0):.0f}m"
        )

    # =========================================================================
    # TAHAP 5: Bangun accessibility graph
    # =========================================================================
    logger.info("[5/9] Membangun weighted accessibility graph...")
    adj_builder = AdjacencyBuilder(gdf, road_handler)
    G           = adj_builder.build_graph()
    logger.info(f"      Graph: {G.number_of_nodes()} node, {G.number_of_edges()} edge")

    # =========================================================================
    # TAHAP 6: Manual override
    # =========================================================================
    if override_path and Path(override_path).exists():
        logger.info("[6/9] Menerapkan manual override...")
        G = apply_manual_override(G, override_path)
    else:
        if override_path:
            logger.warning(f"[6/9] File override tidak ditemukan: {override_path}")
        else:
            logger.info("[6/9] Tidak ada manual override (dilewati).")

    # =========================================================================
    # TAHAP 7: Partisi balanced connected
    # =========================================================================
    logger.info(f"[7/9] Mempartisi {len(gdf)} SLS ke {n_officers} petugas...")
    partitioner = BalancedPartitioner(G, n_groups=n_officers)
    partition   = partitioner.run()

    # =========================================================================
    # TAHAP 8: Generate output Excel
    # =========================================================================
    logger.info("[8/9] Membuat output Excel...")
    output_gen = OutputGenerator(gdf, G, partition, n_officers)
    output_gen.save_excel(output_excel)

    # Cetak ringkasan ke terminal
    output_gen.print_summary()

    # =========================================================================
    # TAHAP 9: Visualisasi peta
    # =========================================================================
    logger.info("[9/9] Membuat visualisasi peta...")
    try:
        viz = MapVisualizer(gdf, partition, n_officers)
        viz.save_html(output_map)
    except ImportError:
        logger.warning("      Folium tidak tersedia. Mencoba matplotlib...")
        try:
            png_path = output_map.replace(".html", ".png")
            save_static_map(gdf, partition, n_officers, png_path)
        except Exception as e:
            logger.warning(f"      Visualisasi gagal: {e}")
    except Exception as e:
        logger.warning(f"      Visualisasi gagal: {e}")

    logger.info("=" * 60)
    logger.info(f"  SELESAI. Output: {output_excel}, {output_map}")
    logger.info("=" * 60)

    return partition


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Sistem Partisi Wilayah Petugas Sensus\n"
            "Membagi SLS menjadi kelompok yang connected dan seimbang muatannya."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  # Bagi 13 SLS untuk 4 petugas, tanpa override:
  python main.py data/sls_enrekang.geojson 4

  # Dengan override lapangan dan UTM Zone 49S (Jawa):
  python main.py data/sls.geojson 8 --override koreksi.xlsx --epsg 32749

  # Tentukan path output:
  python main.py data/sls.geojson 6 --output-excel hasil.xlsx --output-map peta.html
        """,
    )

    parser.add_argument(
        "geojson",
        help="Path ke file GeoJSON berisi polygon SLS",
    )
    parser.add_argument(
        "n_officers",
        type=int,
        help="Jumlah petugas sensus (= jumlah kelompok)",
    )
    parser.add_argument(
        "--override",
        metavar="EXCEL_PATH",
        help="Path ke file manual_override.xlsx",
        default=None,
    )
    parser.add_argument(
        "--output-excel",
        metavar="PATH",
        help=f"Path output Excel (default: {config.OUTPUT_EXCEL})",
        default=None,
    )
    parser.add_argument(
        "--output-map",
        metavar="PATH",
        help=f"Path output peta HTML (default: {config.OUTPUT_MAP_HTML})",
        default=None,
    )
    parser.add_argument(
        "--epsg",
        type=int,
        metavar="EPSG_CODE",
        help=(
            f"EPSG CRS metrik untuk proyeksi (default: {config.EPSG_METRIC}). "
            f"32750=Sulawesi, 32749=Jawa Tengah-Timur, 32748=Sumatera/Jawa Barat"
        ),
        default=None,
    )
    parser.add_argument(
        "--restarts",
        type=int,
        help=f"Jumlah restart algoritma (default: {config.N_RESTARTS})",
        default=None,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Aktifkan logging level DEBUG",
    )
    parser.add_argument(
        "--generate-template",
        action="store_true",
        help="Buat template manual_override.xlsx dan keluar",
    )

    args = parser.parse_args()

    # -------------------------------------------------------------------------
    # Mode: Generate template
    # -------------------------------------------------------------------------
    if args.generate_template:
        from manual_override import generate_override_template
        generate_override_template("manual_override_template.xlsx")
        print("Template berhasil dibuat: manual_override_template.xlsx")
        return

    # -------------------------------------------------------------------------
    # Atur logging level
    # -------------------------------------------------------------------------
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Mode DEBUG aktif.")

    # -------------------------------------------------------------------------
    # Override config dari argumen CLI
    # -------------------------------------------------------------------------
    if args.restarts:
        config.N_RESTARTS = args.restarts

    # -------------------------------------------------------------------------
    # Jalankan pipeline
    # -------------------------------------------------------------------------
    try:
        run_pipeline(
            geojson_path=args.geojson,
            n_officers=args.n_officers,
            override_path=args.override,
            output_excel=args.output_excel,
            output_map=args.output_map,
            epsg_metric=args.epsg,
        )
    except FileNotFoundError as e:
        logger.error(f"File tidak ditemukan: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Input tidak valid: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Error tidak terduga: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
