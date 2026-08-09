from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from fixed.external_people_store import normalize_external_member_names
from fixed.langchain_trace import extract_agent_events, extract_final_text
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.schedule_decision import (
    CommonSlotCandidate,
    decide_final_slot_payload,
    find_common_available_slots_payload,
    normalize_date_bound,
    slot_to_text,
)
from student_parts.week01_wake_up_nana import join_system_prompt
from student_parts.week02_structure_natural_language_requests import extract_schedule_request
from student_parts.week04_retrieve_nanas_memory import week04_prompt_parts, week04_tools
from student_parts.week05_load_kanas_past_conversations import (
    EXTERNAL_LOOKUP_FAILURE_NOTICE,
    collect_member_schedules,
    external_member_names,
    extract_schedules_from_history,
    list_shared_schedules,
    load_conversation_messages,
    search_previous_conversations,
    unique_member_names,
    week05_prompt_parts,
)


_NANA_SUBAGENT: Any | None = None
_KANA_SUBAGENT: Any | None = None
_SUPERVISOR_AGENT: Any | None = None


# [6주차 수강생 구현 가이드]
#
# 용어
#   - supervisor: 사용자의 요청을 직접 처리하지 않고 Nana 또는 Kana에 한 번 위임하는 상위 agent입니다.
#   - 하위 agent: supervisor에게서 query를 받아 자기 도구만 사용하는 Nana 또는 Kana입니다.
#   - busy_rows: 멤버별로 이미 잡힌 일정(row)을 모은 목록입니다.
#   - candidate_slots: Kana가 busy_rows를 보고 직접 제안한 공통 가능 시간 후보 목록입니다.
#   - selected_index / selected_slot: 후보 목록에서 Kana가 고른 번호 / 후보 객체입니다.
#   - final_slot: 선택이 끝난 최종 시간 문자열입니다. 선택 전에는 null이어야 합니다.
#   - roster: 일정 조회에서 확인된 멤버 명단과 조회 상한 경고입니다.
#   - LLM: Kana가 후보를 제안할 때 사용하는 언어 모델입니다.
#   - RAG: 저장된 대화나 참고자료에서 관련 내용을 찾아 답변 근거로 사용하는 방식입니다.
#   - trace: agent와 도구가 어떤 순서로 호출됐는지 남긴 실행 기록입니다.
#   - payload: 도구가 반환하는 결과 dict입니다.
#   - final_slot_payload / final_decision_payload: 최종 시간 선택 결과를 supervisor가 읽기 쉽게 올려 둔 두 결과 항목입니다.
#
# 목표
#   Week 6은 "모든 기능을 한 agent가 직접 처리"하지 않고 supervisor가 Nana/Kana 하위 agent로 위임하게 만듭니다.
#   Nana는 개인 일정/저장/RAG를 맡고, Kana는 외부 대화/멤버 일정/그룹 시간 결정을 맡습니다.
#   supervisor가 직접 볼 수 있는 tool은 nana_agent와 kana_agent 두 개뿐입니다.
#
# 과제 구성
#   - 메인과제: 한 agent가 모두 처리하던 구조를 supervisor + Nana/Kana 하위 agent로 나누어
#     supervisor가 요청을 알맞은 하위 agent에 위임하는 뼈대를 완성합니다.
#     세 agent의 system prompt를 직접 작성하는 것과 위임 wrapper tool 두 개 구현이 여기 들어갑니다.
#   - 추가 과제: Kana의 공통 가능 시간 후보 검증(find_common_available_slots)과
#     최종 시간 결정(decide_final_slot)까지 붙여 그룹 일정 조율을 마무리합니다.
#
# 구현 위치와 사용할 코드
#   - 이 파일(student_parts/week06_kanamate_decides_schedule.py)의 Week 6 전용 tool과 sub-agent wrapper를 구현합니다.
#   - 공통 가능 시간 검증/최종 선택 결과 dict 생성은 fixed/schedule_decision.py의
#     find_common_available_slots_payload(), decide_final_slot_payload(), normalize_date_bound()를 사용합니다.
#   - Nana 하위 agent 도구는 student_parts/week04_retrieve_nanas_memory.py의 week04_tools()를 그대로 사용합니다.
#   - Kana 하위 agent 도구는 이 파일의 kana_tools()에서 구성하며, Week 2 extract_schedule_request와
#     Week 5 wrapper tool(search_previous_conversations, extract_schedules_from_history,
#     collect_member_schedules 등), find_common_available_slots, decide_final_slot을 포함합니다.
#   - supervisor가 볼 수 있는 도구는 supervisor_tools()의 nana_agent, kana_agent 두 개뿐입니다.
#   - nana_agent()/kana_agent()/build_langchain_supervisor_agent()는 create_agent(...)로 각각 필요한 agent를 만들고 재사용합니다.
#   - trace 정리는 fixed/langchain_trace.py의 extract_agent_events(), extract_final_text()를 사용합니다.
#
# 메인과제 구현 대상
#   1. week06_prompt_parts / nana_prompt_parts / kana_prompt_parts / supervisor_system_prompt
#      - supervisor와 Nana/Kana 하위 에이전트의 역할 분담을 prompt로 직접 정의합니다.
#      - supervisor는 직접 업무를 처리하지 않고 nana_agent 또는 kana_agent로만 위임하게 씁니다.
#      - Nana는 개인 일정/저장/RAG, Kana는 외부 멤버 일정/공통 시간 결정을 담당하게 씁니다.
#      - week06_prompt_parts는 week05_prompt_parts()를, nana_prompt_parts는 week04_prompt_parts()를 누적합니다.
#        kana_prompt_parts만 누적 없이 시작하므로 Kana 역할을 처음부터 작성해야 합니다.
#      - 하위 에이전트는 supervisor prompt를 공유하지 않으므로 각자 필요한 지시를 스스로 갖고 있어야 합니다.
#
#   2. nana_agent
#      - supervisor가 넘긴 query로 Nana 하위 agent를 이 tool 안에서 만들거나 재사용해 실행합니다.
#      - 개인 일정 조회/생성/수정/삭제 판단은 하위 agent가 prompt와 tool description을 근거로 수행합니다.
#      - 하위 agent 결과에서 answer, trace, inner_tool_names를 뽑아 JSON 문자열로 반환합니다.
#      - 개인 일정 생성/조회/수정/삭제, todo/reminder 저장, 개인 참고자료와 앱 대화 RAG는 Nana 담당입니다.
#
#   3. kana_agent
#      - supervisor가 넘긴 query로 Kana 하위 agent를 이 tool 안에서 만들거나 재사용해 실행합니다.
#      - 하위 실행 기록을 훑어 decide_final_slot 결과를 final_slot_payload로 끌어올립니다.
#      - answer, trace, inner_tool_names, final_slot_payload, final_decision_payload를 JSON으로 반환합니다.
#      - 외부 멤버 일정 조회, 공유 일정 row 조회, 공통 가능 시간 후보 검증과 최종 시간 결정은 Kana 담당입니다.
#
# 추가 과제 구현 대상 (구현하지 않으려면 kana_tools() 목록에서 해당 tool을 제거)
#   1. FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION / DECIDE_FINAL_SLOT_DESCRIPTION
#      - Kana agent가 두 tool을 언제 어떤 argument로 호출할지 판단하는 유일한 근거가 tool description입니다.
#      - Python tool이 자동으로 최적 시간을 고르는 것이 아니라, agent가 busy_rows를 근거로 후보와 최종 시간을
#        직접 골라 argument로 넘기게 만들어야 합니다. 이 점이 description에 없으면 agent가 tool에 계산을 떠넘깁니다.
#      - candidate_slots 항목 형식(date, start_time, end_time, duration_minutes, reason)과
#        final_slot 형식('YYYY-MM-DD HH:MM-HH:MM')을 명시해 argument 형태를 고정합니다.
#
#   2. find_common_available_slots_dict / find_common_available_slots / decide_final_slot
#      - find_common_available_slots는 busy-time row를 Python 규칙이나 도구 안의 새 언어 모델로 계산하지 않고,
#        Kana agent가 직접 고른 candidate_slots 목록을 검증하고 기록합니다.
#      - date_from/date_to에 ISO datetime이 들어오면 normalize_date_bound()로 날짜 부분만 사용합니다.
#      - busy_rows가 None이면 collect_member_schedules를 호출해 내 일정과 외부 멤버 busy-time을 모읍니다.
#      - decide_final_slot도 도구 안에서 언어 모델을 다시 호출하지 않고 Kana agent가 넘긴 선택 정보를 검증한 뒤,
#        final_slot, needs_agent_selection, reason을 과제에서 정한 JSON 형식으로 기록합니다.
#      - 반환 JSON은 과제에서 정한 최상위 final_slot, reason, candidates를 반드시 포함합니다.
#      - 후보 판단을 수행한 경우 members, busy_rows, candidate_slots도 함께 남겨 근거를 확인할 수 있게 합니다.
#      - selected_index나 selected_slot이 없으면 final_slot을 자동으로 고르지 말고 needs_agent_selection=True 상태를 유지합니다.
#
# 중요한 구조
#   Week 6 파일은 Week 1-5 구현을 다시 작성하지 않습니다.
#   이전 주차 tool을 import하고 kana_tools(), supervisor_tools()에서 역할별로 조립합니다.
#   prompt 함수는 메인과제 구현 대상입니다. supervisor와 Nana/Kana는 서로 다른 system prompt로 동작하므로,
#   위임 규칙과 역할 분담을 어떻게 쓰느냐가 Week 6 동작을 그대로 좌우합니다.
#   두 tool description 상수도 추가 과제 구현 대상입니다. Python 구현과 description이 서로 다른 계약을 말하면
#   agent가 잘못된 argument를 넘기므로, 두 tool을 구현할 때 description도 같은 계약으로 함께 씁니다.
#   각 tool이 받는 argument 이름과 형식은 FindCommonAvailableSlotsInput / DecideFinalSlotInput에 이미 정의되어 있으니
#   description은 그 스키마를 말로 풀어 agent가 언제 무엇을 채울지 판단하게 만드는 역할입니다.
#   fixed/schedule_decision.py는 후보의 기본 조건 검증과 결과 dict 생성을 맡고,
#   이 파일의 wrapper는 일정 수집과 agent의 후보 선택 정보 검증을 맡습니다.
#
# Compatibility helper
#   propose_group_schedule은 기존 흐름을 위해 구현된 상태로 유지하며 kana_tools()에는 들어가지 않습니다.
#   현재 supervisor/kana_tools() 경로의 구현 대상은 prompt 함수 4개와 nana_agent, kana_agent(메인),
#   tool description 상수 2개와 find_common_available_slots_dict, find_common_available_slots,
#   decide_final_slot(추가)입니다.
#
# 검증 방법
#   - 메인과제: ./run.sh --week6을 실행하고, supervisor trace에서 nana_agent 또는 kana_agent 중
#     무엇이 선택됐는지, 개인 일정 조회에서 Nana 하위 agent trace에 personal_list_saved_schedules
#     호출이 남는지 확인합니다. 위임이 엉뚱한 agent로 가면 tool 구현이 아니라 prompt의 판단 기준을 먼저 고칩니다.
#     추가 과제를 아직 구현하지 않았다면 kana_tools()에서 find_common_available_slots와
#     decide_final_slot을 빼고 Kana prompt에서도 두 tool 언급을 지운 뒤 위임 흐름만 확인합니다.
#   - 추가 과제: 그룹 일정 요청에서 하위 trace에 search_previous_conversations,
#     extract_schedules_from_history 또는 collect_member_schedules, find_common_available_slots,
#     decide_final_slot이 이어지고 final_slot_payload가 최종 답변과 일치하는지 확인합니다.
#
# 함수별 동작 설명 ([메인]/[추가]/[공통]은 각 함수가 속한 과제 티어입니다)
#   - [메인] week06_system_prompt() / week06_prompt_parts()
#     supervisor agent의 system prompt를 만듭니다. supervisor는 직접 업무를 처리하지 않고 nana_agent 또는 kana_agent로 위임합니다.
#
#   - [메인] nana_prompt_parts() / kana_prompt_parts()
#     하위 에이전트별 역할 prompt를 만듭니다. Nana는 개인 일정/저장/RAG, Kana는 외부 멤버 일정/공통 시간 결정을 담당합니다.
#
#   - [메인] nana_system_prompt() / kana_system_prompt() / supervisor_system_prompt()
#     prompt 조각을 join_system_prompt(...)로 합쳐 실제 create_agent(...)에 넘길 system prompt 문자열을 만듭니다.
#     supervisor_system_prompt()는 누적 조각 뒤에 supervisor 실행 역할 지시를 덧붙이는 자리입니다.
#
#   - [공통] _tool_call_names(events)
#     trace event 목록에서 tool_call 이벤트의 tool_name만 뽑아 UI와 테스트가 호출 순서를 쉽게 확인하게 합니다.
#
#   - [공통] extract_langchain_trace(result)
#     supervisor 실행 결과를 events, 선택된 하위 agent, 내부 tool 이름, 최종 시간 결과가 포함된 실행 기록 dict로 정리합니다.
#
#   - [공통] tool_name(tool_object)
#     LangChain tool 객체와 일반 함수 객체에서 이름을 안전하게 읽습니다. agent_tool_names(...)에서 사용합니다.
#
#   - [추가] FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION / DECIDE_FINAL_SLOT_DESCRIPTION
#     Kana agent가 두 tool을 언제 어떤 argument로 호출할지 판단하는 근거가 되는 tool description입니다.
#     tool이 후보나 최종 시간을 대신 계산해주지 않는다는 점을 agent가 알 수 있게 써야 합니다.
#
#   - [추가] FindCommonAvailableSlotsInput / DecideFinalSlotInput
#     Kana agent가 공통 가능 시간 후보와 최종 선택을 tool argument로 넘길 때 쓰는 Pydantic 입력 스키마입니다.
#
#   - [공통] ProposeGroupScheduleInput / AgentQueryInput
#     호환용 그룹 일정 제안 tool(구현 완료)과 supervisor가 하위 agent에 query를 넘기는 wrapper tool(메인과제)의 입력 스키마입니다.
#
#   - [추가] find_common_available_slots_dict(...)
#     멤버 이름과 날짜 범위를 정규화하고, busy_rows가 없으면 collect_member_schedules를 호출해 수집합니다.
#     실제 후보 검증 결과 dict 생성은 fixed/schedule_decision.py의 find_common_available_slots_payload(...)가 맡습니다.
#
#   - [추가] find_common_available_slots(...)
#     Kana agent가 직접 고른 candidate_slots가 busy_rows와 겹치지 않는지 검증하고 JSON 문자열로 반환하는 tool입니다.
#
#   - [추가] decide_final_slot(...)
#     Kana agent가 직접 고른 selected_index/final_slot/reason을 과제 JSON 형식에 맞는 최종 결과로 기록합니다.
#
#   - [공통] kana_tools() / supervisor_tools() / agent_tool_names(agent_name)
#     Kana 하위 agent와 supervisor가 볼 수 있는 tool 목록을 역할별로 조립하고 이름 목록을 제공합니다.
#
#   - [공통] propose_group_schedule(...)
#     이전 실습 흐름과의 호환을 위해 남겨 둔 그룹 일정 최종 제안 helper입니다. 구현 완료 상태이고
#     kana_tools()에도 들어가지 않습니다. 현재 핵심 경로는 decide_final_slot입니다.
#
#   - [메인] nana_agent(query)
#     supervisor가 개인 업무를 위임할 때 호출하는 tool입니다. Week 4 tool을 가진 Nana 하위 agent를 실행합니다.
#
#   - [메인] kana_agent(query)
#     supervisor가 외부 멤버/그룹 조율 업무를 위임할 때 호출하는 tool입니다. Kana 하위 agent trace에서
#     final_slot_payload와 final_decision_payload를 끌어올려 supervisor가 최종 답변에 사용할 수 있게 합니다.
#
#   - [공통] build_langchain_supervisor_agent() / build_week_agent()
#     supervisor agent를 한 번만 만들고 재사용합니다. build_week_agent()는 실행기가 호출하는 표준 entry point입니다.


