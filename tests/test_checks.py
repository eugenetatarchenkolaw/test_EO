"""Small arithmetic/contract fixtures, not a model or a procurement solution."""
import csv
import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from decimal import Decimal as D
from tools.pp840_helper import (PRICE_FIELDS, discount_coefficient, freshness_coefficient,
                                number, price_plan, read_csv)
from tools.audit_data import audit
from tools.validate_submission import validate

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "data/demo"


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class PriceTests(unittest.TestCase):
    def setUp(self):
        self.rows = read_csv(DEMO / "pricing_tiles.csv")
        self.config = json.loads((DEMO / "config.json").read_text())

    def test_manual_new_acquisition(self):
        result, cost = price_plan(self.rows, ["DEMO_O1"], self.config)
        self.assertEqual(cost, D("1703.46"))
        self.assertEqual(result[0]["discount_coef"], "1.000000000")

    def test_empty_order(self):
        self.assertEqual(price_plan(self.rows, [], self.config), ([], D("0.00")))

    def test_calendar_90_day_boundary(self):
        row = {"acquisition_type": "operational", "acquired_date": "2026-06-22"}
        self.assertEqual(freshness_coefficient(row, "2026-09-20"), D(1))
        row.update(acquisition_type="archive", acquired_date="2026-06-21")
        self.assertEqual(freshness_coefficient(row, "2026-09-20"), D(".6"))

    def test_discount_bounds_and_known_values(self):
        self.assertEqual(discount_coefficient("optical", "10", "1"), D(".903450065"))
        self.assertEqual(discount_coefficient("sar", "10", "1"), D(".984948298"))
        self.assertEqual(discount_coefficient("optical", "1e20", "1"), D(".2"))
        self.assertEqual(discount_coefficient("sar", "1e20", "1"), D(".7"))
        self.assertEqual(discount_coefficient("sar", ".001", "1"), D(1))

    def test_reprice_whole_basket(self):
        _, one = price_plan(self.rows, ["DEMO_O1"], self.config)
        _, two = price_plan(self.rows, ["DEMO_O2"], self.config)
        _, both = price_plan(self.rows, ["DEMO_O1", "DEMO_O2"], self.config)
        self.assertEqual(both, D("3500.11"))
        self.assertLess(both, one + two)

    def test_bad_numeric_inputs(self):
        for value in ["NaN", "Infinity", "-1", "0"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                discount_coefficient("optical", value, 1)
        with self.assertRaises(ValueError):
            discount_coefficient("unknown", 1, 1)

    def test_unknown_duplicate_late_and_non_guaranteed(self):
        for ids in [["unknown"], ["DEMO_O1", "DEMO_O1"]]:
            with self.assertRaises(ValueError):
                price_plan(self.rows, ids, self.config)
        for field, value in [("available_at", "2026-09-21T00:00:00Z"), ("guaranteed_purchase", "false")]:
            rows = deepcopy(self.rows)
            rows[0][field] = value
            with self.assertRaises(ValueError):
                price_plan(rows, ["DEMO_O1"], self.config)

    def test_zero_rate_requires_explicit_basis(self):
        self.rows[0]["base_rate_rub_km2"] = "0"
        with self.assertRaises(ValueError):
            price_plan(self.rows, ["DEMO_O1"], self.config)
        self.rows[0]["zero_rate_basis"] = "synthetic zero-rate test, not a legal entitlement"
        self.assertEqual(price_plan(self.rows, ["DEMO_O1"], self.config)[1], 0)

    def test_year_and_group(self):
        for key, value in [("calendar_year", 2025), ("resolution_m", "2")]:
            cfg = deepcopy(self.config)
            cfg["discount_groups"]["OPT_1M"][key] = value
            with self.assertRaises(ValueError):
                price_plan(self.rows, ["DEMO_O1"], cfg)


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data, self.out = self.base / "data", self.base / "submission"
        shutil.copytree(DEMO, self.data)
        self.out.mkdir()
        self.schema = json.loads((ROOT / "schemas/columns.json").read_text())
        self.config = json.loads((self.data / "config.json").read_text())
        self.catalog = read_csv(self.data / "pricing_tiles.csv")
        self.assets = [dict(zip(self.schema["asset_loss.csv"], r)) for r in [
            ["DEMO_A1", "DEMO_AOI3", ".5", "1250000.00", ".2", "7", "1", "ok"],
            ["DEMO_A2", "DEMO_AOI3", ".5", "4000000.00", ".2", "1", "1", "ok"],
            ["DEMO_A3", "DEMO_AOI3", ".5", "750000.00", ".2", "10", "1", "ok"],
            ["DEMO_A4", "DEMO_AOI3", ".5", "800000.00", ".2", "9", "1", "ok"],
            ["DEMO_A5", "DEMO_AOI3", ".5", "2100000.00", ".2", "4", "1", "ok"],
            ["DEMO_A6", "DEMO_AOI3", ".5", "2250000.00", ".2", "3", "1", "ok"],
            ["DEMO_A7", "DEMO_AOI3", ".5", "1800000.00", ".2", "5", "1", "ok"],
            ["DEMO_A8", "DEMO_AOI3", ".5", "1350000.00", ".2", "6", "1", "ok"],
            ["DEMO_A9", "DEMO_AOI3", ".5", "1000000.00", ".2", "8", "1", "ok"],
            ["DEMO_A10", "DEMO_AOI3", ".5", "2400000.00", ".2", "2", "1", "ok"]]]
        self.save_assets()
        plans = {"A": [], "B": ["DEMO_O1", "DEMO_O2", "DEMO_S1"], "C": ["DEMO_O1", "DEMO_O2"]}
        (self.out / "strategy_plans.json").write_text(json.dumps(plans))
        priced, _ = price_plan(self.catalog, plans["C"], self.config)
        write_csv(self.out / "procurement_plan.csv", PRICE_FIELDS, priced)
        comparison = []
        # Independently specified union totals: overlapping A2/A9 must be counted once.
        for key, coverage in [("A", D(0)), ("B", D("17700000")), ("C", D("12400000"))]:
            _, cost = price_plan(self.catalog, plans[key], self.config)
            values = [key, str(cost), "0", str(cost), str(cost <= D("4000")).lower(),
                      str(coverage), str(coverage / D("17700000")), "", "not_estimated", "arithmetic fixture only"]
            comparison.append(dict(zip(self.schema["strategy_comparison.csv"], values)))
        write_csv(self.out / "strategy_comparison.csv", self.schema["strategy_comparison.csv"], comparison)
        write_csv(self.out / "sensitivity.csv", self.schema["sensitivity.csv"], [dict(zip(self.schema["sensitivity.csv"],
                  ["fixture", "A", '{"budget_rub":"0"}', "0", "0", "scenario", "format fixture"]))])
        meta = {"dataset_version": "demo-1.1", "code_commit": "test-fixture", "seed": 2026,
                "environment": {"python": "test"}, "threshold": .5, "uncertainty_method": "test only",
                "aggregation": "points", "comparison_notes": "synthetic", "decision_action": "test",
                "known_expected_loss_rub": "17700000", "unassessed_asset_value_rub": "0"}
        (self.out / "run_metadata.json").write_text(json.dumps(meta))

    def save_assets(self):
        write_csv(self.out / "asset_loss.csv", self.schema["asset_loss.csv"], self.assets)

    def check(self):
        return validate(self.data, self.out, check_rasters=False)

    def test_complete_tables_and_unique_coverage(self):
        self.assertEqual(self.check()["cost_rub"], "3500.11")

    def test_probability_nan_and_infinity_rejected(self):
        for value in ["1.1", "-.1", "NaN", "Infinity", ""]:
            self.assets[0]["p_flood"] = value
            self.save_assets()
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.check()

    def test_loss_sum_and_rank_errors(self):
        self.assets[0]["expected_loss_rub"] = "1250001"
        self.save_assets()
        with self.assertRaisesRegex(ValueError, "base EL"):
            self.check()
        self.assets[0]["expected_loss_rub"] = "1250000"
        self.assets[0]["rank"] = "1"
        self.save_assets()
        with self.assertRaisesRegex(ValueError, "ranks"):
            self.check()

    def test_budget_and_price_tampering(self):
        self.config["budget_rub"] = "1"
        (self.data / "config.json").write_text(json.dumps(self.config))
        with self.assertRaisesRegex(ValueError, "exceeds budget"):
            self.check()
        self.config["budget_rub"] = "4000"
        (self.data / "config.json").write_text(json.dumps(self.config))
        plan = read_csv(self.out / "procurement_plan.csv")
        plan[0]["cost_rub"] = "1.00"
        write_csv(self.out / "procurement_plan.csv", PRICE_FIELDS, plan)
        with self.assertRaisesRegex(ValueError, "price audit mismatch"):
            self.check()

    def test_repeated_region_rejected(self):
        events = read_csv(self.data / "events.csv")
        events[1]["region_id"] = events[0]["region_id"]
        write_csv(self.data / "events.csv", events[0].keys(), events)
        with self.assertRaisesRegex(ValueError, "region"):
            audit(self.data)

    def test_nodata_cannot_be_zero_loss(self):
        self.assets[0].update(status="no_data", coverage_fraction="0")
        self.save_assets()
        with self.assertRaisesRegex(ValueError, "unassessed"):
            self.check()

    def test_raster_alignment_nodata_threshold(self):
        try:
            import rasterio
            import numpy as np
        except ImportError:
            self.skipTest("install requirements.txt for raster tests")
        profile = dict(driver="GTiff", height=4, width=4, count=1, dtype="float32",
                       crs="EPSG:32636", transform=rasterio.transform.from_origin(1000,2000,10,10), nodata=-9999)
        p = np.full((4,4), .7, dtype="float32"); p[0,0] = -9999
        def raster(path, values, prof):
            with rasterio.open(path, "w", **prof) as dst: dst.write(values, 1)
        raster(self.data / "reference.tif", p, profile)
        write_csv(self.data / "aoi.csv", ["aoi_id", "reference_raster", "split"],
                  [{"aoi_id":"DEMO_AOI3", "reference_raster":"reference.tif", "split":"test"}])
        raster(self.out / "flood_probability.tif", p, profile)
        mask_profile = dict(profile, dtype="uint8", nodata=255)
        mask = np.ones((4,4), dtype="uint8"); mask[0,0] = 255
        raster(self.out / "flood_mask.tif", mask, mask_profile)
        write_csv(self.out / "raster_manifest.csv", self.schema["raster_manifest.csv"],
                  [{"aoi_id":"DEMO_AOI3", "probability_path":"flood_probability.tif", "mask_path":"flood_mask.tif"}])
        self.assertEqual(validate(self.data, self.out)["raster_aois"], 1)
        mask[1,1] = 0
        raster(self.out / "flood_mask.tif", mask, mask_profile)
        with self.assertRaisesRegex(ValueError, "threshold"):
            validate(self.data, self.out)
        mask[1,1] = 1; mask[0,0] = 0
        raster(self.out / "flood_mask.tif", mask, mask_profile)
        with self.assertRaisesRegex(ValueError, "validity"):
            validate(self.data, self.out)


if __name__ == "__main__":
    unittest.main()
