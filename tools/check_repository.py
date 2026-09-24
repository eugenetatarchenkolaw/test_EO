"""Check reference material integrity only; never evaluate team submissions."""
import csv
import json
import re
from pathlib import Path
from urllib.parse import unquote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parents[1]


def main():
    errors = []
    files = [p for p in ROOT.rglob("*") if p.is_file()
             and not any(x in p.relative_to(ROOT).parts for x in [".git", "outputs", "__pycache__", ".venv"])
             and not p.is_relative_to(ROOT / "data/local")]
    for path in files:
        if path.suffix.lower() in {".docx", ".pdf", ".pt", ".pth", ".tif", ".tiff", ".zip"}:
            errors.append(f"unexpected public artifact: {path.relative_to(ROOT)}")
        if "reference_solution" in path.name.lower() or "экспертный" in path.name.lower():
            errors.append(f"private material filename: {path.name}")
        if path.suffix == ".md":
            source = path.read_text()
            source = re.sub(r"```[\s\S]*?```", "", source)
            targets = re.findall(r"\]\(([^\s)]+)\)", source)
            targets += re.findall(r'<img[^>]+src="([^"]+)"', source)
            for target in targets:
                if target.startswith(("http:", "https:", "mailto:", "#")):
                    continue
                local = unquote(target.split("#", 1)[0])
                if local and not (path.parent / local).exists():
                    errors.append(f"broken local link: {path.relative_to(ROOT)} -> {local}")
        if path.suffix == ".svg":
            ET.parse(path)
            if "<script" in path.read_text().lower():
                errors.append(f"unexpected script in SVG: {path.name}")
        if path.suffix == ".ipynb":
            nb = json.loads(path.read_text())
            for cell in nb["cells"]:
                if cell["cell_type"] == "code":
                    if cell.get("outputs") or cell.get("execution_count") is not None:
                        errors.append(f"public notebook should be clean: {path.name}")
                    compile("".join(cell["source"]), path.name, "exec")
        if path.suffix == ".py":
            compile(path.read_text(), str(path), "exec")
        if path.suffix in {".json", ".geojson"}:
            def reject_constant(value):
                raise ValueError(f"Non-finite JSON value in {path}: {value}")
            json.loads(path.read_text(), parse_constant=reject_constant)
    columns = json.loads((ROOT / "schemas/columns.json").read_text())
    for name, fields in columns.items():
        with (ROOT / "examples/empty_submission" / name).open() as stream:
            rows = list(csv.reader(stream))
            actual = rows[0]
        if actual != fields:
            errors.append(f"header mismatch: {name}")
        if len(rows) != 1:
            errors.append(f"empty form must not contain answers: {name}")
    for name in ["assets.geojson", "candidate_orders.geojson"]:
        form = json.loads((ROOT / "examples/empty_submission" / name).read_text())
        if form != {"type": "FeatureCollection", "features": []}:
            errors.append(f"empty geometry form contains data: {name}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"PASS: {len(files)} reference files; local links, notebook source, JSON, SVG and empty forms")


if __name__ == "__main__":
    main()
