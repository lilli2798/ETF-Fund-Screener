"""
Loads a single profile's run configuration (paths, profile name, top_n,
and eligibility thresholds) from a YAML input file, e.g. input_profile_a.yaml.

Keeping this separate from main.py mirrors the rest of the project: each
concern (loading, merging, scoring, export, and now input-file parsing)
lives in its own module, so main.py stays a thin orchestrator.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml

from config import (
    DEFAULT_STRUCT_PATH, DEFAULT_PERF_PATH, DEFAULT_OUT_PATH,
    DEFAULT_PROFILE_NAME, DEFAULT_TOP_N_PER_CATEGORY,
    DEFAULT_THRESHOLDS,
)


def deep_merge_dicts(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge `overrides` onto a deep copy of `defaults`.

    Unlike `{**defaults, **overrides}` (which replaces a whole nested
    dict if the key exists in overrides), this merges nested dicts
    key-by-key. That matters here because YAML overrides are often
    partial -- e.g. a user tuning `concept_weights.performance.return_3y`
    while learning what each column means should NOT silently wipe out
    the other default `performance` sub-weights (return_5y, return_1y,
    rank_3y) just because they didn't repeat them in the YAML.

    Only `dict` values are merged recursively; lists, strings, numbers,
    bools, and None are replaced outright by the override value.
    """
    result = deepcopy(defaults)
    for key, override_value in (overrides or {}).items():
        default_value = result.get(key)
        if isinstance(override_value, dict) and isinstance(default_value, dict):
            result[key] = deep_merge_dicts(default_value, override_value)
        else:
            result[key] = override_value
    return result


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

    raw_thresholds = raw.get("thresholds", {})
    if not isinstance(raw_thresholds, dict):
        raise ValueError(f"'thresholds' must be a mapping in {path}")

    # Deep-merge user thresholds onto the canonical DEFAULT_THRESHOLDS
    # schema (config.py), so missing keys -- and missing sub-keys inside
    # nested `weights` / `concept_weights` -- fall back safely instead of
    # each caller needing its own `.get(key, default)` fallback logic.
    thresholds = deep_merge_dicts(DEFAULT_THRESHOLDS, raw_thresholds)

    unknown_keys = set(raw_thresholds) - set(DEFAULT_THRESHOLDS)
    if unknown_keys:
        print(f"  Warning: {path} has unrecognized threshold key(s) {sorted(unknown_keys)} "
              f"-- check for typos. They will be ignored by known logic but are still "
              f"present in the merged thresholds dict.")

    return ProfileInput(
        profile_name=profile_name.strip(),
        struct_path=raw.get("struct_path") or DEFAULT_STRUCT_PATH,
        perf_path=raw.get("perf_path") or DEFAULT_PERF_PATH,
        out_path=raw.get("out_path") or DEFAULT_OUT_PATH,
        top_n_per_category=int(raw.get("top_n_per_category", DEFAULT_TOP_N_PER_CATEGORY)),
        thresholds=thresholds,
    )
