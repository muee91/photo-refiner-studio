#!/usr/bin/env python3
"""Compile Studio-facing Starryear catalogs from the creative skill + preview sources."""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "skills" / "photo-refiner-creative" / "references" / "starryear" / "catalog.json"
PREVIEW_ROOT = REPO / "catalog" / "starryear"
TARGET = REPO / "config" / "creative-recipes.json"
LARGE_TARGET = REPO / "config" / "creative-previews-large.json"
PREVIEW_MAX_SIDE = 320
PREVIEW_JPEG_QUALITY = 70


def encode_preview(path: Path, *, max_side: int | None, quality: int) -> str:
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit("Pillow is required to compile creative previews") from exc
    with Image.open(path) as image:
        converted = image.convert("RGB")
        if max_side is not None:
            converted.thumbnail((max_side, max_side))
        buffer = BytesIO()
        converted.save(buffer, "JPEG", quality=quality, optimize=True)
    return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def main() -> None:
    catalog = json.loads(SOURCE.read_text(encoding="utf-8"))
    recipes = catalog.get("recipes")
    if not isinstance(recipes, list) or not recipes:
        raise SystemExit("Starryear catalog must contain at least one recipe")

    seen: set[str] = set()
    public_recipes: list[dict] = []
    large: list[dict] = []
    for recipe in recipes:
        recipe_id = recipe.get("id")
        if not isinstance(recipe_id, str) or not recipe_id or recipe_id in seen:
            raise SystemExit(f"Invalid or duplicate recipe id: {recipe_id!r}")
        seen.add(recipe_id)

        source_count = recipe.get("sourceCount") or {}
        minimum, maximum = source_count.get("min"), source_count.get("max")
        if not isinstance(minimum, int) or not isinstance(maximum, int) or minimum < 1 or maximum < minimum:
            raise SystemExit(f"{recipe_id}: invalid sourceCount range")

        recipe_dir = SOURCE.parent / str(recipe.get("recipePath", ""))
        if not (recipe_dir / "SKILL.md").is_file():
            raise SystemExit(f"{recipe_id}: missing recipe SKILL.md at {recipe_dir}")

        preview = dict(recipe.get("preview") or {})
        if preview.get("status") == "available":
            preview_path = PREVIEW_ROOT / str(preview.get("path", ""))
            if not preview_path.is_file():
                raise SystemExit(f"{recipe_id}: missing developer preview source at {preview_path}")
            preview["dataUri"] = encode_preview(preview_path, max_side=PREVIEW_MAX_SIDE, quality=PREVIEW_JPEG_QUALITY)
            large.append({"id": recipe_id, "dataUri": encode_preview(preview_path, max_side=None, quality=74)})
        elif preview.get("status") != "missing":
            raise SystemExit(f"{recipe_id}: preview status must be available or missing")

        public_recipe = {key: value for key, value in recipe.items() if key != "recipePath"}
        public_recipe["preview"] = preview
        public_recipes.append(public_recipe)

    payload = {
        "version": catalog.get("version", 1),
        "collection": catalog.get("collection", {}),
        "recipes": public_recipes,
    }
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LARGE_TARGET.write_text(json.dumps({"version": payload["version"], "recipes": large}, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Synced {len(public_recipes)} creative recipes to {TARGET}")
    print(f"Synced {len(large)} large previews to {LARGE_TARGET}")


if __name__ == "__main__":
    main()
