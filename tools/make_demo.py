"""Rebuild ten synthetic assets and four illustrative order contours, not an optimizer."""
import csv
import json
from pathlib import Path
from rasterio.warp import transform, transform_geom
from shapely.geometry import Polygon, Point, mapping
from .geometry import AREA_CRS

ROOT = Path(__file__).parents[1]
DATA = ROOT / "data/demo"


def write_json(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collection(features):
    return {"type": "FeatureCollection", "features": features}


def main():
    # Coordinates and values are fictitious. All objects belong to one demo chip.
    x0, y0 = (c[0] for c in transform("EPSG:4326", AREA_CRS, [30], [50]))
    specifications = [
        ("warehouse", "10000000", ".25", 300, 300),
        ("substation", "20000000", ".4", 800, 700),
        ("road_unit", "5000000", ".3", 1400, 500),
        ("facility", "8000000", ".2", 300, 1800),
        ("pumping_station", "12000000", ".35", 700, 1300),
        ("clinic", "30000000", ".15", 2100, 500),
        ("school", "18000000", ".2", 1200, 1100),
        ("workshop", "6000000", ".45", 2300, 650),
        ("telecom_node", "4000000", ".5", 900, 900),
        ("water_intake", "16000000", ".3", 1300, 1700),
    ]
    assets, features, points = [], [], {}
    for i, (kind, value, vulnerability, x, y) in enumerate(specifications, 1):
        key = f"DEMO_A{i}"
        point = Point(x0+x, y0+y)
        points[key] = point
        geometry = transform_geom(AREA_CRS, "EPSG:4326", mapping(point))
        lon, lat = geometry["coordinates"]
        row = dict(asset_id=key, aoi_id="DEMO_AOI3", chip_id="DEMO_CHIP3", asset_class=kind,
                   asset_value_rub=value, vulnerability_coef=vulnerability, value_date="2026-09-01",
                   value_basis="synthetic_replacement_value", longitude=str(lon), latitude=str(lat))
        assets.append(row)
        features.append({"type": "Feature", "properties": row, "geometry": geometry})
    write_json("assets.geojson", collection(features))
    with (DATA / "exposure.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(assets[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(assets)
    contours = {
        "DEMO_O1": [(0,0),(1000,0),(1000,1000),(0,1000)],
        "DEMO_O2": [(500,0),(2500,0),(2500,750),(1500,750),(1500,1250),(500,1250)],
        "DEMO_S1": [(0,0),(1500,0),(1500,2000),(0,2000)],
        "DEMO_ARCHIVE": [(0,0),(1000,0),(1000,1000),(0,1000)],
    }
    features, relations = [], []
    for key, vertices in contours.items():
        poly = Polygon([(x0+x, y0+y) for x,y in vertices])
        features.append({"type": "Feature", "properties": {"candidate_id": key, "synthetic": True},
                         "geometry": transform_geom(AREA_CRS, "EPSG:4326", mapping(poly))})
        relations.extend({"candidate_id": key, "unit_id": asset_id}
                         for asset_id, point in points.items() if poly.covers(point))
    write_json("candidates.geojson", collection(features))
    with (DATA / "candidate_units.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["candidate_id", "unit_id"], lineterminator="\n")
        writer.writeheader(); writer.writerows(relations)
    chip = Polygon([(x0,y0),(x0+2560,y0),(x0+2560,y0+2560),(x0,y0+2560)])
    write_json("chip_footprint.geojson", collection([{"type":"Feature",
        "properties":{"chip_id":"DEMO_CHIP3", "aoi_id":"DEMO_AOI3", "synthetic":True},
        "geometry": transform_geom(AREA_CRS, "EPSG:4326", mapping(chip))}]))
    config = json.loads((DATA / "config.json").read_text())
    config["order_geometry"] = {"type": "Polygon", "allow_holes": False, "min_area_km2": "1.000",
                                "area_crs": AREA_CRS, "coverage_rule": "point_covers"}
    write_json("config.json", config)
    manifest = json.loads((DATA / "dataset_manifest.json").read_text())
    manifest.update(version="demo-1.1", assets=10, assets_per_demo_chip=10,
                    demo_asset_chip="DEMO_CHIP3", coverage_source="projected polygon covers(point)",
                    generator="python -m tools.make_demo")
    write_json("dataset_manifest.json", manifest)
    print("Generated 10 synthetic assets, 4 polygons and their coverage relations.")


if __name__ == "__main__":
    main()
