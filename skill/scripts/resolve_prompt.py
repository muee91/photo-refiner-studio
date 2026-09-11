#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

import yaml


PRESETS_PATH = Path(__file__).resolve().parent.parent / "references" / "presets.yaml"
CUSTOM_DEFAULT_STRENGTH = 50


def resolve_prompt(
    preset: str,
    custom_prompt: str = "",
    custom_avoid: str = "",
    presets_path: Path = PRESETS_PATH,
) -> dict:
    data = yaml.safe_load(presets_path.read_text(encoding="utf-8"))
    version = data.get("version")
    presets = data.get("presets", {})

    if preset == "custom":
        prompt = custom_prompt.strip()
        if not prompt:
            raise ValueError("A non-empty custom prompt is required for preset 'custom'")
        resolved = {
            "preset": "custom",
            "label": "Custom",
            "summary": "User-provided photo refinement prompt",
            "prompt": prompt,
            "avoid": custom_avoid.strip(),
            "default_strength": CUSTOM_DEFAULT_STRENGTH,
            "preset_version": version,
        }
    else:
        if preset not in presets:
            available = ", ".join(sorted(presets))
            raise ValueError(f"Unknown preset '{preset}'. Available presets: {available}, custom")
        item = presets[preset]
        strength = item.get("default_strength", CUSTOM_DEFAULT_STRENGTH)
        if not isinstance(strength, (int, float)) or not 0 <= strength <= 100:
            raise ValueError(f"Preset '{preset}' has invalid default_strength: {strength!r}")
        resolved = {
            "preset": preset,
            "label": item["label"],
            "summary": item.get("summary_zh") or item.get("summary") or item["label"],
            "prompt": item["prompt"].strip(),
            "avoid": item.get("avoid", "").strip(),
            "default_strength": strength,
            "preset_version": version,
        }

    digest_source = json.dumps(resolved, ensure_ascii=False, sort_keys=True).encode("utf-8")
    resolved["prompt_hash"] = hashlib.sha256(digest_source).hexdigest()
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and expand a photo-refiner preset.")
    parser.add_argument("--preset", required=True)
    parser.add_argument("--custom-prompt", default="")
    parser.add_argument("--custom-avoid", default="")
    args = parser.parse_args()
    try:
        resolved = resolve_prompt(args.preset, args.custom_prompt, args.custom_avoid)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(resolved, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
