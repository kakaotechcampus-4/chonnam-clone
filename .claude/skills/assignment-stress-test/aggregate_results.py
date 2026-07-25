#!/usr/bin/env python3
"""주차 무관 범용 집계기. prompts.jsonl + results.jsonl을 읽어 불일치/예외/회귀를
정리해 사람이 읽을 리포트를 stdout에 낸다. run_harness.py와 마찬가지로 assignment
구조는 전혀 모르는 순수 집계 로직이라 매주 다시 짤 필요가 없다.

검색 품질 평가 (프롬프트에 expected_hits 필드가 있을 때만 동작):
  - run_harness가 fixture를 심을 때 payload에 넣은 마커 "[FXT:<fixture_id>]"를
    tool_result 이벤트 내용에서 스캔해, 어떤 fixture가 어떤 순서로 반환됐는지 복원한다.
    tool/스키마 구조를 몰라도 되는 이유가 이 마커 방식이다.
  - expected_hits=[...]: 반드시 반환돼야 할 fixture → recall/순위(hit@1, MRR) 계산.
  - expected_hits=[]: 아무 fixture도 반환되면 안 됨 (빈 결과가 정답인 프롬프트).
  - forbidden_hits=[...]: 반환되면 안 되는 fixture → 위반 카운트.
  - 순위는 tool_result 직렬화 문자열에서 마커가 처음 등장한 순서로 근사한다
    (hits 리스트가 관련도순으로 직렬화되므로 실용적으로 일치).

사용법:
  uv run python aggregate_results.py --prompts <prompts.jsonl> --results <results.jsonl> \
      [--previous <이전_results.jsonl>]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

MARKER_RE = re.compile(r"\[FXT:([A-Za-z0-9_\-]+)\]")


def returned_fixtures(events: list[dict]) -> list[str]:
    """tool_result 이벤트들에서 fixture 마커를 등장 순서대로 (중복 제거) 뽑는다."""

    ranked: list[str] = []
    for ev in events or []:
        if ev.get("event") != "tool_result":
            continue
        content = ev.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        for m in MARKER_RE.finditer(text):
            fid = m.group(1)
            if fid not in ranked:
                ranked.append(fid)
    return ranked


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

    # 검색 품질 (expected_hits 라벨 있는 프롬프트만)
    retrieval_evaluated = 0
    retrieval_recalls: list[float] = []
    retrieval_rrs: list[float] = []  # reciprocal rank (기대 fixture 중 최상위 것 기준)
    retrieval_failures: list[tuple] = []  # (pid, text, expected, ranked, 문제 설명)
    forbidden_violations: list[tuple] = []
    empty_expected_violations: list[tuple] = []
    retrieval_regressions: list[tuple] = []

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

        # ── 검색 품질 평가 (expected_hits 키가 있는 프롬프트만; None이면 평가 안 함)
        expected_hits = p.get("expected_hits")
        if expected_hits is not None and not r.get("error"):
            retrieval_evaluated += 1
            ranked = returned_fixtures(r.get("events") or [])

            if expected_hits == []:
                # 빈 결과가 정답 — fixture가 하나라도 반환되면 위반
                if ranked:
                    empty_expected_violations.append((pid, p["text"], ranked))
            else:
                found = [fid for fid in expected_hits if fid in ranked]
                recall = len(found) / len(expected_hits)
                retrieval_recalls.append(recall)
                ranks = [ranked.index(fid) + 1 for fid in found]
                retrieval_rrs.append(1.0 / min(ranks) if ranks else 0.0)
                if recall < 1.0:
                    missing = [fid for fid in expected_hits if fid not in ranked]
                    desc = "빈 결과" if not ranked else f"누락: {missing}"
                    retrieval_failures.append((pid, p["text"], expected_hits, ranked, desc))
                elif ranks and min(ranks) > 1:
                    retrieval_failures.append(
                        (pid, p["text"], expected_hits, ranked, f"정답이 {min(ranks)}순위 (관련도 낮은 hit가 상위)")
                    )

            for fid in p.get("forbidden_hits") or []:
                if fid in ranked:
                    forbidden_violations.append((pid, p["text"], fid, ranked))

            if prev_r is not None:
                prev_ranked = returned_fixtures(prev_r.get("events") or [])
                if prev_ranked != ranked:
                    retrieval_regressions.append((pid, p["text"], prev_ranked, ranked))

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

    if retrieval_evaluated:
        print("\n=== 검색 품질 (expected_hits 라벨 기준) ===")
        print(f"평가 대상: {retrieval_evaluated}개")
        if retrieval_recalls:
            mean_recall = sum(retrieval_recalls) / len(retrieval_recalls)
            mrr = sum(retrieval_rrs) / len(retrieval_rrs)
            perfect = sum(1 for x in retrieval_recalls if x == 1.0)
            hit1 = sum(1 for x in retrieval_rrs if x == 1.0)
            print(f"평균 recall: {mean_recall:.2f} (완전 회수 {perfect}/{len(retrieval_recalls)})")
            print(f"MRR: {mrr:.2f} (정답 1순위 {hit1}/{len(retrieval_rrs)})")
        print(f"빈-결과-정답 위반: {len(empty_expected_violations)} / forbidden 위반: {len(forbidden_violations)}")

        if retrieval_failures:
            print("\n--- 검색 실패 상세 (recall<1 또는 순위 밀림) ---")
            for pid, text, expected, ranked, desc in retrieval_failures:
                print(f"[{pid}] '{text}'")
                print(f"    기대: {expected} / 반환: {ranked} → {desc}")
        if empty_expected_violations:
            print("\n--- 빈 결과가 정답인데 fixture 반환됨 ---")
            for pid, text, ranked in empty_expected_violations:
                print(f"[{pid}] '{text}' → {ranked}")
        if forbidden_violations:
            print("\n--- forbidden fixture 반환됨 ---")
            for pid, text, fid, ranked in forbidden_violations:
                print(f"[{pid}] '{text}' → 금지 {fid} 포함 (전체: {ranked})")
        if args.previous and retrieval_regressions:
            print("\n--- 검색 결과 회귀 (반환 fixture 구성/순서 변화) ---")
            for pid, text, prev_ranked, ranked in retrieval_regressions:
                print(f"[{pid}] '{text}'")
                print(f"    이전: {prev_ranked} / 이번: {ranked}")


if __name__ == "__main__":
    main()
