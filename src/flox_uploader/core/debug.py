"""Collecteur de debug consolidé (1 fichier JSON au lieu de N writes).

Pensé pour réduire les I/O sur NAS lors du batch.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Debug:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.data: dict = {}

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def update(self, mapping: dict) -> None:
        self.data.update(mapping)

    def write_extra(self, filename: str, content: str) -> None:
        """Pour les gros volumes qui ne méritent pas d'être dans le JSON
        consolidé (ex : raw response OpenAI).
        """
        try:
            (self.output_dir / filename).write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"[WARN] Debug extra write failed ({filename}): {e}")

    def save(self) -> None:
        try:
            (self.output_dir / "debug.json").write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[WARN] Debug save failed: {e}")
