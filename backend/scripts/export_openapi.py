#!/usr/bin/env python
"""Regenerates `openapi/api.json` and `.yaml` from the live FastAPI
app definition. Run this after changing any route/schema so the checked-in
spec stays in sync.

Usage:
    python -m scripts.export_openapi
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from app.main import app  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "openapi"


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    schema = app.openapi()

    json_path = OUTPUT_DIR / "api.json"
    yaml_path = OUTPUT_DIR / "api.yaml"

    json_path.write_text(json.dumps(schema, indent=2))
    yaml_path.write_text(yaml.dump(schema, sort_keys=False, allow_unicode=True))

    print(f"Wrote {json_path} ({len(schema['paths'])} paths)")
    print(f"Wrote {yaml_path}")


if __name__ == "__main__":
    main()
