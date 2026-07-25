#!/usr/bin/env python3
"""주차 무관 범용 실행기. prompts.jsonl을 읽어 AgentRuntime으로 실제 agent를 돌리고
results.jsonl로 기록한다. 과제별 지식(어떤 tool이 있는지, 프롬프트 내용)은 전혀 모른다 —
그건 SKILL.md 절차(구조 탐색/프롬프트 생성)가 매번 새로 계산해서 prompts.jsonl에 넣어준다.
이 스크립트 자체는 assignment 구조가 바뀌어도 고칠 필요 없는 순수 실행 배선이다.

prompts.jsonl 한 줄 형식:
  {"id": str, "text": str, "expected_tool": str|null, "category": str,
   "reason": str, "conversation_group": str|null}
  conversation_group이 같은 줄들은 conversation_id를 공유해 순서대로 실행된다
  (멀티턴 시나리오용). null/누락이면 매번 새 대화로 실행된다.

results.jsonl 한 줄 형식:
  {"id": str, "conversation_id": str, "answer": str,
   "tool_calls": [str, ...], "events": [...], "error": str|null}

격리: 이 harness는 실제 앱이 쓰는 data/kanana_app.sqlite3, data/chroma를 절대
건드리지 않는다. 실행마다 --out 파일 옆에 격리된 임시 DB/Chroma 디렉터리를 만들고,
fixed.config.CONFIG의 app_db_path/chroma_dir을 (frozen dataclass라 object.__setattr__로)
그쪽으로 돌려놓은 뒤에 fixed.agent_runtime을 import한다. student_parts.weekNN_* 모듈은
week_agent_registry가 첫 실행 시점에 importlib로 지연 import하므로, 그 시점엔 이미
패치된 CONFIG를 보고 자기 store 싱글턴(REFERENCE_STORE 등)을 만든다 — 이 순서가
깨지면(예: fixed.agent_runtime을 먼저 import하면) 격리가 안 먹으니 주의.

검색 품질 평가용 fixture seeding (--fixtures):
  fixtures.jsonl 한 줄 형식:
    {"fixture_id": str, "seed_module": str, "seed_via": str, "payload": dict,
     "id_fields": [str, ...], "note": str}
  - CONFIG 격리 직후, 프롬프트 실행 전에 seed_module을 import해 seed_via를 payload로
    호출한다 (LangChain tool이면 .invoke(payload), 일반 함수면 fn(**payload) →
    실패 시 fn(payload)). agent를 거치지 않으므로 결정론적이다.
  - fixture 판정은 "id 값 스캔" 방식이다: seed 반환값을 재귀 탐색해 id_fields에
    선언된 키의 값(예: reference_id, request_id, saved_rows[].id)을 전부 수집하고,
    집계기(aggregate_results.py)가 tool_result 직렬화 문자열에서 그 id 값의 등장을
    스캔해 어떤 fixture가 반환됐는지 판정한다. payload에 인공 마커를 심지 않으므로
    테스트 데이터가 오염되지 않는다. id를 하나도 못 뽑으면 즉시 실패시킨다.
  - fixture_id ↔ 수집된 id 목록은 --out 옆 fixture_map_<out stem>.json에 기록한다.
    집계기가 이 파일을 --fixture-map으로 받아 역매핑에 쓴다.

사용법:
  uv run python run_harness.py --prompts <prompts.jsonl> --active-week <N> --out <results.jsonl>
  (--isolate-dir로 격리 디렉터리 위치를 직접 지정할 수도 있음, 기본은 --out 옆 자동 생성)
  (--fixtures <fixtures.jsonl>을 주면 실행 전에 격리 DB/Chroma에 fixture를 심는다)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / ".env").exists() or (candidate / ".env.example").exists():
            return candidate
    raise RuntimeError("repo root를 찾지 못했습니다 (.env 또는 .env.example 필요).")


def _isolate_config(isolate_dir: Path) -> None:
    """CONFIG의 DB/Chroma 경로를 격리 디렉터리로 돌린다. agent_runtime import 전에 호출해야 한다."""

    from fixed.config import CONFIG

    isolate_dir.mkdir(parents=True, exist_ok=True)
    object.__setattr__(CONFIG, "app_db_path", isolate_dir / "kanana_app.sqlite3")
    object.__setattr__(CONFIG, "chroma_dir", isolate_dir / "chroma")


def _collect_ids(value: Any, id_fields: list[str]) -> list[str]:
    """seed 반환값을 재귀 탐색해 id_fields 키에 해당하는 값을 전부 문자열로 수집한다."""

    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in id_fields and isinstance(item, (str, int)) and str(item).strip():
                found.append(str(item))
            else:
                found.extend(_collect_ids(item, id_fields))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_ids(item, id_fields))
    return found


def _seed_fixtures(fixtures_path: Path, out_path: Path) -> None:
    """fixtures.jsonl을 격리 DB/Chroma에 심는다. _isolate_config() 이후에만 호출해야 한다."""

    import importlib

    fixture_map: dict[str, Any] = {}
    with fixtures_path.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    for row in rows:
        fid = row["fixture_id"]
        payload = row["payload"]
        id_fields = row.get("id_fields") or []
        if not id_fields:
            raise RuntimeError(f"fixture {fid}: id_fields 선언이 없습니다 — 채점 불가라 중단")

        module = importlib.import_module(row["seed_module"])
        target = getattr(module, row["seed_via"], None)
        if target is None:
            raise RuntimeError(f"fixture {fid}: {row['seed_module']}에 {row['seed_via']} 없음")

        if hasattr(target, "invoke"):  # LangChain tool
            result: Any = target.invoke(payload)
        else:
            try:
                result = target(**payload)
            except TypeError:
                result = target(payload)
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                pass
        ids = _collect_ids(result, id_fields)
        if not ids:
            raise RuntimeError(
                f"fixture {fid}: seed 반환값에서 id_fields={id_fields} 로 id를 하나도 못 뽑았습니다 — "
                f"반환 구조를 확인하고 id_fields를 고치세요. 반환값: {json.dumps(result, ensure_ascii=False)[:300]}"
            )
        fixture_map[fid] = {"seed_via": row["seed_via"], "ids": ids, "result": result}
        print(f"[seed] {fid} via {row['seed_via']} ids={ids}")

    map_path = out_path.parent / f"fixture_map_{out_path.stem}.json"
    map_path.write_text(json.dumps(fixture_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[seed] fixture {len(fixture_map)}개 심음 → {map_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="assignment-stress-test 실행기")
    parser.add_argument("--prompts", required=True, help="prompts.jsonl 경로")
    parser.add_argument("--active-week", required=True, type=int, help="실행할 주차 번호")
    parser.add_argument("--out", required=True, help="results.jsonl 출력 경로")
    parser.add_argument(
        "--isolate-dir",
        default=None,
        help="격리 DB/Chroma 디렉터리 (기본: <out 파일 부모>/isolated_data_<out stem>/)",
    )
    parser.add_argument(
        "--fixtures",
        default=None,
        help="검색 품질 평가용 fixtures.jsonl 경로 (실행 전 격리 DB/Chroma에 심음)",
    )
    args = parser.parse_args()

    repo_root = _find_repo_root(Path.cwd())
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    out_path = Path(args.out)
    isolate_dir = Path(args.isolate_dir) if args.isolate_dir else out_path.parent / f"isolated_data_{out_path.stem}"
    _isolate_config(isolate_dir)
    print(f"[격리] 실제 앱 DB 안 건드림 — 이번 실행 전용 격리 디렉터리: {isolate_dir}")

    if args.fixtures:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _seed_fixtures(Path(args.fixtures), out_path)

    from fixed.agent_runtime import AgentRuntime

    runtime = AgentRuntime(active_week=args.active_week)
    conversation_ids: dict[str, str] = {}

    prompts_path = Path(args.prompts)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with prompts_path.open(encoding="utf-8") as f, out_path.open("w", encoding="utf-8") as out:
        for line in f:
            line = line.strip()
            if not line:
                continue
            prompt = json.loads(line)
            group = prompt.get("conversation_group")
            conversation_id = conversation_ids.get(group) if group else None

            record: dict[str, object] = {"id": prompt["id"]}
            try:
                result = runtime.run_agent(prompt["text"], conversation_id)
                if group:
                    conversation_ids[group] = result.conversation_id
                tool_calls = [
                    ev["tool_name"] for ev in result.trace.get("events", []) if ev.get("event") == "tool_call"
                ]
                record.update(
                    {
                        "conversation_id": result.conversation_id,
                        "answer": result.answer,
                        "tool_calls": tool_calls,
                        "events": result.trace.get("events", []),
                        "error": result.trace.get("error"),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - 개별 프롬프트 실패는 전체를 막지 않는다
                record.update(
                    {
                        "conversation_id": conversation_id,
                        "answer": None,
                        "tool_calls": [],
                        "events": [],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            print(f"[{prompt['id']}] tools={record.get('tool_calls')} error={record.get('error')}")


if __name__ == "__main__":
    main()
