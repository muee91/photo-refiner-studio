#!/usr/bin/env python3
"""Build the plugin-facing Starryear recipe catalog from the Skill source."""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "skill" / "references" / "starryear" / "catalog.json"
TARGET = REPO_ROOT / "plugin" / "config" / "creative-recipes.json"
# Selector previews are embedded into every open_photo_refiner_flow_settings tool
# result and every resources/read response. Full-size images make one response
# several megabytes, which some Codex brokers truncate or drop, leaving the
# settings panel unable to mount. The Skill catalog keeps the originals.
PREVIEW_MAX_SIDE = 320
PREVIEW_JPEG_QUALITY = 70


def preview_data_uri(path: Path) -> str:
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required to downscale selector previews: python3 -m pip install pillow"
        ) from exc
    with Image.open(path) as image:
        converted = image.convert("RGB")
        converted.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
        buffer = BytesIO()
        converted.save(buffer, "JPEG", quality=PREVIEW_JPEG_QUALITY, optimize=True)
    return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def main() -> None:
    catalog = json.loads(SOURCE.read_text(encoding="utf-8"))
    recipes = catalog.get("recipes")
    if not isinstance(recipes, list) or not recipes:
        raise SystemExit("Starryear catalog must contain at least one recipe")

    seen: set[str] = set()
    output_recipes: list[dict] = []
    for recipe in recipes:
        recipe_id = recipe.get("id")
        if not isinstance(recipe_id, str) or not recipe_id or recipe_id in seen:
            raise SystemExit(f"Invalid or duplicate recipe id: {recipe_id!r}")
        seen.add(recipe_id)

        source_count = recipe.get("sourceCount")
        if not isinstance(source_count, dict):
            raise SystemExit(f"{recipe_id}: sourceCount is required")
        minimum = source_count.get("min")
        maximum = source_count.get("max")
        if not isinstance(minimum, int) or not isinstance(maximum, int) or minimum < 1 or maximum < minimum:
            raise SystemExit(f"{recipe_id}: invalid sourceCount range")

        recipe_dir = SOURCE.parent / str(recipe.get("recipePath", ""))
        if not (recipe_dir / "SKILL.md").is_file():
            raise SystemExit(f"{recipe_id}: missing recipe SKILL.md at {recipe_dir}")

        preview = dict(recipe.get("preview") or {})
        if preview.get("status") == "available":
            preview_path = SOURCE.parent / str(preview.get("path", ""))
            if not preview_path.is_file():
                raise SystemExit(f"{recipe_id}: missing preview image at {preview_path}")
            preview["dataUri"] = preview_data_uri(preview_path)
        elif preview.get("status") != "missing":
            raise SystemExit(f"{recipe_id}: preview status must be available or missing")

        public_recipe = {
            key: value
            for key, value in recipe.items()
            if key not in {"recipePath"}
        }
        public_recipe["preview"] = preview
        output_recipes.append(public_recipe)

    payload = {
        "version": catalog.get("version", 1),
        "collection": catalog.get("collection", {}),
        "recipes": output_recipes,
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Synced {len(output_recipes)} creative recipes to {TARGET}")


if __name__ == "__main__":
    main()