def week06_system_prompt() -> str:
    """6주차 supervisor agent가 따르는 시스템 프롬프트입니다."""

    return supervisor_system_prompt()


def week06_prompt_parts() -> list[str]:
    """1~6주차 supervisor system prompt 조각을 누적합니다."""

    return [
        *week05_prompt_parts(),
        "## Week 6 supervisor 위임 규칙\n"
        "- supervisor는 직접 일정 업무를 처리하지 않고 nana_agent 또는 kana_agent 중 하나로 한 번만 위임한다.\n"
        "- 개인 일정 조회·생성·수정·삭제, 개인 참고자료/RAG, 확정된 일정 저장은 Nana 담당이다.\n"
        "- 외부 구성원 일정 조회와 여러 사람의 공통 가능 시간·그룹 일정 조율은 Kana 담당이다.\n"
        "- 한 번의 supervisor 위임으로 개인 저장과 그룹 조율을 연달아 수행하지 않는다. 그룹 조율 요청은 Kana가 최종 후보만 확정해 답하고 저장됐다고 말하지 않는다. 이미 확정된 그룹 일정의 저장을 별도로 요청받은 턴에는 Nana에게 전달한다.\n"
        "- 위임할 때 사용자의 원래 요청과 날짜·멤버·소요 시간 같은 조건을 query에 보존한다.",
    ]


