#!/usr/bin/env python3
"""주차 무관 범용 집계기. prompts.jsonl + results.jsonl을 읽어 불일치/예외/회귀를
정리해 사람이 읽을 리포트를 stdout에 낸다. run_harness.py와 마찬가지로 assignment
구조는 전혀 모르는 순수 집계 로직이라 매주 다시 짤 필요가 없다.

사용법:
  uv run python aggregate_results.py --prompts <prompts.jsonl> --results <results.jsonl> \
      [--previous <이전_results.jsonl>]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _load_jsonl(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out[row["id"]] = row
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="assignment-stress-test 집계기")
    parser.add_argument("--prompts", required=True, help="prompts.jsonl 경로")
    parser.add_argument("--results", required=True, help="이번 실행 results.jsonl 경로")
    parser.add_argument("--previous", default=None, help="회귀 비교용 이전 results.jsonl 경로 (선택)")
    args = parser.parse_args()

    prompts = _load_jsonl(Path(args.prompts))
    results = _load_jsonl(Path(args.results))
    previous = _load_jsonl(Path(args.previous)) if args.previous else {}

    matches = 0
    mismatches: list[tuple] = []
    off_topic_called = []
    no_expectation_ok = 0
    errors = []
    category_total: Counter = Counter()
    category_mismatch: Counter = Counter()
    regressions = []

    for pid, p in prompts.items():
        r = results.get(pid)
        if r is None:
            continue
        category_total[p["category"]] += 1
        tool_calls = r.get("tool_calls") or []
        expected = p.get("expected_tool")

        if r.get("error"):
            errors.append((pid, p["text"], r["error"]))
        elif expected is None:
            if p["category"] == "off_topic" and tool_calls:
                off_topic_called.append((pid, p["text"], tool_calls))
            else:
                no_expectation_ok += 1
        elif expected in tool_calls:
            matches += 1
        else:
            mismatches.append((pid, p["text"], expected, tool_calls, p["category"], p.get("reason", "")))
            category_mismatch[p["category"]] += 1

        prev_r = previous.get(pid)
        if prev_r is not None:
            prev_tools = prev_r.get("tool_calls") or []
            if prev_tools != tool_calls:
                regressions.append((pid, p["text"], prev_tools, tool_calls))

    total_with_expectation = sum(1 for p in prompts.values() if p.get("expected_tool") is not None)
    print("=== 요약 ===")
    print(f"기대 tool 있는 프롬프트: {total_with_expectation} / 매치 {matches} / 불일치 {len(mismatches)}")
    print(f"기대 tool 없음(정상): {no_expectation_ok}")
    print(f"주제이탈인데 tool 호출됨: {len(off_topic_called)}")
    print(f"에러: {len(errors)}")
    if args.previous:
        print(f"회귀(이전 실행 대비 tool 선택 바뀜): {len(regressions)}")
    print()
    print("카테고리별 전체/불일치:", dict(category_total), dict(category_mismatch))

    if mismatches:
        print("\n=== 불일치 상세 ===")
        for pid, text, expected, actual, cat, reason in mismatches:
            print(f"[{pid}][{cat}] '{text}'")
            print(f"    기대: {expected} / 실제: {actual}")
            print(f"    근거: {reason}")

    if off_topic_called:
        print("\n=== 주제이탈인데 tool 호출됨 ===")
        for pid, text, tools in off_topic_called:
            print(f"[{pid}] '{text}' -> {tools}")

    if errors:
        print("\n=== 에러 ===")
        for pid, text, err in errors:
            print(f"[{pid}] '{text}' -> {err}")

    if args.previous and regressions:
        print("\n=== 회귀 (이전 실행과 tool 선택이 달라진 프롬프트) ===")
        for pid, text, prev_tools, cur_tools in regressions:
            print(f"[{pid}] '{text}'")
            print(f"    이전: {prev_tools} / 이번: {cur_tools}")


if __name__ == "__main__":
    main()
