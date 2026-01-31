#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from config_loader import deep_merge, load_default_and_local


def _path_to_str(path: Tuple[str, ...]) -> str:
    return ".".join(path)


def _format_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return yaml.safe_dump(
            value,
            default_flow_style=True,
            sort_keys=True,
            allow_unicode=True,
        ).strip()
    return repr(value)


def _leaf_paths(value: Any, prefix: Tuple[str, ...]) -> List[Tuple[Tuple[str, ...], Any]]:
    if isinstance(value, dict) and value:
        out: List[Tuple[Tuple[str, ...], Any]] = []
        for key, child in value.items():
            out.extend(_leaf_paths(child, prefix + (str(key),)))
        return out
    return [(prefix, value)]


def _type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def _is_scalar(value: Any) -> bool:
    return not isinstance(value, (dict, list))


def _collect_diffs(
    default_cfg: Dict[str, Any],
    local_cfg: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    overrides: List[Dict[str, Any]] = []
    added_local: List[Dict[str, Any]] = []
    new_default: List[Dict[str, Any]] = []
    stale_local: List[Dict[str, Any]] = []
    type_warnings: List[Dict[str, Any]] = []

    def walk(dv: Any, lv: Any, path: Tuple[str, ...]) -> None:
        if isinstance(dv, dict) and isinstance(lv, dict):
            keys = set(dv.keys()) | set(lv.keys())
            for key in sorted(keys):
                next_path = path + (str(key),)
                if key in dv and key in lv:
                    d_child = dv[key]
                    l_child = lv[key]
                    if isinstance(d_child, dict) and isinstance(l_child, dict):
                        walk(d_child, l_child, next_path)
                    else:
                        if d_child != l_child:
                            label = "changed(list)" if isinstance(d_child, list) or isinstance(l_child, list) else "changed"
                            overrides.append(
                                {
                                    "path": _path_to_str(next_path),
                                    "label": label,
                                    "from": d_child,
                                    "to": l_child,
                                }
                            )
                        if isinstance(d_child, dict) != isinstance(l_child, dict) or isinstance(d_child, list) != isinstance(l_child, list):
                            type_warnings.append(
                                {
                                    "path": _path_to_str(next_path),
                                    "default_type": _type_name(d_child),
                                    "local_type": _type_name(l_child),
                                }
                            )
                        elif _is_scalar(d_child) and _is_scalar(l_child) and type(d_child) != type(l_child):
                            type_warnings.append(
                                {
                                    "path": _path_to_str(next_path),
                                    "default_type": _type_name(d_child),
                                    "local_type": _type_name(l_child),
                                }
                            )
                elif key in dv:
                    for leaf_path, leaf_val in _leaf_paths(dv[key], next_path):
                        new_default.append(
                            {"path": _path_to_str(leaf_path), "value": leaf_val}
                        )
                else:
                    for leaf_path, leaf_val in _leaf_paths(lv[key], next_path):
                        added_local.append(
                            {"path": _path_to_str(leaf_path), "value": leaf_val}
                        )
                        stale_local.append(
                            {"path": _path_to_str(leaf_path), "value": leaf_val}
                        )
        else:
            if dv != lv:
                label = "changed(list)" if isinstance(dv, list) or isinstance(lv, list) else "changed"
                overrides.append(
                    {"path": _path_to_str(path), "label": label, "from": dv, "to": lv}
                )
            if isinstance(dv, dict) != isinstance(lv, dict) or isinstance(dv, list) != isinstance(lv, list):
                type_warnings.append(
                    {
                        "path": _path_to_str(path),
                        "default_type": _type_name(dv),
                        "local_type": _type_name(lv),
                    }
                )
            elif _is_scalar(dv) and _is_scalar(lv) and type(dv) != type(lv):
                type_warnings.append(
                    {
                        "path": _path_to_str(path),
                        "default_type": _type_name(dv),
                        "local_type": _type_name(lv),
                    }
                )

    walk(default_cfg, local_cfg, tuple())
    return {
        "overrides": overrides,
        "added_local_only": added_local,
        "new_default_only": new_default,
        "stale_local_only": stale_local,
        "type_warnings": type_warnings,
    }


def _print_section(title: str, lines: List[str]) -> None:
    print(f"{title}:")
    if not lines:
        print("  (none)")
        return
    for line in lines:
        print(f"  {line}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect config.default.yaml vs config.yaml overrides.")
    parser.add_argument(
        "command",
        nargs="?",
        default="report",
        choices=["report", "effective"],
        help="report (default) or effective",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output (report or effective)")
    args = parser.parse_args()

    base = Path(__file__).parent.parent
    try:
        default_cfg, local_cfg, has_local = load_default_and_local(base)
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2

    effective_cfg = deep_merge(default_cfg, local_cfg)

    if args.command == "effective":
        if args.json:
            payload = {"effective_config": effective_cfg}
            print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        else:
            print(
                yaml.safe_dump(
                    effective_cfg,
                    sort_keys=True,
                    default_flow_style=False,
                    allow_unicode=True,
                ).rstrip()
            )
        return 0

    diffs = _collect_diffs(default_cfg, local_cfg)
    warn_count = len(diffs["stale_local_only"]) + len(diffs["type_warnings"])

    if args.json:
        payload = {
            "has_local_config": has_local,
            "overrides": diffs["overrides"],
            "added_local_only": diffs["added_local_only"],
            "new_default_only": diffs["new_default_only"],
            "stale_local_only": diffs["stale_local_only"],
            "type_warnings": diffs["type_warnings"],
            "effective_config": effective_cfg,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 1 if warn_count else 0

    if not has_local:
        print("WARNING: config.yaml not found; using only config.default.yaml")

    overrides_lines = [
        f'{item["label"]}: {item["path"]}: {_format_value(item["from"])} -> {_format_value(item["to"])}'
        for item in diffs["overrides"]
    ]
    added_lines = [
        f'added(local-only): {item["path"]} = {_format_value(item["value"])}'
        for item in diffs["added_local_only"]
    ]
    new_default_lines = [
        f'new(default-only): {item["path"]} = {_format_value(item["value"])}'
        for item in diffs["new_default_only"]
    ]
    stale_lines = [
        f'WARNING stale(local): {item["path"]} = {_format_value(item["value"])}'
        for item in diffs["stale_local_only"]
    ]
    type_lines = [
        (
            "WARNING type-mismatch: "
            f'{item["path"]} default={item["default_type"]} local={item["local_type"]}'
        )
        for item in diffs["type_warnings"]
    ]

    _print_section("Overrides report", overrides_lines)
    _print_section("Added local-only keys", added_lines)
    _print_section("New keys in default", new_default_lines)
    _print_section("Stale local keys", stale_lines)
    _print_section("Type compatibility warnings", type_lines)

    print("\nEffective config:")
    print(
        yaml.safe_dump(
            effective_cfg,
            sort_keys=True,
            default_flow_style=False,
            allow_unicode=True,
        ).rstrip()
    )

    return 1 if warn_count else 0


if __name__ == "__main__":
    sys.exit(main())
