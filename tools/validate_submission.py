"""Validate declared base-case outputs. Does not award points or certify a model."""
import argparse
import csv
import json
from decimal import Decimal as D
from pathlib import Path
from .pp840_helper import (PRICE_FIELDS, number, price_plan, read_csv,
                           rounded, unique_index)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def table(path, fields):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        headers = next(csv.reader(stream), [])
    require(set(fields) <= set(headers), f"{path}: missing required fields")
    return read_csv(path)


def covered_units(ids, catalog, relations):
    """Set union only; relations must have been independently validated."""
    selected = set(ids)
    return {row["unit_id"] for row in relations
            if row["candidate_id"] in selected
            and catalog[row["candidate_id"]]["data_role"] == "event_observation"}


def validate_assets(rows, exposure, loss_model="control_pvq"):
    actual = unique_index(rows, "asset_id")
    require(actual.keys() == exposure.keys(), "asset set differs from fixed portfolio")
    known = {}
    ranking = []
    for asset_id, row in actual.items():
        require(row["aoi_id"] == exposure[asset_id]["aoi_id"], "asset AOI mismatch")
        coverage = number(row["coverage_fraction"], minimum=0)
        require(coverage <= 1, "coverage_fraction > 1")
        require(row["status"] in {"ok", "partial", "no_data"}, "unknown asset status")
        if row["status"] != "ok":
            require(all(row[k] == "" for k in ["p_flood", "expected_loss_rub", "rank"]),
                    "unassessed assets must not carry base p, EL or rank")
            require(coverage == 0 if row["status"] == "no_data" else 0 < coverage < 1,
                    "status and coverage disagree")
            if row["uncertainty"]:
                number(row["uncertainty"], minimum=0)
            continue
        require(coverage == 1, "ok requires full declared support coverage")
        p = number(row["p_flood"], minimum=0)
        require(p <= 1, "probability outside [0,1]")
        number(row["uncertainty"], minimum=0)
        asset = exposure[asset_id]
        expected = rounded(p * number(asset["asset_value_rub"], minimum=0)
                           * number(asset["vulnerability_coef"], minimum=0), 2)
        loss = number(row["expected_loss_rub"], minimum=0)
        if loss_model == "control_pvq":
            require(abs(loss - expected) <= D(".02"), "base EL differs from p*V*q")
        rank = number(row["rank"], positive=True)
        require(rank == rank.to_integral_value(), "rank must be an integer")
        ranking.append((int(rank), loss))
        known[asset_id] = loss
    require(sorted(r for r, _ in ranking) == list(range(1, len(ranking) + 1)),
            "ranks must cover 1..number of assessed assets")
    ordered = [loss for _, loss in sorted(ranking)]
    require(ordered == sorted(ordered, reverse=True), "rank must descend by base EL")
    return known


def validate_rasters(data, submission, metadata):
    import numpy as np
    import rasterio
    expected = unique_index(read_csv(data / "aoi.csv"), "aoi_id")
    expected = {k: v for k, v in expected.items() if v["split"] == "test"}
    output = unique_index(table(submission / "raster_manifest.csv",
                                ["aoi_id", "probability_path", "mask_path"]), "aoi_id")
    require(output.keys() == expected.keys(), "raster set differs from test AOIs")
    threshold = float(number(metadata["threshold"], minimum=0))
    require(threshold <= 1, "threshold > 1")
    total_valid = 0
    for aoi_id, row in output.items():
        paths = [(submission / row[k]).resolve() for k in ["probability_path", "mask_path"]]
        require(all(p.is_relative_to(submission.resolve()) for p in paths), "output path escapes submission")
        ref_path = data / expected[aoi_id]["reference_raster"]
        with rasterio.open(ref_path) as ref, rasterio.open(paths[0]) as prob, rasterio.open(paths[1]) as mask:
            require(prob.count == mask.count == 1, "outputs must be single-band")
            require(prob.crs is not None and prob.crs == mask.crs == ref.crs, "CRS mismatch")
            require(prob.transform == mask.transform == ref.transform, "transform mismatch")
            require(prob.shape == mask.shape == ref.shape, "raster shape mismatch")
            require(prob.dtypes[0] == "float32" and mask.dtypes[0] == "uint8", "wrong raster dtype")
            require(prob.nodata == -9999 and mask.nodata == 255, "nodata must be -9999 / 255")
            for _, window in prob.block_windows(1):
                p, m = prob.read(1, window=window), mask.read(1, window=window)
                valid = prob.read_masks(1, window=window) > 0
                require(np.array_equal(valid, mask.read_masks(1, window=window) > 0), "output validity differs")
                require(np.array_equal(valid, ref.read_masks(1, window=window) > 0), "coverage differs from reference grid mask")
                require(np.isfinite(p).all(), "non-finite raster values")
                require(((p[valid] >= 0) & (p[valid] <= 1)).all(), "raster probability outside [0,1]")
                require(np.array_equal(m[valid], (p[valid] >= threshold).astype("uint8")), "binary mask and threshold disagree")
                require((p[~valid] == -9999).all() and (m[~valid] == 255).all(), "nodata values inconsistent")
                total_valid += int(valid.sum())
    require(total_valid > 0, "no valid test pixels")
    return len(output)