def nana_prompt_parts() -> list[str]:
    """Week 6 Nana 하위 에이전트 전용 system prompt 조각입니다."""

    return [
        *week04_prompt_parts(),
        "## Week 6 Nana 담당 범위\n"
        "- 개인 일정 조회·생성·수정·삭제, 개인 참고자료와 대화 RAG는 Nana가 담당한다.\n"
        "- 개인 일정 요청은 기존 개인/SQLite 도구의 결과를 근거로 답하고, 없는 일정을 지어내지 않는다.\n"
        "- 확정된 개인 일정과 확정된 그룹 일정의 저장도 Nana가 담당하며, 저장 요청은 kind에 맞춰 save_structured_request로 처리한다.\n"
        "- 외부 멤버의 바쁜 시간이나 그룹 공통 시간 후보를 직접 조율하는 요청은 Kana 담당이다.",
    ]


def kana_prompt_parts() -> list[str]:
    """Week 6 Kana 하위 에이전트 전용 system prompt 조각입니다."""

    return [
        # Kana 프롬프트만 이전 주차를 누적하지 않으므로(이 파일 맨 위 구현 가이드), Week 1의
        # "오늘 날짜" 조각이 딸려 오지 않는다. 그런데 "8월 20일" 같은 사용자 표현을
        # date_from/date_to 값으로 바꾸는 일은 Kana가 한다 — supervisor는 사용자 원문과 조건을
        # 그대로 보존해 넘기기만 한다. 기준 날짜가 없으면 Kana가 연도를 지어낸다.
        "## 날짜 해석 기준\n"
        f"- 오늘 날짜는 {current_app_date_iso()}다.\n"
        "- 상대/모호한 날짜는 이 기준으로 해석한다.",
        "## Week 6 Kana 그룹 일정 조율\n"
        "- Kana는 외부 구성원 일정 조회, 내 일정과 외부 일정의 busy-time 근거 수집, 그룹 공통 시간 조율을 담당한다.\n"
        "- collect_member_schedules의 member_names에는 외부 구성원 이름만 넣고 \"나\"는 넣지 않는다. member_names가 없거나 빈 목록이면 전체 구성원 요청으로 처리한다.\n"
        "- collect_member_schedules 결과의 rows를 busy_rows로 그대로 읽는다. roster.limit_reached가 true이면 roster.notice를 답변에 포함하고 현재 확인된 구성원 기준이라고 제한해서 말한다.\n"
        "- collect_member_schedules 결과에 ok=false가 있으면 시간을 확정하지 말고, 외부 일정을 확인하지 못했다는 사실을 답변에 적는다.\n"
        "- list_shared_schedules의 member_names에는 \"나\"를 포함한다. 이 공유 저장소 조회 규칙은 collect_member_schedules의 member_names에 \"나\"를 넣지 않는 규칙과 다르다.\n"
        "- 바쁜 시간만 물었다면 search_previous_conversations를 건너뛰고 extract_schedules_from_history를 바로 호출한다. 대화 원문이나 일정 근거가 필요할 때만 search_previous_conversations로 찾고, 필요한 경우 load_conversation_messages를 읽은 뒤 일정 추출을 한다.\n"
        "- 조회 결과에 없는 일정을 지어내지 않는다.\n"
        "- 도구 결과의 24시간제 표기를 그대로 사용한다.\n"
        "- extract_schedule_request는 사용자의 자연어에서 일정 날짜·멤버·소요 시간을 구조화해야 할 때만 호출하고, 이미 구조화된 조회 조건이 있으면 생략한다.\n"
        "- find_common_available_slots는 후보를 계산하는 도구가 아니다. busy_rows를 근거로 candidate_slots를 직접 만들고, 각 후보에 date(YYYY-MM-DD), start_time(HH:MM), end_time(HH:MM), duration_minutes, reason을 채운다.\n"
        # 이 파일 맨 위 구현 가이드는 decide_final_slot이 "어떻게 동작하는가"만 정하고,
        # "언제 부르는가"는 tool description과 이 프롬프트가 판단하도록 맡긴다. 그래서 세 경우를
        # 나눠 적는다: ①후보를 골랐다 ②후보는 남았는데 못 고르겠다 ③남은 후보가 하나도 없다.
        # ③은 확정할 대상 자체가 없으므로 호출하지 않고, 가능한 시간이 없다고 답한다.
        "- 후보를 만든 뒤 반드시 find_common_available_slots를 호출하고, 그 결과에 실제로 남은 후보 중 하나를 selected_index 또는 selected_slot으로 골라 반드시 decide_final_slot을 이어서 호출한다. 남은 후보가 있는데 하나를 고를 수 없으면 시간을 지어내지 말고 decide_final_slot을 final_slot=null, needs_agent_selection=true로 호출한다. 검증 결과 남은 후보가 하나도 없으면 시간을 지어내지 말고 가능한 시간이 없다고 그대로 답한다.\n"
        "- 최종 답변에는 검증된 후보와 decide_final_slot의 최종 선택만 사용하며, busy_rows와 겹치거나 날짜·업무시간·소요 시간 조건을 벗어난 시간을 쓰지 않는다.\n"
        "- 일정 저장은 내(Kana) 담당이 아니며 이 하위 agent에는 Nana 위임 도구가 없다. 그룹 조율 턴에서는 저장 완료라고 말하지 않고 확정된 final_slot만 반환한다. 사용자가 확정된 그룹 일정 저장을 별도로 요청하면 supervisor가 Nana로 라우팅한다. 그룹 일정 저장 자체를 범위 밖이라고 말하지 않는다.",
    ]


