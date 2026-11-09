"""Facility directory, grouped by region (county). Data lives in data/facilities.json."""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class Directory:
    def __init__(self, data: dict):
        self.regions = data["regions"]
        if not 1 <= len(self.regions) <= 9:
            raise ValueError("between 1 and 9 regions are supported (one keypad digit each)")
        self._facilities = {}
        for region in self.regions:
            if not region.get("facilities"):
                raise ValueError(f"region {region['key']!r} has no facilities")
            for facility in region["facilities"]:
                self._facilities[facility["id"]] = facility

    @classmethod
    def load(cls, path=None) -> "Directory":
        path = Path(path) if path else DATA_DIR / "facilities.json"
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def region_keys(self) -> list:
        return [r["key"] for r in self.regions]

    def facility_for(self, region_key: str) -> dict:
        """v1: the first facility listed for the region. Later: nearest by sub-county."""
        for region in self.regions:
            if region["key"] == region_key:
                return region["facilities"][0]
        raise KeyError(region_key)

    def facility(self, facility_id: str) -> dict:
        return self._facilities[facility_id]
