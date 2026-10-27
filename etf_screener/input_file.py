"""
Loads the profile YAML files in input_files/. Each profile_*.yaml is one
profile (LT, ST, ...), and the YAML is the ONLY place its settings live:
there are no hidden defaults. A missing or misspelled key stops the run
with a message naming the file and the key.

To add a profile: copy a profile_*.yaml, give it a new `profile:` key and
your values. run_ci.py, main.py (Enter), alerts.py and the column
dictionary pick it up automatically. `enabled: false` keeps a YAML
without running it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml

from scoring import REQUIRED_CONCEPT_KEYS

PROFILE_DIR = Path(__file__).resolve().parent / "input_files"
PROFILE_GLOB = "profile_*.yaml"

# Top-level keys of a profile YAML.
REQUIRED_TOP_LEVEL = ("profile", "data_path", "out_path", "thresholds")
OPTIONAL_TOP_LEVEL = ("enabled",)

# Keys under `thresholds:`. A profile YAML only SCORES funds -- it never
# removes one (rules for every profile are config.PURCHASE_RULES); to make
# something not count, set its weight to 0.0. yahoo_metrics is optional
# (Yahoo download settings, see utils/yahoo_metrics.YahooMetricsConfig).
REQUIRED_THRESHOLDS = ("weights", "concept_weights")
OPTIONAL_THRESHOLDS = ("yahoo_metrics",)


@dataclass
class ProfileInput:
    profile_name: str
    data_path: str
    out_path: str
    thresholds: Dict[str, Any]
    path: str = ""


def _check_keys(where: str, given: Dict[str, Any], required, optional=()) -> None:
    missing = [k for k in required if k not in given]
    unknown = [k for k in given if k not in required and k not in optional]
    problems = []
    if missing:
        problems.append(f"missing {', '.join(missing)}")
    if unknown:
        problems.append(f"unknown {', '.join(unknown)} (typo?)")
    if problems:
        raise ValueError(f"{where}: {'; '.join(problems)}")


def load_profile_input(input_file: str) -> ProfileInput:
    """
    Read and validate one profile YAML. Raises FileNotFoundError,
    yaml.YAMLError or ValueError (with the file and key named) so main.py
    can ask again instead of crashing.
    """
    path = Path(input_file).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must contain a YAML mapping at the top level.")

    _check_keys(path.name, raw, REQUIRED_TOP_LEVEL, OPTIONAL_TOP_LEVEL)
    profile_name = raw["profile"]
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ValueError(f"{path.name}: 'profile' must be a non-empty name, e.g. LT")

    thresholds = raw["thresholds"]
    if not isinstance(thresholds, dict):
        raise ValueError(f"{path.name}: 'thresholds' must be a mapping")
    _check_keys(f"{path.name} thresholds", thresholds, REQUIRED_THRESHOLDS, OPTIONAL_THRESHOLDS)

    # weights: one per concept; concept_weights: every input of every concept
    # (set a weight to 0.0 to leave it out, don't delete the key)
    concepts = tuple(REQUIRED_CONCEPT_KEYS)
    _check_keys(f"{path.name} thresholds.weights", thresholds["weights"] or {}, concepts)
    _check_keys(f"{path.name} thresholds.concept_weights", thresholds["concept_weights"] or {}, concepts)
    for concept, keys in REQUIRED_CONCEPT_KEYS.items():
        _check_keys(f"{path.name} thresholds.concept_weights.{concept}",
                    thresholds["concept_weights"][concept] or {}, keys)

    return ProfileInput(
        profile_name=profile_name.strip(),
        data_path=raw["data_path"],
        out_path=raw["out_path"],
        thresholds=thresholds,
        path=str(path),
    )


def discover_profiles(folder: Path = PROFILE_DIR) -> List[ProfileInput]:
    """Every enabled input_files/profile_*.yaml, in file-name order. The order
    doesn't change which funds are in the report; the first profile's concept
    scores fill the concept-score columns (profile_long_term sorts first)."""
    profiles: List[ProfileInput] = []
    for path in sorted(folder.glob(PROFILE_GLOB)):
        with open(path, "r") as f:
            if (yaml.safe_load(f) or {}).get("enabled", True) is False:
                print(f"  Skipping {path.name} (enabled: false)")
                continue
        profiles.append(load_profile_input(str(path)))
    names = [p.profile_name for p in profiles]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"Two profile YAMLs use the same profile key: {', '.join(duplicates)}")
    if not profiles:
        raise FileNotFoundError(f"No enabled {PROFILE_GLOB} in {folder}")
    return profiles
