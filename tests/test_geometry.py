"""Check the agreed geometry rules and the ten-object demo independently."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from rasterio.warp import transform_geom
from shapely.geometry import Polygon, MultiPolygon, mapping, shape, Point
from tools.geometry import AREA_CRS, audit_geometry, polygon_area_km2
from tools.pp840_helper import read_csv, price_plan

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "data/demo"


def geographic(poly):
    return transform_geom(AREA_CRS, "EPSG:4326", mapping(poly))


class GeometryTests(unittest.TestCase):
    def test_exact_minimum_and_below_minimum_before_rounding(self):
        area, _ = polygon_area_km2(geographic(Polygon([(0,0),(1000,0),(1000,1000),(0,1000)])))
        self.assertAlmostEqual(area, 1, places=8)
        for width in [10, 999.6]:
            with self.subTest(width=width), self.assertRaisesRegex(ValueError, "at least 1"):
                polygon_area_km2(geographic(Polygon([(0,0),(width,0),(width,1000),(0,1000)])))

    def test_concave_contour_not_bounding_box(self):
        geo = json.loads((DEMO / "candidates.geojson").read_text())
        geometry = next(f["geometry"] for f in geo["features"] if f["properties"]["candidate_id"] == "DEMO_O2")
        area, polygon = polygon_area_km2(geometry)
        self.assertAlmostEqual(area, 2, places=7)
        self.assertAlmostEqual(polygon.envelope.area / 1e6, 2.5, places=7)
        self.assertLess(polygon.area, polygon.convex_hull.area)

    def test_holes_multipolygon_and_self_crossing_rejected(self):
        outer = [(0,0),(2000,0),(2000,2000),(0,2000)]
        hole = [(200,200),(400,200),(400,400),(200,400)]
        for geometry in [geographic(Polygon(outer,[hole])),
                         geographic(MultiPolygon([Polygon(outer)])),
                         geographic(Polygon([(0,0),(2000,2000),(2000,0),(0,2000)]))]:
            with self.subTest(geometry=geometry["type"]), self.assertRaises(ValueError):
                polygon_area_km2(geometry)

    def test_ten_objects_on_one_chip_and_consistent_coverage(self):
        rows = read_csv(DEMO / "exposure.csv")
        self.assertEqual(len(rows), 10)
        self.assertEqual({r["chip_id"] for r in rows}, {"DEMO_CHIP3"})
        report = audit_geometry(DEMO)
        self.assertEqual(report["candidate_polygons"], 4)
        chip = shape(json.loads((DEMO / "chip_footprint.geojson").read_text())["features"][0]["geometry"])
        for row in rows:
            self.assertTrue(chip.covers(Point(float(row["longitude"]),float(row["latitude"]))))
        relations = read_csv(DEMO / "candidate_units.csv")
        ids = {r["unit_id"] for r in relations if r["candidate_id"] in {"DEMO_O1","DEMO_O2"}}
        self.assertEqual(ids, {"DEMO_A1","DEMO_A2","DEMO_A3","DEMO_A6","DEMO_A7","DEMO_A8","DEMO_A9"})

    def test_tampered_area_and_coverage_are_rejected(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as folder:
            data = Path(folder) / "data"
            shutil.copytree(DEMO,data)
            path = data / "pricing_tiles.csv"
            original = path.read_text()
            path.write_text(original.replace("DEMO_O2,2.000,", "DEMO_O2,2.500,"))
            with self.assertRaisesRegex(ValueError, "differs from polygon"):
                audit_geometry(data)
            path.write_text(original)
            relations = data / "candidate_units.csv"
            relations.write_text(relations.read_text().replace("DEMO_O1,DEMO_A1\n", ""))
            with self.assertRaisesRegex(ValueError, "differ from point coverage"):
                audit_geometry(data)

    def test_price_helper_rejects_subminimum_order(self):
        rows = read_csv(DEMO / "pricing_tiles.csv")
        rows[0]["area_km2"] = ".999"
        with self.assertRaisesRegex(ValueError, "at least 1"):
            price_plan(rows,["DEMO_O1"],json.loads((DEMO / "config.json").read_text()))


if __name__ == "__main__":
    unittest.main()
