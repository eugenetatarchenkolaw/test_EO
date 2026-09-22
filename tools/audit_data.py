"""Check public identifiers and declared splits; not a geometric leakage audit."""
import argparse
import json
from pathlib import Path
from .pp840_helper import number, read_csv, unique_index, price_plan


def audit(data):
    data = Path(data)
    manifest = json.loads((data / "dataset_manifest.json").read_text())
    config = json.loads((data / "config.json").read_text())
    events = unique_index(read_csv(data / "events.csv"), "event_id")
    region_splits = {}
    for row in events.values():
        if row["split"] not in {"train", "validation", "test"}:
            raise ValueError("invalid split")
        region_splits.setdefault(row["region_id"], set()).add(row["split"])
    if any(len(splits) > 1 for splits in region_splits.values()):
        raise ValueError("region appears in multiple splits")
    if {r["split"] for r in events.values()} != {"train", "validation", "test"}:
        raise ValueError("all three splits are required")
    chips = unique_index(read_csv(data / "chips.csv"), "chip_id")
    scenes = {}
    for row in chips.values():
        event = events[row["event_id"]]
        scenes.setdefault(row["scene_id"], set()).add(event["split"])
        if event["split"] == "test" and row.get("label_path"):
            raise ValueError("test label path must be empty in public release")
        if manifest["status"] == "competition":
            for field in ["s1_path", "valid_mask_path"]:
                if not row.get(field) or not (data / row[field]).is_file():
                    raise ValueError(f"missing {field} for {row['chip_id']}")
            if event["split"] != "test" and not (data / row["label_path"]).is_file():
                raise ValueError("missing public label")
    if any(len(s) > 1 for s in scenes.values()):
        raise ValueError("parent scene appears in multiple splits")
    assets = unique_index(read_csv(data / "exposure.csv"), "asset_id")
    for row in assets.values():
        if row.get("chip_id"):
            if row["chip_id"] not in chips or chips[row["chip_id"]]["aoi_id"] != row["aoi_id"]:
                raise ValueError("asset chip/AOI mismatch")
        number(row["asset_value_rub"], minimum=0)
        q = number(row["vulnerability_coef"], minimum=0)
        if q > 1:
            raise ValueError("vulnerability outside [0,1]")
    catalog = read_csv(data / "pricing_tiles.csv")
    candidates = unique_index(catalog, "candidate_id")
    # Candidate catalogs may contain late products; only available ones can be ordered.
    from .pp840_helper import timestamp
    for row in catalog:
        if timestamp(row["available_at"]) <= timestamp(config["decision_deadline"]):
            price_plan(catalog, [row["candidate_id"]], config)
    pairs = set()
    for row in read_csv(data / "candidate_units.csv"):
        pair = (row["candidate_id"], row["unit_id"])
        if pair in pairs or pair[0] not in candidates or pair[1] not in assets:
            raise ValueError("invalid or duplicate candidate-unit relation")
        pairs.add(pair)
    return {"status": manifest["status"], "events": len(events), "chips": len(chips),
            "assets": len(assets), "candidates": len(candidates),
            "scope": "identifier, split and arithmetic checks; geometry is not certified"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--geometry", action="store_true", help="also check contour areas and point coverage")
    args = parser.parse_args()
    report = audit(args.data)
    if args.geometry:
        from .geometry import audit_geometry
        report["geometry"] = audit_geometry(args.data)
        report["scope"] = "identifiers, arithmetic and order geometry; no spatial split certification"
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
