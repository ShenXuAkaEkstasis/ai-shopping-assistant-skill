#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shop_engine import VERSION, dispatch, self_test
from shop_engine.validation import load_json_file, load_json_text


def _read_payload(args: argparse.Namespace) -> dict:
    if args.input_file:
        return load_json_file(Path(args.input_file))
    if args.input_json:
        return load_json_text(args.input_json)
    text = sys.stdin.read()
    if not text.strip():
        return {"operation": "capabilities"}
    return load_json_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="WorkBuddy AI Shopping Assistant deterministic engine")
    parser.add_argument("--input-file", help="JSON input file")
    parser.add_argument("--input-json", help="JSON input string")
    parser.add_argument("--self-test", action="store_true", help="run built-in tests")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    try:
        if args.version:
            print(VERSION)
            return 0
        result = self_test() if args.self_test else dispatch(_read_payload(args))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if not args.self_test or result["passed"] == result["total"] else 1
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "engine_version": VERSION}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
