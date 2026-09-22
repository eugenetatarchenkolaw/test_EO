"""Case geometry checks: one simple polygon, no holes, at least 1 km².

The control area is computed along the polygon contour in EPSG:6933, not
from its bounding rectangle. This is an educational ordering convention.
"""
import json
import math
from pathlib import Path
from .pp840_helper import number, read_csv, rounded, unique_index

AREA_CRS = "EPSG:6933"
MIN_AREA_KM2 = 1.0
AREA_EPS_KM2 = 1e-9  # 0.001 m², only for coordinate round-trip noise.


def polygon_area_km2(geometry):
    from rasterio.warp import transform_geom
    from shapely.geometry import shape
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise ValueError("each order must be a single Polygon, not MultiPolygon")
    rings = geometry.get("coordinates", [])
    if len(rings) != 1:
        raise ValueError("polygon must have one exterior ring and no holes")
    ring = rings[0]
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ValueError("polygon ring must be closed and have at least three vertices")
    for point in ring:
        if len(point) != 2 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in point):
            raise ValueError("polygon coordinates must be finite longitude/latitude pairs")
        if not (-180 <= point[0] <= 180 and -86 <= point[1] <= 86):
            raise ValueError("coordinates outside the supported EPSG:6933 domain")
    if any(abs(a[0] - b[0]) > 180 for a, b in zip(ring, ring[1:])):
        raise ValueError("dateline crossing needs a separately declared area protocol")
    polygon = shape(geometry)
    if polygon.is_empty or not polygon.is_valid:
        raise ValueError("polygon must be nonempty and valid, without self-intersections")
    projected = shape(transform_geom("EPSG:4326", AREA_CRS, geometry))
    if not projected.is_valid or not math.isfinite(projected.area):
        raise ValueError("invalid projected polygon")
    area = projected.area / 1_000_000
    if area + AREA_EPS_KM2 < MIN_AREA_KM2:
        raise ValueError("order polygon area must be at least 1 km² before rounding")
    return area, projected


def audit_geometry(data):
    """Verify catalog contours and, for point portfolios, coverage relations."""
    from rasterio.warp import transform_geom
    from shapely.geometry import shape
    data = Path(data)
    config = json.loads((data / "config.json").read_text())
    rules = config["order_geometry"]
    if (rules["type"] != "Polygon" or rules["allow_holes"] is not False
            or number(rules["min_area_km2"]) != 1 or rules["area_crs"] != AREA_CRS):
        raise ValueError("unsupported order geometry convention")
    catalog = unique_index(read_csv(data / "pricing_tiles.csv"), "candidate_id")
    geo = json.loads((data / "candidates.geojson").read_text())
    if geo.get("type") != "FeatureCollection":
        raise ValueError("candidates must be a FeatureCollection")
    features = unique_index([dict(candidate_id=f["properties"]["candidate_id"], feature=f)
                             for f in geo["features"]], "candidate_id")
    if features.keys() != catalog.keys():
        raise ValueError("candidate geometry IDs differ from catalog")
    polygons = {}
    for key, record in features.items():
        area, polygon = polygon_area_km2(record["feature"]["geometry"])
        if rounded(str(area), 3) != number(catalog[key]["area_km2"]):
            raise ValueError(f"{key}: catalog area differs from polygon contour")
        polygons[key] = polygon
    assets = json.loads((data / "assets.geojson").read_text())
    if assets.get("type") != "FeatureCollection":
        raise ValueError("assets must be a FeatureCollection")
    features = unique_index([dict(asset_id=f["properties"]["asset_id"], feature=f)
                             for f in assets["features"]], "asset_id")
    exposure = unique_index(read_csv(data / "exposure.csv"), "asset_id")
    if features.keys() != exposure.keys():
        raise ValueError("asset geometry IDs differ from exposure")
    for key, record in features.items():
        props = record["feature"]["properties"]
        for field in ["aoi_id", "asset_class", "asset_value_rub", "vulnerability_coef"]:
            if str(props[field]) != exposure[key][field]:
                raise ValueError(f"{key}: asset properties differ from exposure")
    mode = rules["coverage_rule"]
    if mode not in {"point_covers", "organizer_verified_units"}:
        raise ValueError("unknown coverage rule")
    if mode == "point_covers":
        expected = set()
        for key, record in features.items():
            geom = record["feature"]["geometry"]
            if geom.get("type") != "Point":
                raise ValueError("point_covers requires a point portfolio")
            coords = geom.get("coordinates", [])
            if (len(coords) != 2 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in coords)
                    or not (-180 <= coords[0] <= 180 and -86 <= coords[1] <= 86)):
                raise ValueError("invalid asset point coordinates")
            for field, value in zip(["longitude", "latitude"], coords):
                if field in exposure[key] and abs(float(number(exposure[key][field])) - value) > 1e-10:
                    raise ValueError(f"{key}: coordinates differ from exposure")
            point = shape(transform_geom("EPSG:4326", AREA_CRS, geom))
            expected.update((candidate, key) for candidate, polygon in polygons.items() if polygon.covers(point))
        rows = read_csv(data / "candidate_units.csv")
        actual = {(r["candidate_id"], r["unit_id"]) for r in rows}
        if len(rows) != len(actual) or actual != expected:
            raise ValueError("candidate-unit relations differ from point coverage")
    return {"candidate_polygons": len(polygons), "minimum_area_km2": MIN_AREA_KM2,
            "area_crs": AREA_CRS, "coverage_check": mode}