def nana_system_prompt() -> str:
    return join_system_prompt(nana_prompt_parts())


def kana_system_prompt() -> str:
    return join_system_prompt(kana_prompt_parts())


def supervisor_system_prompt() -> str:
    return join_system_prompt(
        [
            *week06_prompt_parts(),
            "## Week 6 supervisor 최종 실행 규칙\n"
            "- Week 5에 상속된 \"여러 사람의 최종 회의 시간을 확정하지 말라\"는 지시는 Week 6에서 덮어쓴다. Week 6 supervisor는 Kana가 고른 검증된 후보 중 최종 시간까지 확정해 답한다.\n"
            "- Week 5에 상속된 \"답변에는 바쁜 시간이 아니라 비어 있는 구간을 적는다\"는 빈 구간 계산 지시는 Week 6에서 덮어쓴다. Week 6 답변에는 빈 시간표를 새로 계산·열거하지 말고 Kana의 검증된 candidate_slots와 decide_final_slot의 final_slot만 적는다.\n"
            "- 먼저 nana_agent 또는 kana_agent 중 정확히 하나를 호출하고, 직접 개인/외부 일정 도구를 호출하거나 업무를 처리하지 않는다. 개인 일정 요청은 Nana, 외부 멤버·그룹 일정 요청은 Kana로 보낸다.\n"
            "- Kana 결과의 find_common_available_slots를 통과한 검증된 후보와 decide_final_slot의 final_slot만 최종 답변에 사용한다. 빈 시간표를 새로 계산하거나 임의의 시간을 만들지 않는다.\n"
            "- 후보가 없거나 최종 선택이 없으면 시간을 지어내지 말고 추가 선택이 필요하다고 알린다.\n"
            "- 결과에 roster.limit_reached=true와 roster.notice가 있으면 notice를 답변에 포함하고 \"현재 확인된 구성원 기준\", \"일부 구성원이 누락될 수 있음\"처럼 제한적으로 표현한다. 이 경우에도 선택된 final_slot과 final_slot_payload는 유지하되 \"전원 확정\"이나 \"모두 가능\"이라고 말하지 않는다.\n"
            "- 결과에 external_lookup.ok=false가 있으면 external_lookup.notice를 답변에 포함하고, 외부 구성원 일정을 확인하지 못한 상태라고 밝힌다. 이 경우 \"전원 확정\"이나 \"모두 가능\"이라고 말하지 않는다.\n"
            "- Week 6에는 공유 저장소를 직접 고치는 도구가 없다. 공유 일정 등록·삭제 요청은 처리할 수 없다고 밝히고, 대신 현재 제공되는 공유 row 조회와 시간 조율 범위만 안내한다. shared_로 시작하는 일정 id도 개인 일정 삭제 도구로 처리하지 않는다.\n"
            "- final_slot_payload는 decide_final_slot 반환 dict이고, final_decision_payload는 호환용 propose_group_schedule의 final_decision 값일 때만 사용한다. 둘을 서로 복사하지 않는다.\n"
            "- 이번 supervisor 턴에서 Kana 결과는 그룹 조율과 final_slot 확정까지만 근거로 삼고 저장 완료라고 말하지 않는다. 사용자가 이미 확정된 그룹 일정의 저장을 별도로 요청한 턴에는 Nana에게 날짜·멤버·시간을 보존해 위임하며, 그룹 일정 저장을 범위 밖이라고 말하지 않는다.",
        ]
    )


def _tool_call_names(events: list[dict[str, Any]]) -> list[str]:
    return [event["tool_name"] for event in events if event.get("event") == "tool_call" and event.get("tool_name")]


def _final_slot_payload_in(content: dict[str, Any]) -> dict[str, Any] | None:
    """도구 실행 결과 하나에서 최종 시간 결과 dict를 꺼냅니다. 없으면 None입니다.

    decide_final_slot 결과가 바로 들어온 경우와 final_slot_payload 키 안에 한 번 감싸져
    들어온 경우를 모두 처리합니다. 두 trace 정리 함수가 같은 판단을 쓰도록 한 곳에 둡니다.
    """

    if content.get("final_slot_payload"):
        return content["final_slot_payload"]
    if "final_slot" in content:
        return content
    return None