def validate(data, submission, *, check_rasters=True):
    data, submission = Path(data), Path(submission)
    from .audit_data import audit
    audit(data)
    config = json.loads((data / "config.json").read_text())
    metadata = json.loads((submission / "run_metadata.json").read_text())
    for key in ["dataset_version", "code_commit", "seed", "environment", "threshold",
                "uncertainty_method", "aggregation", "comparison_notes", "decision_action"]:
        require(key in metadata and metadata[key] != "", f"metadata missing {key}")
    version = json.loads((data / "dataset_manifest.json").read_text())["version"]
    require(metadata["dataset_version"] == version, "dataset version mismatch")
    schema = json.loads((Path(__file__).parents[1] / "schemas/columns.json").read_text())
    exposure = unique_index(read_csv(data / "exposure.csv"), "asset_id")
    loss_model = metadata.get("loss_model", "control_pvq")
    require(loss_model in {"control_pvq", "declared_custom"}, "unknown loss model profile")
    if loss_model == "declared_custom":
        require(bool(metadata.get("loss_model_reference")), "custom loss model requires a method/code reference")
    losses = validate_assets(table(submission / "asset_loss.csv", schema["asset_loss.csv"]), exposure, loss_model)
    known_total = sum(losses.values(), D(0))
    unassessed = sum((number(row["asset_value_rub"]) for key, row in exposure.items()
                      if key not in losses), D(0))
    require(abs(number(metadata["known_expected_loss_rub"], minimum=0) - known_total) <= D(".02"),
            "known loss total mismatch")
    require(abs(number(metadata["unassessed_asset_value_rub"], minimum=0) - unassessed) <= D(".02"),
            "unassessed exposure mismatch")
    catalog_rows = read_csv(data / "pricing_tiles.csv")
    catalog = unique_index(catalog_rows, "candidate_id")
    plan = table(submission / "procurement_plan.csv", PRICE_FIELDS)
    actual = unique_index(plan, "candidate_id")
    calculated, total = price_plan(catalog_rows, list(actual), config)
    for row in calculated:
        for key in PRICE_FIELDS:
            require(actual[row["candidate_id"]][key] == row[key], f"price audit mismatch: {row['candidate_id']} / {key}")
    require(total <= number(config["budget_rub"]), "procurement plan exceeds budget")
    plans = json.loads((submission / "strategy_plans.json").read_text())
    require(set(plans) == {"A", "B", "C"}, "strategy plans must contain A/B/C")
    require(plans["A"] == [] and set(plans["C"]) == set(actual), "A or C plan inconsistent")
    comparison = unique_index(table(submission / "strategy_comparison.csv", schema["strategy_comparison.csv"]), "strategy")
    require(comparison.keys() == plans.keys(), "comparison must contain A/B/C")
    relations = read_csv(data / "candidate_units.csv")
    denominator = sum(losses.values(), D(0))
    for strategy, ids in plans.items():
        _, cost = price_plan(catalog_rows, ids, config)
        row = comparison[strategy]
        require(number(row["data_cost_rub"], minimum=0) == cost, "strategy data cost mismatch")
        other = number(row["other_cost_rub"], minimum=0)
        require(number(row["decision_cost_rub"], minimum=0) == cost + other, "strategy total mismatch")
        require(row["budget_feasible"] == str(cost <= number(config["budget_rub"])).lower(), "feasibility mismatch")
        covered = sum((losses.get(uid, D(0)) for uid in covered_units(ids, catalog, relations)), D(0))
        require(abs(number(row["covered_expected_loss_rub"], minimum=0) - covered) <= D(".02"), "coverage must use unique observed units")
        if denominator:
            require(abs(number(row["coverage_share"], minimum=0) - covered / denominator) <= D(".000001"), "coverage share mismatch")
        else:
            require(row["coverage_share"] == "", "zero EL denominator requires blank share")
        require(row["uncertainty_status"] in {"measured", "scenario", "not_estimated"}, "unknown uncertainty status")
        if row["uncertainty_status"] == "not_estimated":
            require(row["residual_uncertainty"] == "", "unestimated uncertainty must be blank")
        else:
            number(row["residual_uncertainty"], minimum=0)
        require(bool(row["uncertainty_basis"]), "uncertainty needs a basis or limitation")
    sensitivity = table(submission / "sensitivity.csv", schema["sensitivity.csv"])
    require(bool(sensitivity), "sensitivity table is empty")
    unique_index(sensitivity, "scenario_id")
    for row in sensitivity:
        require(row["strategy"] in plans and bool(row["changed_inputs_json"]), "invalid sensitivity row")
        require(isinstance(json.loads(row["changed_inputs_json"]), dict), "changed inputs must be an object")
        number(row["decision_cost_rub"], minimum=0)
        number(row["covered_expected_loss_rub"], minimum=0)
        require(row["result_status"] in {"measured", "scenario"}, "invalid sensitivity status")
    raster_count = validate_rasters(data, submission, metadata) if check_rasters else None
    return {"checks": "passed", "assets": len(exposure), "assessed_assets": len(losses),
            "selected_candidates": len(actual), "cost_rub": str(total), "raster_aois": raster_count,
            "loss_formula_checked": loss_model == "control_pvq",
            "scope": "format and declared arithmetic; custom loss formula and scientific quality require review"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--tables-only", action="store_true", help="partial check; not full acceptance")
    args = parser.parse_args()
    try:
        result = validate(args.data, args.submission, check_rasters=not args.tables_only)
    except (ValueError, KeyError, OSError, ImportError) as exc:
        parser.exit(1, f"Validation failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
