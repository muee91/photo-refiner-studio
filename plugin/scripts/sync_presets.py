#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import yaml


DEFAULT_SKILL_PRESETS = Path.home() / ".codex" / "skills" / "photo-refiner" / "references" / "presets.yaml"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "config" / "presets.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Photo Refiner Studio preset catalog from the core skill.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SKILL_PRESETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    generated = {"version": data["version"], "presets": {}}
    for preset_id, item in data["presets"].items():
        generated["presets"][preset_id] = {
            "label": item["label"],
            "summary": item["summary_zh"],
            "prompt": item["prompt"].strip(),
            "avoid": item.get("avoid", "").strip(),
            "promptZh": item.get("prompt_zh", "").strip(),
            "avoidZh": item.get("avoid_zh", "").strip(),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(generated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Synced {len(generated['presets'])} presets from {source} to {output}")


if __name__ == "__main__":
    main()