def _kana_trace_payloads(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Kana 하위 agent의 실행 기록에서 supervisor가 읽을 결과 dict를 모읍니다.

    여기서는 도구 결과만 보고, extract_langchain_trace는 모든 실행 기록을 봅니다.
    final_decision은 여기서만 읽으므로 두 함수의 순회를 하나로 합치지 않습니다.
    최종 시간 결과를 찾는 규칙만 _final_slot_payload_in으로 공유합니다.
    """

    contents = [
        event["content"]
        for event in events
        if event.get("event") == "tool_result" and isinstance(event.get("content"), dict)
    ]

    # 네 결과를 같은 반복문에 억지로 합치지 않는다. 선택 규칙이 서로 다르다.
    # 멤버 명단은 누락 경고가 있는 결과를 우선하고, 외부 조회 상태와 최종 시간은 마지막 결과를 쓴다.

    # 멤버 명단은 여러 도구 결과에 들어 있을 수 있다. 그중 "명단이 잘렸을 수 있다"는 경고가 붙은
    # 것이 하나라도 있으면 그것을 고른다 — 경고 없는 멤버 명단으로 덮어써 경고를 잃으면 안 된다.
    roster_payload: dict[str, Any] | None = None
    for content in contents:
        roster = content.get("roster")
        if isinstance(roster, dict) and (
            roster_payload is None or roster.get("limit_reached")
        ):
            roster_payload = roster

    # 외부 조회 상태는 가장 나중 결과를 쓴다. 같은 턴에 여러 번 조회했다면 마지막 상태가 현재 상태다.
    external_lookup_payload: dict[str, Any] | None = None
    for content in contents:
        if isinstance(content.get("external_lookup"), dict):
            external_lookup_payload = content["external_lookup"]

    # 마지막에 찾은 최종 시간 결과를 쓴다. 최종 시간 결과가 없는 도구 결과는 앞서 찾은 값을 덮지 않는다.
    final_slot_payload: dict[str, Any] | None = None
    for content in contents:
        final_slot_payload = _final_slot_payload_in(content) or final_slot_payload

    # propose_group_schedule 결과는 final_decision 키 아래에 들어 있다. 위와 같은 이유로,
    # final_decision_payload로 한 번 감싸져 온 경우에는 그 안쪽 값을 꺼내 쓴다.
    final_decision_payload: dict[str, Any] | None = None
    for content in contents:
        if content.get("final_decision_payload"):
            final_decision_payload = content["final_decision_payload"]
        elif "final_decision" in content:
            final_decision_payload = content["final_decision"]

    return {
        "final_slot_payload": final_slot_payload,
        "final_decision_payload": final_decision_payload,
        "roster": roster_payload,
        "external_lookup": external_lookup_payload,
    }


def extract_langchain_trace(result: dict[str, Any]) -> dict[str, Any]:
    """Week 6 supervisor 실행 결과를 화면에 보여줄 실행 기록 결과 dict로 변환합니다."""

    events = extract_agent_events(result)
    inner_tool_names: list[str] = []
    final_slot_payload: dict[str, Any] | None = None
    final_decision_payload: dict[str, Any] | None = None
    selected_agent: str | None = None

    for event in events:
        if event.get("event") == "tool_call" and event.get("tool_name") in {"nana_agent", "kana_agent"}:
            selected_agent = event["tool_name"]
        content = event.get("content")
        if isinstance(content, dict):
            inner_tool_names.extend(content.get("inner_tool_names") or [])
            final_slot_payload = _final_slot_payload_in(content) or final_slot_payload
            if content.get("final_decision_payload"):
                final_decision_payload = content["final_decision_payload"]

    return {
        "events": events,
        "supervisor_selected_agent": selected_agent,
        "inner_tool_names": inner_tool_names,
        "final_slot_payload": final_slot_payload,
        "final_decision_payload": final_decision_payload,
    }


def tool_name(tool_object: Any) -> str:
    return getattr(tool_object, "name", getattr(tool_object, "__name__", str(tool_object)))


FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION = (
    "이 도구는 공통 가능 후보를 계산하는 도구가 아니다. 앞선 일정 조회 결과의 busy_rows를 읽고 Kana가 "
    "후보 candidate_slots를 직접 만들어 검증을 맡긴다. 각 후보에는 date(YYYY-MM-DD), start_time(HH:MM), "
    "end_time(HH:MM), duration_minutes, reason을 모두 넣고, 어떤 busy_rows와도 겹치지 않게 한다. "
    "후보 날짜는 date_from~date_to 안에 있어야 하고 workday_start~workday_end 안에 있어야 한다. "
    "workday_start/workday_end를 생략하면 기본 업무시간은 09:00~18:00이다. 후보 길이는 duration_minutes 이상이어야 한다. "
    "busy_rows는 앞선 collect_member_schedules 결과에서 복사한다. 이 도구 결과만으로 답변을 끝내지 말고, "
    "반환된 candidate_slots 중 하나를 selected_index 또는 selected_slot으로 고른 뒤 반드시 decide_final_slot을 이어서 호출한다. "
)


DECIDE_FINAL_SLOT_DESCRIPTION = (
    "이 도구는 최종 시간을 자동으로 계산하거나 임의로 고르는 도구가 아니다. 반드시 find_common_available_slots가 "
    "반환한 candidate_slots 목록을 그대로 넘기고, 그중 하나를 selected_index 또는 selected_slot으로 지목한다. "
    "final_slot은 선택한 후보와 같은 'YYYY-MM-DD HH:MM-HH:MM' 형식으로 기록하며 후보 목록에 없는 시간은 절대 넣지 않는다. "
    "아직 선택하지 않았거나 candidate_slots가 비어 있으면 final_slot=null, needs_agent_selection=true로 둔다. "
    "선택 이유 reason과 근거 candidate_slots, busy_rows, member_names, date_from, date_to, duration_minutes도 함께 넘긴다. "
)


class FindCommonAvailableSlotsInput(BaseModel):
    member_names: list[str] | None = Field(
        default=None,
        description="공통 가능 시간을 찾아야 하는 외부 멤버 이름 목록. 전체 구성원이면 이 칸을 생략하거나 비워 둡니다.",
    )
    date_from: str = Field(description="조회 시작 날짜. ISO datetime이면 날짜 부분만 사용")
    date_to: str = Field(description="조회 종료 날짜. ISO datetime이면 날짜 부분만 사용")
    duration_minutes: int = Field(default=60, ge=30, le=480, description="회의 길이(분)")
    workday_start: str = Field(default="09:00", description="허용 업무 시간 시작 HH:MM")
    workday_end: str = Field(default="18:00", description="허용 업무 시간 종료 HH:MM")
    limit: int = Field(default=5, ge=1, le=20, description="최대 후보 수")
    busy_rows: list[dict[str, Any]] | None = Field(
        default=None,
        description="앞선 일정 조회 tool output에서 복사한 busy_rows. 후보는 이 row들과 overlap/겹치면 안 됩니다.",
    )
    candidate_slots: list[CommonSlotCandidate] = Field(
        default_factory=list,
        description=(
            "LLM agent가 직접 고른 후보 목록. 각 항목은 date, start_time, end_time, "
            "duration_minutes, reason을 포함하고 busy_rows와 겹치면 안 됩니다."
        ),
    )
    llm_reason: str | None = Field(default=None, description="LLM agent가 후보 목록을 고른 전체 이유")


class DecideFinalSlotInput(BaseModel):
    candidate_slots: list[Any] = Field(default_factory=list, description="find_common_available_slots 결과의 후보 목록")
    selected_slot: Any | None = Field(default=None, description="LLM agent가 직접 고른 후보 객체")
    selected_index: int | None = Field(default=None, description="LLM agent가 직접 고른 candidate_slots index")
    final_slot: str | None = Field(
        default=None,
        description="최종 확정 시간 텍스트. 형식은 'YYYY-MM-DD HH:MM-HH:MM'. 미확정이면 null",
    )
    needs_agent_selection: bool | None = Field(
        default=None,
        description="후보 선택이 더 필요하면 true, final_slot을 확정했으면 false",
    )
    member_names: list[str] | None = Field(default=None, description="회의 대상 멤버 목록")
    date_from: str | None = Field(default=None, description="요청 날짜 범위 시작")
    date_to: str | None = Field(default=None, description="요청 날짜 범위 종료")
    duration_minutes: int = Field(default=60, description="회의 길이(분)")
    reason: str | None = Field(default=None, description="최종 선택 또는 보류에 대한 사용자-facing 설명")
    busy_rows: list[dict[str, Any]] | None = Field(default=None, description="최종 결정 근거로 남길 busy_rows")


class ProposeGroupScheduleInput(BaseModel):
    """기존 호환용 그룹 일정 제안 입력입니다."""

    title: str
    member_names: list[str]
    candidate_slots: list[CommonSlotCandidate] = Field(default_factory=list)
    selected_slot: CommonSlotCandidate | None = None
    reason: str | None = None


class AgentQueryInput(BaseModel):
    """하위 에이전트 위임 입력입니다."""

    query: str


def find_common_available_slots_dict(
    member_names: list[str] | None = None,
    *,
    date_from: str,
    date_to: str,
    duration_minutes: int = 60,
    workday_start: str = "09:00",
    workday_end: str = "18:00",
    limit: int = 5,
    busy_rows: list[dict[str, Any]] | None = None,
    candidate_slots: list[dict[str, Any]] | None = None,
    llm_reason: str | None = None,
) -> dict[str, Any]:
    """일정이 없으면 수집하고, Kana가 제안한 후보를 조건에 맞는 결과 dict로 검증합니다.

    후보는 날짜 범위·업무시간·회의 길이·기존 일정 겹침·형식을 확인합니다.
    """

    # 여기서 "나"를 빼면 안 된다. ["나"]만 온 요청이 빈 목록이 되는데, Week 5의
    # _collect_member_schedules는 빈 목록을 "전원"으로 읽으므로 조회가 통째로 넓어진다.
    # "나"를 빼는 일은 Week 5가 외부 저장소를 조회하는 경계에서 맡는다.
    requested_member_names = unique_member_names(member_names)

    normalized_date_from = normalize_date_bound(date_from)
    normalized_date_to = normalize_date_bound(date_to)
    resolved_busy_rows = busy_rows
    roster: dict[str, Any] | None = None
    collected_payload: dict[str, Any] = {}
    collection_failed = False

    # 시작·끝 날짜가 뒤집혀 들어와도 후보 검사 쪽은 fixed의 date_range()가 알아서 흡수한다.
    # 그런데 일정 조회 쪽은 그렇지 않다 — SQL 조건이 date >= 시작 AND date <= 끝이라
    # (fixed/external_people_store.py의 list_shared_schedules) 뒤집힌 채로 넘기면 조건을
    # 만족하는 날이 하나도 없다. 오류 없이 "일정 0건"이 돌아오므로 사용자는 정말 비어 있는 줄
    # 안다. 그래서 여기서 앞뒤를 바로잡는다.
    # 날짜로 해석하지 않고 글자 순서로만 비교한다 — 날짜가 아닌 값이 와도 터지지 않아야 한다.
    if normalized_date_from > normalized_date_to:
        normalized_date_from, normalized_date_to = (
            normalized_date_to,
            normalized_date_from,
        )

    if resolved_busy_rows is None:
        try:
            # collect_member_schedules.invoke()의 인자 검증·결과 해석 단계에서 생긴 예외도
            # 이 도구의 외부 일정 조회 실패 결과로 바꾼다.
            collected = collect_member_schedules.invoke(
                {
                    "member_names": requested_member_names,
                    "date_from": normalized_date_from,
                    "date_to": normalized_date_to,
                }
            )
            if isinstance(collected, str):
                collected_payload = json.loads(collected)
            else:
                collected_payload = collected
            if not isinstance(collected_payload, dict):
                collected_payload = {}
            collection_failed = collected_payload.get("ok") is not True
            resolved_busy_rows = collected_payload.get("rows") or []
            if isinstance(collected_payload.get("roster"), dict):
                roster = collected_payload["roster"]
        except Exception:
            collection_failed = True
            resolved_busy_rows = []
            collected_payload = {}
            roster = None

    # 근거 이름을 얻는 곳이 세 군데인 것은 세 경우가 실제로 다 있기 때문이다.
    #   1단 requested_member_names — 요청이 전원([])이거나 "나"뿐이면 여기는 비어 있다.
    #   2단 collected_payload["filters"] — 위 collect를 부른 경우에만 있다.
    #   3단 busy_rows의 member_name — Kana가 busy_rows를 직접 넘기면 collect를 안 부르므로
    #        (위 resolved_busy_rows is None 갈래 참조) 2단이 통째로 없다. 그때 이름이
    #        남아 있는 곳은 여기뿐이다.
    evidence_external_names = external_member_names(requested_member_names)
    if not evidence_external_names:
        filters = collected_payload.get("filters")
        if isinstance(filters, dict):
            evidence_external_names = external_member_names(filters.get("member_names"))
    if not evidence_external_names:
        evidence_external_names = external_member_names(
            [
                row.get("member_name")
                for row in resolved_busy_rows or []
                if isinstance(row, dict)
            ]
        )

    # 이 목록은 답변에 근거로 보여줄 이름이라 리터럴 "나"를 쓴다. 외부 저장소를 조회할 때 쓰는
    # PERSONAL_SHARED_MEMBER_NAME과 지금은 값이 같지만, 일부러 그 상수를 쓰지 않는다. 상수로 묶으면
    # "화면에 보일 이름"과 "저장소 조회에 쓸 이름"이 한 값이 되어, 저장소 쪽 사정으로 상수가
    # 바뀌는 날 화면 표기까지 같이 바뀐다.
    evidence_member_names = [*evidence_external_names]
    if "나" not in evidence_member_names:
        evidence_member_names.append("나")

    payload = find_common_available_slots_payload(
        member_names=evidence_member_names,
        date_from=normalized_date_from,
        date_to=normalized_date_to,
        busy_rows=resolved_busy_rows or [],
        duration_minutes=duration_minutes,
        workday_start=workday_start,
        workday_end=workday_end,
        limit=limit,
        candidate_slots=candidate_slots,
        llm_reason=llm_reason,
    )
    # fixed helper 결과의 members 필드가 Week 6 근거 이름을 노출하므로 별도 member_names 키는 싣지 않는다.
    payload["date_from"] = normalized_date_from
    payload["date_to"] = normalized_date_to
    if roster is not None:
        payload["roster"] = roster
    if collection_failed:
        # 수집 실패 원인은 최종 결과 dict에 반드시 남긴다.
        payload["external_lookup"] = collected_payload.get(
            "external_lookup",
            {"ok": False, "notice": EXTERNAL_LOOKUP_FAILURE_NOTICE},
        )
        payload["ok"] = False
        # 외부 조회가 실패하면 외부 일정 근거 없이 통과한 후보도 믿을 수 없으므로 비운다.
        # external_lookup.notice를 함께 남겨 "후보 없음"과 "조회 실패"를 구분한다.
        payload["candidate_slots"] = []
    elif not candidate_slots:
        # 여기서 보는 candidate_slots는 이 함수가 인자로 "받은 원본"이지 위 결과 dict가 돌려준
        # 검증 통과 목록이 아니다. 그래서 냈는데 전부 탈락한 경우는 이 분기에 안 걸린다 —
        # 둘을 같은 값으로 읽으면, 후보를 냈는데 전부 탈락한 경우에도 "후보를 아직 안 냈다"는
        # 아래 안내가 붙어 버린다.
        # "후보를 아직 안 냈다"와 "낸 후보가 전부 탈락했다"가 fixed helper 결과에서는 똑같이
        # candidate_slots=[]로 나온다. 이 둘을 구분해 주지 않으면 Kana는 자기가 후보를 안 냈다는
        # 사실을 모른 채 "가능한 시간이 없다"고 답해 버린다.
        # 안내 문구에 업무시간 범위를 함께 적는 것이 중요하다 — 범위를 빼고 "직접 골라라"만
        # 적었더니 Kana가 업무시간을 스스로 넓혀 그 밖의 시간을 후보로 지어냈다.
        payload["needs_candidate_slots"] = True
        payload["notice"] = (
            f"candidate_slots를 받지 못했습니다. busy_rows와 겹치지 않는 후보를 "
            f"{workday_start}~{workday_end} 안에서 직접 만들어 이 도구를 다시 호출하세요. "
            f"업무시간을 넓히지 말고 그 범위 밖 시간은 후보로 넣지 마세요. "
            f"범위 안에 {duration_minutes}분이 남지 않으면 후보 없이 시간이 없다고 답하세요."
        )
    return payload


@tool(description=FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION, args_schema=FindCommonAvailableSlotsInput)
def find_common_available_slots(
    member_names: list[str] | None = None,
    *,
    date_from: str,
    date_to: str,
    duration_minutes: int = 60,
    workday_start: str = "09:00",
    workday_end: str = "18:00",
    limit: int = 5,
    busy_rows: list[dict[str, Any]] | None = None,
    candidate_slots: list[Any] | None = None,
    llm_reason: str | None = None,
) -> str:
    """Kana가 제안한 공통 가능 시간 후보를 날짜·업무시간·길이·겹침 조건에 맞는지 검증합니다.

    busy_rows가 없으면 먼저 collect_member_schedules로 일정 근거를 수집합니다.
    """

    return json.dumps(
        find_common_available_slots_dict(
            member_names=member_names,
            date_from=date_from,
            date_to=date_to,
            duration_minutes=duration_minutes,
            workday_start=workday_start,
            workday_end=workday_end,
            limit=limit,
            busy_rows=busy_rows,
            candidate_slots=candidate_slots,
            llm_reason=llm_reason,
        ),
        ensure_ascii=False,
    )


def _slot_as_jsonable(slot: Any) -> Any:
    if hasattr(slot, "model_dump"):
        return slot.model_dump()
    if isinstance(slot, dict):
        return dict(slot)
    return slot


@tool(description=DECIDE_FINAL_SLOT_DESCRIPTION, args_schema=DecideFinalSlotInput)
def decide_final_slot(
    candidate_slots: list[Any] | None = None,
    selected_slot: Any | None = None,
    selected_index: int | None = None,
    final_slot: str | None = None,
    needs_agent_selection: bool | None = None,
    member_names: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    duration_minutes: int = 60,
    reason: str | None = None,
    busy_rows: list[dict[str, Any]] | None = None,
) -> str:
    """Kana의 후보 선택 정보를 검증해 최종 시간 결과 dict로 변환합니다.

    후보 밖의 시간이나 선택 정보가 없는 final_slot은 확정하지 않고,
    final_slot=null 및 needs_agent_selection=true로 반환합니다.
    """

    normalized_candidates = [_slot_as_jsonable(slot) for slot in candidate_slots or []]
    candidate_texts = {slot_to_text(slot) for slot in normalized_candidates}

    # 선택 정보(selected_slot·selected_index)는 final_slot이 후보 안에 있든 없든 똑같이 검사한다.
    # 이 파일 맨 위 구현 가이드가 "selected_index나 selected_slot이 없으면 final_slot을 자동으로
    # 고르지 말고 needs_agent_selection=True 상태를 유지합니다"라고 요구하는데, 그 조건은
    # final_slot이 어떻게 들어왔는지와 무관하기 때문이다.
    # selected_slot은 자유 형식 dict라 후보와 대조된 적이 없는데 decide_final_slot_payload가
    # selected_index보다 먼저 쓴다. 그래서 후보에 없으면 여기서 지운다.
    if selected_slot is not None and slot_to_text(_slot_as_jsonable(selected_slot)) not in candidate_texts:
        selected_slot = None
    # selected_index는 normalized_candidates 안만 가리킬 수 있을 때만 남긴다.
    try:
        index_in_range = 0 <= int(selected_index) < len(normalized_candidates)
    except (TypeError, ValueError):
        index_in_range = False
    # 번호를 주긴 했는데 쓸 수 없는 경우를 따로 기억한다. 값을 지우면 "선택 정보가 없었다"와
    # "잘못된 번호를 보냈다"를 구분할 수 없고, 두 경우에 Kana가 받을 안내가 달라진다.
    unusable_index = selected_index is not None and not index_in_range
    if not index_in_range:
        selected_index = None

    final_slot_outside_candidates = final_slot is not None and final_slot not in candidate_texts
    if final_slot_outside_candidates:
        # 후보 목록에 없는 final_slot 문자열은 버린다. 다만 "몇 번째 후보"라는 선택 정보까지 같이
        # 버리지는 않는다 — fixed/schedule_decision.py의 decide_final_slot_payload가 그 선택 정보로
        # final_slot을 후보 안에서 다시 만들어 준다.
        final_slot = None
        if selected_slot is None and selected_index is None:
            reason = "입력한 final_slot이 후보 목록에 없어 최종 확정하지 않았습니다."

    # 위 가이드대로, 쓸 수 있는 선택 정보가 하나도 없으면 확정하지 않는다. 이때 final_slot도 같이 비운다.
    # 값을 남기면 "유효한 final_slot + needs_agent_selection=true"라는 모순된 결과가 나가는데,
    # DECIDE_FINAL_SLOT_DESCRIPTION과 DecideFinalSlotInput이 둘 다 "미확정이면 final_slot=null"을
    # 계약으로 적고 있어 서로 어긋난다. 그러면 supervisor가 final_slot만 보고 확정했다고 답할 수 있다.
    if selected_slot is None and selected_index is None:
        needs_agent_selection = True
        if final_slot is not None:
            final_slot = None
            reason = "후보 지목(selected_index/selected_slot)이 없어 최종 확정하지 않았습니다."
        if unusable_index and not final_slot_outside_candidates:
            # 번호를 지운 뒤라 fixed/schedule_decision.py는 "번호가 범위를 벗어났다"를 더 이상
            # 말할 수 없다. 그 진단을 여기서 대신 적는다. 고칠 방법까지 적어야 Kana가 다시 부른다.
            # final_slot까지 후보 밖이면 그쪽 문구를 남긴다 — 먼저 고쳐야 할 것이 그것이다.
            # final_slot은 위에서 이미 비웠으므로 여기서는 reason만 갈아 끼운다.
            reason = (
                f"selected_index가 후보 목록 범위를 벗어났습니다. "
                f"후보 번호는 0부터 {len(normalized_candidates) - 1}까지입니다."
                if normalized_candidates
                else "selected_index를 받았지만 candidate_slots가 비어 있어 가리킬 후보가 없습니다."
            )
    else:
        # 쓸 수 있는 선택 정보가 있으면 agent가 보낸 needs_agent_selection을 그대로 믿지 않고 None으로
        # 지운다. fixed/schedule_decision.py의 decide_final_slot_payload는 이 값이 None일 때만
        # "final_slot이 비었나"를 보고 직접 정해 주기 때문이다. 그대로 넘기면 Kana가
        # needs_agent_selection=true를 함께 보냈을 때 확정된 final_slot과 "선택이 더 필요하다"가
        # 같이 나가, DecideFinalSlotInput의 needs_agent_selection 설명이 적은
        # "final_slot을 확정했으면 false" 계약과 어긋난다.
        needs_agent_selection = None
    payload = decide_final_slot_payload(
        candidate_slots=normalized_candidates,
        selected_slot=_slot_as_jsonable(selected_slot),
        selected_index=selected_index,
        member_names=member_names,
        date_from=date_from,
        date_to=date_to,
        duration_minutes=duration_minutes,
        final_slot=final_slot,
        needs_agent_selection=needs_agent_selection,
        reason=reason,
        busy_rows=busy_rows,
    )
    return json.dumps(payload, ensure_ascii=False)


def kana_tools() -> list[Any]:
    return [
        extract_schedule_request,
        search_previous_conversations,
        load_conversation_messages,
        extract_schedules_from_history,
        list_shared_schedules,
        collect_member_schedules,
        find_common_available_slots,
        decide_final_slot,
    ]


def supervisor_tools() -> list[Any]:
    return [nana_agent, kana_agent]


def agent_tool_names(agent_name: str) -> list[str]:
    if agent_name == "nana_agent":
        return [tool_name(item) for item in week04_tools()]
    if agent_name == "kana_agent":
        return [tool_name(item) for item in kana_tools()]
    if agent_name == "supervisor":
        return [tool_name(item) for item in supervisor_tools()]
    return []


@tool(args_schema=ProposeGroupScheduleInput)
def propose_group_schedule(
    title: str,
    member_names: list[str],
    candidate_slots: list[Any] | None = None,
    selected_slot: Any | None = None,
    reason: str | None = None,
) -> str:
    """Kana가 고른 후보 시간으로 최종 그룹 일정 결정 페이로드를 만듭니다."""

    slots = [slot.model_dump() if hasattr(slot, "model_dump") else slot for slot in candidate_slots or []]
    selected = selected_slot.model_dump() if hasattr(selected_slot, "model_dump") else selected_slot
    payload = {
        "title": title,
        "members": normalize_external_member_names(member_names),
        "selected_slot": selected,
        "status": "confirmed" if selected else "needs_manual_review",
        "reason": reason,
        "candidate_slots": slots,
    }
    return json.dumps({"ok": True, "tool_name": "propose_group_schedule", "final_decision": payload}, ensure_ascii=False)


def _subagent_failure_payload(selected_agent: str, label: str, exc: Exception) -> dict[str, Any]:
    """하위 agent를 만들거나 부르다 실패했을 때 supervisor에게 돌려줄 결과 dict입니다.

    실패 사실을 새 키가 아니라 기존 answer 칸에 담는다. 새 키를 만들면 supervisor 프롬프트에
    "그 키도 읽어라"를 따로 적어 줘야 답변까지 닿는다. answer는 supervisor가 이미 읽는 자리라
    프롬프트를 건드리지 않고도 닿는다.
    문장 틀은 fixed/week_agent_registry.py가 같은 상황에 쓰는 규격을 따르되, label에는 내부 이름
    대신 사용자가 쓰는 말을 넘긴다 — supervisor는 하위 결과의 answer를 자기 말로 다시 쓰는데,
    "kana_agent" 같은 내부 이름은 사용자에게 옮길 말로 치지 않아 "무언가 문제가 생겼습니다"로
    뭉개 버린다.
    """

    return {
        "selected_agent": selected_agent,
        "answer": f"{label} 위임 처리 중 오류가 발생했습니다: {type(exc).__name__}: {exc}",
        "trace": [],
        "inner_tool_names": [],
        "final_slot_payload": None,
        "final_decision_payload": None,
    }


@tool(args_schema=AgentQueryInput)
def nana_agent(query: str) -> str:
    """개인 일정과 개인 RAG 작업을 프롬프트 기반 Nana 하위 에이전트에게 위임합니다."""

    global _NANA_SUBAGENT
    # 만들기와 부르기만 감싼다. 이 둘이 밖(모델 서버)과 말하는 구간이라 터질 수 있다.
    # 아래에서 결과를 꺼내 조립하는 함수들은 isinstance로 모양을 먼저 확인하므로,
    # 예상 밖의 값이 와도 예외를 내지 않고 건너뛴다.
    try:
        if _NANA_SUBAGENT is None:
            _NANA_SUBAGENT = create_agent(
                model=chat_model(),
                tools=week04_tools(),
                system_prompt=nana_system_prompt(),
            )
        result = _NANA_SUBAGENT.invoke({"messages": [{"role": "user", "content": query}]})
    except Exception as exc:
        return json.dumps(
            _subagent_failure_payload("nana_agent", "개인 일정(Nana)", exc), ensure_ascii=False
        )

    events = extract_agent_events(result)
    payload = {
        "selected_agent": "nana_agent",
        "answer": extract_final_text(result),
        "trace": events,
        "inner_tool_names": _tool_call_names(events),
        "final_slot_payload": None,
        "final_decision_payload": None,
    }
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=AgentQueryInput)
def kana_agent(query: str) -> str:
    """그룹 일정 종합 작업을 프롬프트 기반 Kana 하위 에이전트에게 위임합니다."""

    global _KANA_SUBAGENT
    try:
        if _KANA_SUBAGENT is None:
            _KANA_SUBAGENT = create_agent(
                model=chat_model(),
                tools=kana_tools(),
                system_prompt=kana_system_prompt(),
            )
        result = _KANA_SUBAGENT.invoke({"messages": [{"role": "user", "content": query}]})
    except Exception as exc:
        payload = _subagent_failure_payload("kana_agent", "그룹 일정 조율(Kana)", exc)
        # 성공 결과에만 있는 두 키도 같은 모양으로 채워 supervisor가 읽는 키 집합을 유지한다.
        payload["roster"] = None
        payload["external_lookup"] = None
        return json.dumps(payload, ensure_ascii=False)

    events = extract_agent_events(result)
    trace_payloads = _kana_trace_payloads(events)

    payload = {
        # 아래 멤버 명단·외부 조회 상태는 하위 실행 기록 안쪽에도 들어 있지만, 여기 최상위에 한 번 더
        # 올려 둔다. 안쪽에만 두면 supervisor가 trace를 파고들지 않아 그 경고를 답변에 못 싣는다.
        "selected_agent": "kana_agent",
        "answer": extract_final_text(result),
        "trace": events,
        "inner_tool_names": _tool_call_names(events),
        "final_slot_payload": trace_payloads["final_slot_payload"],
        "final_decision_payload": trace_payloads["final_decision_payload"],
        "roster": trace_payloads["roster"],
        "external_lookup": trace_payloads["external_lookup"],
    }
    return json.dumps(payload, ensure_ascii=False)


def build_langchain_supervisor_agent() -> object:
    """nana_agent와 kana_agent 위임 도구만 노출하는 LangChain v1 슈퍼바이저입니다."""

    global _SUPERVISOR_AGENT
    if _SUPERVISOR_AGENT is None:
        _SUPERVISOR_AGENT = create_agent(
            model=chat_model(),
            tools=supervisor_tools(),
            system_prompt=supervisor_system_prompt(),
        )
    return _SUPERVISOR_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_langchain_supervisor_agent()
