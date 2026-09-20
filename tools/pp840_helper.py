"""PP 840 (27 August 2025): auditable arithmetic, with explicit case conventions.

This module does not establish a Roscosmos base rate or determine legal eligibility
for free data. See docs/PRICING_PP840.md before using it outside the exercise.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path

D = Decimal
EDITION = "2025-08-27"
O = {"L0": D("1"), "L1": D("1"), "L2": D("1.2")}
P = {"internal": D("1"), "limited": D("1.2"), "unrestricted": D("1.5")}
PRICE_FIELDS = ["candidate_id", "area_km2", "base_rate_rub_km2", "base_rate_status",
                "processing_coef", "usage_coef", "freshness_coef", "discount_coef",
                "discount_group_id", "group_area_km2", "unit_price_rub_km2",
                "cost_rub", "formula", "legal_edition"]


def number(value, name="number", *, minimum=None, positive=False):
    try:
        result = D(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name}: expected a decimal number") from exc
    if not result.is_finite():
        raise ValueError(f"{name}: must be finite")
    if positive and result <= 0:
        raise ValueError(f"{name}: must be positive")
    if minimum is not None and result < D(str(minimum)):
        raise ValueError(f"{name}: below {minimum}")
    return result


def rounded(value, places):
    return number(value).quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP)


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include UTC offset")
    return result.astimezone(timezone.utc)


def discount_coefficient(sensor_type, area_km2, resolution_m):
    """Use the numerical units specified in PP 840: km² and metres."""
    area = number(area_km2, "group area", positive=True)
    resolution = number(resolution_m, "resolution", positive=True)
    if sensor_type not in {"optical", "sar"}:
        raise ValueError("sensor_type must be optical or sar")
    slope, intercept, floor = ((D("-.058"), D("1.037"), D(".2"))
                               if sensor_type == "optical" else
                               (D("-.020"), D("1.031"), D(".7")))
    with localcontext() as ctx:
        ctx.prec = 40
        result = slope * (area / resolution**2).ln() + intercept
    return rounded(min(D(1), max(floor, result)), 9)


def freshness_coefficient(row, pricing_date):
    kind = row["acquisition_type"]
    if kind == "new":
        if str(row.get("guaranteed_purchase", "")).lower() != "true":
            raise ValueError("new acquisition requires guaranteed_purchase=true")
        return D("1.8")
    if kind not in {"operational", "archive"}:
        raise ValueError("unknown acquisition_type")
    age = (date.fromisoformat(pricing_date) - date.fromisoformat(row["acquired_date"])).days
    if age < 0:
        raise ValueError("existing acquisition cannot be dated in the future")
    if (kind == "operational") != (age <= 90):
        raise ValueError("acquisition_type does not match the 90 calendar day boundary")
    return D(1) if age <= 90 else D(".6")


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{path}: absent or duplicate headers")
        rows = list(reader)
        if any(None in row or any(v is None for v in row.values()) for row in rows):
            raise ValueError(f"{path}: malformed CSV row")
        return rows


def unique_index(rows, key):
    index = {}
    for row in rows:
        value = row[key]
        if not value or value in index:
            raise ValueError(f"empty or duplicate {key}: {value!r}")
        index[value] = row
    return index


def price_plan(catalog, selected_ids, config):
    """Reprice the whole selected basket. Does not choose any candidate.

    Case convention: homogeneous discount groups, all selected area plus declared
    prior calendar-year area; prior invoices are not recalculated. No exemptions
    are inferred. The base case is a private commercial customer.
    """
    if config["legal_edition"] != EDITION:
        raise ValueError("unsupported legal edition; reverify the helper")
    if config.get("customer_mode") != "private_commercial":
        raise ValueError("this case profile supports private_commercial only")
    budget = number(config["budget_rub"], "budget", minimum=0)
    del budget  # This function prices counterfactual baskets too; validator checks C.
    catalog = unique_index(catalog, "candidate_id")
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("duplicate selected candidate")
    if set(selected_ids) - catalog.keys():
        raise ValueError("selected candidate absent from catalog")
    rows = [catalog[key] for key in sorted(selected_ids)]
    groups = {}
    for row in rows:
        if timestamp(row["available_at"]) > timestamp(config["decision_deadline"]):
            raise ValueError(f"{row['candidate_id']}: unavailable by decision deadline")
        if row["data_role"] not in {"event_observation", "context"}:
            raise ValueError("unknown data_role")
        if row["processing_level"] not in O or row["usage_mode"] not in P:
            raise ValueError("unknown processing_level or usage_mode")
        if row["base_rate_status"] not in {"scenario", "official"} or not row["base_rate_source"]:
            raise ValueError("base rate needs status and source")
        area = number(row["area_km2"], "area_km2", positive=True)
        if area != rounded(area, 3):
            raise ValueError("case area must already be stated to 0.001 km²")
        rate = number(row["base_rate_rub_km2"], "base rate", minimum=0)
        if rate == 0 and not row.get("zero_rate_basis"):
            raise ValueError("zero rate requires an explicit basis")
        group_id = row["discount_group_id"]
        prior = config["discount_groups"][group_id]
        if prior["calendar_year"] != date.fromisoformat(config["pricing_date"]).year:
            raise ValueError("prior area belongs to a different calendar year")
        key = (row["sensor_type"], number(row["resolution_m"], positive=True))
        if key != (prior["sensor_type"], number(prior["resolution_m"], positive=True)):
            raise ValueError("heterogeneous discount group")
        if group_id not in groups:
            groups[group_id] = number(prior["prior_area_km2"], minimum=0)
        groups[group_id] += area
    output = []
    for row in rows:
        area = number(row["area_km2"])
        rate = number(row["base_rate_rub_km2"])
        processing, usage = O[row["processing_level"]], P[row["usage_mode"]]
        freshness = freshness_coefficient(row, config["pricing_date"])
        group_area = groups[row["discount_group_id"]]
        discount = discount_coefficient(row["sensor_type"], group_area, row["resolution_m"])
        unit = rounded(rate * processing * usage * freshness * discount, 2)
        cost = rounded(area * unit, 2)
        output.append(dict(zip(PRICE_FIELDS, map(str, [
            row["candidate_id"], area, rate, row["base_rate_status"], processing, usage,
            freshness, discount, row["discount_group_id"], group_area, unit, cost,
            "B*K*O*P*T*R; round(unit,2); round(K*unit,2)", EDITION]))))
    return output, sum((number(row["cost_rub"]) for row in output), D("0.00"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--ids", nargs="*", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = json.loads((args.data / "config.json").read_text())
    rows, total = price_plan(read_csv(args.data / "pricing_tiles.csv"), args.ids, config)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=PRICE_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({"selected": args.ids, "cost_rub": str(total),
                      "within_budget": total <= number(config["budget_rub"]),
                      "rate_status": sorted({r["base_rate_status"] for r in rows})},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
