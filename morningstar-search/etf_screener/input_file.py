"""
Loads a single profile's run configuration (paths, profile name, top_n,
and eligibility thresholds) from a YAML input file, e.g. input_profile_a.yaml.

Keeping this separate from main.py mirrors the rest of the project: each
concern (loading, merging, scoring, export, and now input-file parsing)
lives in its own module, so main.py stays a thin orchestrator.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml

from config import (
    DEFAULT_STRUCT_PATH, DEFAULT_PERF_PATH, DEFAULT_OUT_PATH,
    DEFAULT_PROFILE_NAME, DEFAULT_TOP_N_PER_CATEGORY,
)


@dataclass
class ProfileInput:
    profile_name: str
    struct_path: str
    perf_path: str
    out_path: str
    top_n_per_category: int
    thresholds: Dict[str, Any]


def load_profile_input(input_file: str) -> ProfileInput:
    """
    Read and validate a profile input YAML file.

    Raises FileNotFoundError if the path doesn't exist, yaml.YAMLError if
    the file isn't valid YAML, and ValueError if required fields are the
    wrong type -- all of which the caller (main.py) is expected to catch
    and retry on, rather than crashing the whole pipeline.
    """
    path = Path(input_file).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Input path is not a file: {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Input file {path} must contain a YAML mapping at the top level.")

    profile_name = raw.get("profile", DEFAULT_PROFILE_NAME)
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ValueError(f"'profile' must be a non-empty string in {path}")

    thresholds = raw.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise ValueError(f"'thresholds' must be a mapping in {path}")

    return ProfileInput(
        profile_name=profile_name.strip(),
        struct_path=raw.get("struct_path") or DEFAULT_STRUCT_PATH,
        perf_path=raw.get("perf_path") or DEFAULT_PERF_PATH,
        out_path=raw.get("out_path") or DEFAULT_OUT_PATH,
        top_n_per_category=int(raw.get("top_n_per_category", DEFAULT_TOP_N_PER_CATEGORY)),
        thresholds=thresholds,
    )
