from __future__ import annotations

import json
import re
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from fixed.external_people_store import normalize_external_member_names
from fixed.langchain_trace import extract_agent_events, extract_final_text, stream_chunk_messages
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.schedule_decision import (
    CommonSlotCandidate,
    decide_final_slot_payload,
    find_common_available_slots_payload,
    normalize_date_bound,
)
from student_parts.week01_wake_up_nana import join_system_prompt
from student_parts.week02_structure_natural_language_requests import extract_schedule_request
from student_parts.week04_retrieve_nanas_memory import week04_prompt_parts, week04_tools
from student_parts.week05_load_kanas_past_conversations import (
    collect_member_schedules,
    extract_schedules_from_history,
    list_shared_schedules,
    load_conversation_messages,
    search_previous_conversations,
    week05_prompt_parts,
)


_NANA_SUBAGENT: Any | None = None
_KANA_SUBAGENT: Any | None = None
_SUPERVISOR_AGENT: Any | None = None


# [6주차 수강생 구현 가이드]
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
#   - 공통 가능 시간 검증/최종 선택 payload 생성은 fixed/schedule_decision.py의
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
#      - 하위 trace를 훑어 decide_final_slot 결과를 final_slot_payload로 끌어올립니다.
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
#      - find_common_available_slots는 busy-time row를 Python 룰이나 nested LLM으로 훑지 않고,
#        Kana agent가 tool description을 읽고 직접 고른 candidate_slots payload를 검증/기록합니다.
#      - date_from/date_to에 ISO datetime이 들어오면 normalize_date_bound()로 날짜 부분만 사용합니다.
#      - busy_rows가 None이면 collect_member_schedules를 호출해 내 일정과 외부 멤버 busy-time을 모읍니다.
#      - decide_final_slot도 nested LLM을 만들지 않고 Kana agent가 넘긴 final_slot, selected_index,
#        needs_agent_selection, reason payload를 그대로 course repo JSON 계약에 맞춰 기록합니다.
#      - 반환 JSON은 course repo 기준 top-level final_slot, reason, candidates를 반드시 포함합니다.
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
#   find_common_available_slots/decide_final_slot의 실제 겹침 검증과 payload 정리는 fixed/schedule_decision.py가 맡습니다.
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
#     supervisor 실행 결과를 events, 선택된 하위 agent, 내부 tool 이름, 최종 시간 payload가 포함된 trace dict로 정리합니다.
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
#     실제 후보 검증 payload 생성은 fixed/schedule_decision.py의 find_common_available_slots_payload(...)가 맡습니다.
#
#   - [추가] find_common_available_slots(...)
#     Kana agent가 직접 고른 candidate_slots가 busy_rows와 겹치지 않는지 검증하고 JSON 문자열로 반환하는 tool입니다.
#
#   - [추가] decide_final_slot(...)
#     Kana agent가 직접 고른 selected_index/final_slot/reason을 course repo 계약에 맞는 최종 payload로 기록합니다.
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
        """
        현재 실행 범위는 Week 6이며, 아래 역할 분담은 이전 주차의 단일 agent 범위와
        이전 prompt에 남아 있는 Nana 정체성 문구보다 우선한다.
        너는 실제 일정 업무를 직접 처리하지 않는 supervisor다.
        개인 일정 생성·조회·수정·삭제, todo/reminder 저장, 개인 참고자료, 저장 기록,
        앱 내부 대화 RAG 요청은 nana_agent에 위임한다.
        외부 멤버의 과거 대화·일정·공유 일정 조회, 나와 외부 멤버 일정 비교,
        공통 가능 시간 검증과 그룹 최종 시간 결정은 kana_agent에 위임한다.
        사용자 요청 하나에는 담당 agent 하나만 선택하고, 선택하지 않은 agent를 예비로 호출하지 않는다.
        직접 내부 tool을 호출하거나 일정 결과를 추측해서 만들지 않는다.
        """,
    ]


def nana_prompt_parts() -> list[str]:
    """Week 6 Nana 하위 에이전트 전용 system prompt 조각입니다."""

    return [
        *week04_prompt_parts(),
        """
        현재 너는 Week 6의 Nana 하위 에이전트다.
        개인 일정 생성·조회·수정·삭제, todo/reminder 저장, 개인 참고자료 저장·검색,
        저장 기록 검색과 앱 내부 과거 대화 RAG만 담당한다.
        실제 저장·조회·수정·삭제 요청은 대화 기억만으로 답하지 말고 반드시 알맞은 tool 결과를 근거로 답한다.
        외부 멤버의 일정 조회와 그룹 공통 시간 결정은 담당하지 않는다.
        그런 요청이 들어오면 tool을 호출하지 말고 Kana 담당이라고 한국어로 짧게 안내한다.

        개인 일정 생성 요청은 필수 값이 모두 있으면 extract_schedule_request 다음
        personal_create_schedule을 같은 실행에서 호출한다. todo/reminder 저장도
        extract_schedule_request 다음 save_structured_request까지 완료한다.
        todo는 제목과 날짜만 명확해도 저장하며 start_time/end_time을 요구하지 않는다.
        reminder는 사용자가 명시한 날짜·시각을 사용하고 종료 시각을 추가로 묻지 않는다.
        개인 일정 수정·삭제는 personal_list_saved_schedules로 실제 schedule_id를 확인한 뒤
        각각 personal_update_saved_schedule 또는 personal_delete_saved_schedules를 호출한다.
        후보가 없을 때만 변경 tool을 호출하지 않고 없다고 답한다.
        생성·저장·수정·삭제 mutation tool의 결과를 받기 전에는 완료됐다는 최종 답변을
        절대 만들지 않는다. 구조화나 후보 조회 결과만으로 workflow를 끝내지 않는다.

        '앱에 저장된 요청 기록' 검색은 search_saved_requests, '앱의 이전 일반 대화' 검색은
        search_conversation_messages를 반드시 사용한다. 앱 내부 일반 대화는 Nana 담당이며
        외부 멤버의 대화가 아니므로 Kana 담당이라고 돌려보내지 않는다.
        특히 요청에 '앱의 이전 일반 대화' 또는 '이전 일반 대화'가 있으면
        search_conversation_messages만 사용하고 search_personal_references로 바꾸지 않는다.
        사용자가 앞서 개인 참고자료에 저장한 식별 코드·선호·규칙을 "찾아줘"라고 하면
        일정 제목으로 해석하지 말고 search_personal_references를 호출한다.
        """,
    ]


def kana_prompt_parts() -> list[str]:
    """Week 6 Kana 하위 에이전트 전용 system prompt 조각입니다."""

    return [
        f"""
        너는 Week 6의 외부 일정 및 그룹 조율 담당 하위 에이전트 Kana다.
        사용자에게는 한국어로 간결하고 친절하게 답한다.
        현재 앱 기준 날짜는 {current_app_date_iso()}다. 상대 날짜는 이 날짜를 기준으로 해석하고
        날짜는 YYYY-MM-DD, 시간은 HH:MM 형식을 사용한다.

        외부 조회 또는 그룹 조율 전에 외부 member_names와 date_from/date_to가 명확한지 확인한다.
        멤버나 날짜 범위가 없으면 값을 추측하거나 tool을 호출하지 말고 필요한 정보만 질문한다.
        필요한 값이 모두 있고 사용자가 조회·비교·시간 결정을 요청했다면 별도의 조회 허락을
        다시 묻지 말고 즉시 알맞은 tool workflow를 실행한다.

        외부 멤버 일정만 조회할 때는 search_previous_conversations를 먼저 호출하고,
        검색 rows가 비어 있어도 extract_schedules_from_history를 이어서 호출한다.
        사용자가 원문 근거를 요청했고 추출 rows가 있을 때만 실제 source_conversation_id로
        load_conversation_messages를 호출한다. 공유 일정 row 조회에는 list_shared_schedules를 사용한다.

        나와 외부 멤버의 일정을 함께 비교하거나 공통 시간을 정할 때는
        collect_member_schedules 하나로 내 일정과 외부 busy-time을 모으고 search/extract를 중복 호출하지 않는다.
        외부 멤버들만의 공통 시간을 정하면서 search/extract로 rows를 얻었다면 그 rows를 busy_rows로 사용한다.
        find_common_available_slots의 member_names에는 외부 멤버만 넣는다. 이 tool은 결과의
        검증 대상 members에 "나"를 한 번만 자동으로 포함한다.

        그룹 시간 결정에서는 busy_rows를 직접 읽고 어떤 busy row와도 겹치지 않는 candidate_slots를
        네가 직접 고른다. find_common_available_slots가 후보를 계산해 준다고 기대하지 않는다.
        후보 검증 결과만 말하고 끝내지 말고, 유효한 후보 중 하나를 네가 직접 선택해
        selected_index 또는 selected_slot과 final_slot을 채운 뒤 decide_final_slot을 호출한다.
        final_slot 형식은 'YYYY-MM-DD HH:MM-HH:MM'이다.
        후보가 없거나 선택할 수 없으면 final_slot=null, needs_agent_selection=true로 두고 임의 확정하지 않는다.
        확정했다면 needs_agent_selection=false로 두며 후보·busy_rows·멤버·날짜 범위·reason을 함께 전달한다.
        find_common_available_slots를 호출할 때 candidate_slots를 반드시 list로 전달한다.
        사용자가 '10시부터 11시 사이', '10:00부터 11:00 사이'처럼 허용 시간 범위를
        명시했다면 그 시작과 끝을 workday_start/workday_end로 정확히 전달한다. 기본값
        09:00~18:00로 넓히거나 범위 밖 후보를 만들지 않는다.
        공통 후보가 없으면 빈 list를 전달하고, find 결과가 빈 list여도 decide_final_slot을
        반드시 이어서 호출해 final_slot=null, needs_agent_selection=true로 기록한다.
        후보의 시작·종료 간격은 요청 duration_minutes와 정확히 같아야 한다. 최종 확정 시
        final_slot은 selected_slot 또는 selected_index가 가리키는 후보의 날짜·시작·종료와 정확히 같아야 한다.
        앞선 조회 tool의 rows는 busy_rows에 그대로 복사한다. member_name의 공백을 바꾸거나
        notes, source_conversation_id 같은 필드를 생략하지 말고 find와 decide 양쪽에 같은 rows를 전달한다.

        개인 일정 생성·수정·삭제와 확정 일정의 실제 저장은 Nana 담당이다.
        그런 요청에는 개인 저장 tool을 대신 실행하지 말고 Nana 담당이라고 안내한다.
        """,
    ]


def nana_system_prompt() -> str:
    return join_system_prompt(nana_prompt_parts())


def kana_system_prompt() -> str:
    return join_system_prompt(kana_prompt_parts())


def supervisor_system_prompt() -> str:
    return join_system_prompt(
        [
            *week06_prompt_parts(),
            """
            일정 관련 사용자 요청에는 반드시 nana_agent 또는 kana_agent 중 담당 하나를 정확히 한 번 호출한다.
            사용자의 멤버·날짜·의도를 query에 보존하고 사용자가 말하지 않은 값이나 결정을 추가하지 않는다.
            query를 검색 키워드만 남긴 짧은 구로 축약하지 않는다. 저장 기록 검색, 앱 내부 대화 검색,
            생성·수정·삭제 같은 작업 의도를 하위 agent가 알 수 있게 원문 표현을 보존한다.
            후속 답변만으로 멤버·날짜·회의 길이가 완성되는 경우에는 앞선 대화의 미완성 요청과 합쳐
            하위 agent가 단독으로 이해할 수 있는 query를 만든다.
            하위 agent를 호출하지 않은 채 직접 완료 답변을 만들지 않는다.
            하위 agent가 반환한 answer와 payload만 근거로 답하고, JSON 전체를 그대로 노출하지 말고
            사용자에게 필요한 내용을 간결한 한국어로 정리한다.
            """,
        ]
    )


def _tool_call_names(events: list[dict[str, Any]]) -> list[str]:
    return [event["tool_name"] for event in events if event.get("event") == "tool_call" and event.get("tool_name")]


def extract_langchain_trace(result: dict[str, Any]) -> dict[str, Any]:
    """Week 6 supervisor 실행 결과를 UI trace payload로 변환합니다."""

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
            if content.get("final_slot_payload"):
                final_slot_payload = content["final_slot_payload"]
            elif "final_slot" in content:
                final_slot_payload = content
            if content.get("final_decision_payload"):
                final_decision_payload = content["final_decision_payload"]

    trace = {
        "events": events,
        "supervisor_selected_agent": selected_agent,
        "inner_tool_names": inner_tool_names,
        "final_slot_payload": final_slot_payload,
        "final_decision_payload": final_decision_payload,
    }
    if isinstance(result, dict) and "supervisor_retry_count" in result:
        trace["supervisor_retry_count"] = result["supervisor_retry_count"]
    return trace


def tool_name(tool_object: Any) -> str:
    return getattr(tool_object, "name", getattr(tool_object, "__name__", str(tool_object)))


FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION = (
    "공통 가능 시간 후보를 검증하고 기록합니다. 이 Python tool은 빈 시간을 계산하거나 후보를 대신 "
    "선택하지 않습니다. Kana agent가 앞선 일정 조회 결과의 busy_rows를 직접 읽고, 어떤 busy row와도 "
    "겹치지 않는 candidate_slots를 직접 골라 busy_rows와 함께 전달해야 합니다. 각 후보는 "
    "date(YYYY-MM-DD), start_time(HH:MM), end_time(HH:MM), duration_minutes, reason을 모두 포함해야 하며 "
    "요청 날짜 범위, 업무시간, 회의 길이를 만족해야 합니다. 사용자가 명시한 'HH:MM부터 HH:MM 사이'는 "
    "workday_start/workday_end에 그대로 넣고 절대로 기본 09:00~18:00로 넓히지 않습니다. "
    "반환된 검증 결과로 답변을 끝내지 말고 "
    "유효한 후보를 직접 선택한 다음 decide_final_slot을 이어서 호출하세요."
)


DECIDE_FINAL_SLOT_DESCRIPTION = (
    "검증된 후보 중 Kana agent가 직접 고른 최종 시간을 기록합니다. 이 Python tool은 후보나 최종 시간을 "
    "자동 선택하지 않습니다. 확정할 때는 selected_index 또는 selected_slot을 직접 고르고 final_slot을 "
    "'YYYY-MM-DD HH:MM-HH:MM' 형식으로 채우며 needs_agent_selection=false와 사용자-facing reason을 "
    "전달하세요. 아직 고르지 못했다면 final_slot=null, needs_agent_selection=true로 두세요. 판단 근거가 "
    "trace에 남도록 바로 앞 find_common_available_slots 결과의 candidate_slots, busy_rows, members를 "
    "각각 candidate_slots, busy_rows, member_names에 값과 순서를 바꾸지 않고 복사하고 date_from, date_to도 "
    "함께 전달해야 합니다. find 결과에 자동 포함된 '나'를 member_names에서 빼면 안 됩니다."
)


class FindCommonAvailableSlotsInput(BaseModel):
    member_names: list[str] = Field(description="공통 가능 시간을 찾아야 하는 외부 멤버 이름 목록")
    date_from: str = Field(description="조회 시작 날짜. ISO datetime이면 날짜 부분만 사용")
    date_to: str = Field(description="조회 종료 날짜. ISO datetime이면 날짜 부분만 사용")
    duration_minutes: int = Field(default=60, ge=30, le=480, description="회의 길이(분)")
    workday_start: str = Field(
        default="09:00",
        description="허용 업무 시간 시작 HH:MM. 사용자가 시간 범위를 명시하면 그 시작 시각을 사용",
    )
    workday_end: str = Field(
        default="18:00",
        description="허용 업무 시간 종료 HH:MM. 사용자가 시간 범위를 명시하면 그 종료 시각을 사용",
    )
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
    candidate_slots: list[Any] = Field(
        default_factory=list,
        description="find_common_available_slots 결과에서 값과 순서를 바꾸지 않고 복사한 candidate_slots",
    )
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
    member_names: list[str] | None = Field(
        default=None,
        description="find_common_available_slots 결과의 members를 '나'까지 포함해 그대로 복사한 목록",
    )
    date_from: str | None = Field(default=None, description="요청 날짜 범위 시작")
    date_to: str | None = Field(default=None, description="요청 날짜 범위 종료")
    duration_minutes: int = Field(default=60, description="회의 길이(분)")
    reason: str | None = Field(default=None, description="최종 선택 또는 보류에 대한 사용자-facing 설명")
    busy_rows: list[dict[str, Any]] | None = Field(
        default=None,
        description="find_common_available_slots 결과에서 필드와 순서를 바꾸지 않고 복사한 busy_rows",
    )


class ProposeGroupScheduleInput(BaseModel):
    """기존 호환용 그룹 일정 제안 입력입니다."""

    title: str
    member_names: list[str]
    candidate_slots: list[CommonSlotCandidate] = Field(default_factory=list)
    selected_slot: CommonSlotCandidate | None = None
    reason: str | None = None


class AgentQueryInput(BaseModel):
    """하위 에이전트 위임 입력입니다."""

    query: str = Field(
        description=(
            "하위 agent가 이 문자열 하나만 읽어도 실행할 수 있는 완결된 요청. 멤버·날짜·시간·작업 의도를 "
            "원문에서 보존하고, clarification 후속 답변이면 앞선 미완성 요청과 합쳐 전달"
        )
    )


def find_common_available_slots_dict(
    member_names: list[str],
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
    """멤버별 busy-time rows와 LLM이 고른 후보 payload를 검증 결과로 바꿉니다."""

    normalized_member_names = normalize_external_member_names(member_names)
    external_member_names: list[str] = []
    for name in normalized_member_names:
        if name != "나" and name not in external_member_names:
            external_member_names.append(name)

    normalized_date_from = normalize_date_bound(date_from)
    normalized_date_to = normalize_date_bound(date_to)
    collected_busy_rows = busy_rows
    if collected_busy_rows is None:
        collected_payload = json.loads(
            collect_member_schedules.invoke(
                {
                    "member_names": external_member_names,
                    "date_from": normalized_date_from,
                    "date_to": normalized_date_to,
                }
            )
        )
        if not isinstance(collected_payload, dict):
            raise ValueError("collect_member_schedules 결과는 JSON object여야 합니다.")
        if collected_payload.get("ok") is False:
            raise RuntimeError(
                str(collected_payload.get("error") or "collect_member_schedules failed")
            )
        collected_busy_rows = list(collected_payload.get("rows") or [])

    return find_common_available_slots_payload(
        member_names=["나", *external_member_names],
        date_from=normalized_date_from,
        date_to=normalized_date_to,
        busy_rows=collected_busy_rows,
        duration_minutes=duration_minutes,
        workday_start=workday_start,
        workday_end=workday_end,
        limit=limit,
        candidate_slots=candidate_slots,
        llm_reason=llm_reason,
    )


@tool(description=FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION, args_schema=FindCommonAvailableSlotsInput)
def find_common_available_slots(
    member_names: list[str],
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
    """수집된 멤버 일정에서 LLM이 직접 고른 공통 가능 후보 시간을 검증합니다."""

    payload = find_common_available_slots_dict(
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
    )
    return json.dumps(payload, ensure_ascii=False)


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
    """LLM이 직접 고른 후보/최종 시간을 course repo payload로 기록합니다."""

    payload = decide_final_slot_payload(
        candidate_slots=candidate_slots,
        selected_slot=selected_slot,
        selected_index=selected_index,
        final_slot=final_slot,
        needs_agent_selection=needs_agent_selection,
        member_names=member_names,
        date_from=date_from,
        date_to=date_to,
        duration_minutes=duration_minutes,
        reason=reason,
        busy_rows=busy_rows,
    )
    # 빈 후보 목록도 "후보가 없었다"는 결정 근거이므로 key 자체를 보존합니다.
    payload["candidate_slots"] = list(candidate_slots or [])
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


_EXPLICIT_DATE_PATTERN = re.compile(r"(?:\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{4}-\d{1,2}-\d{1,2})")
_TIME_RANGE_PATTERN = re.compile(
    r"(?:\d{1,2}(?::\d{2}|시)(?:\s*\d{1,2}분)?).*?부터.*?"
    r"(?:\d{1,2}(?::\d{2}|시)(?:\s*\d{1,2}분)?).*?까지"
)
_EXPLICIT_WINDOW_PATTERN = re.compile(
    r"(?<![\d:+-])(?P<start_hour>[01]?\d|2[0-3])"
    r"(?::(?P<start_minute>[0-5]\d)|시(?:\s*(?P<start_korean_minute>[0-5]?\d)분)?)"
    r"\s*부터\s*"
    r"(?P<end_hour>[01]?\d|2[0-3])"
    r"(?::(?P<end_minute>[0-5]\d)|시(?:\s*(?P<end_korean_minute>[0-5]?\d)분)?)"
    r"\s*(?:사이|까지)"
)


def _nana_mutation_retry_plan(query: str) -> tuple[str, tuple[str, ...]] | None:
    """명시 필드가 충분한 Nana mutation 요청만 보수적으로 재시도 대상으로 분류합니다."""

    normalized = " ".join(str(query).split())
    has_date = _EXPLICIT_DATE_PATTERN.search(normalized) is not None
    has_time_range = _TIME_RANGE_PATTERN.search(normalized) is not None
    if not has_date:
        return None
    if any(word in normalized for word in ("삭제", "지워", "제거")):
        return (
            "personal_delete_saved_schedules",
            ("personal_list_saved_schedules", "personal_delete_saved_schedules"),
        )
    if any(word in normalized for word in ("수정", "변경", "옮겨", "바꿔")) and has_time_range:
        return (
            "personal_update_saved_schedule",
            ("personal_list_saved_schedules", "personal_update_saved_schedule"),
        )
    if "할 일" in normalized or "할일" in normalized or "알림" in normalized or "리마인더" in normalized:
        if any(word in normalized for word in ("저장", "등록", "추가", "기억")):
            return (
                "save_structured_request",
                ("extract_schedule_request", "save_structured_request"),
            )
    is_personal_create = (
        any(word in normalized for word in ("내 일정", "개인 일정"))
        and any(word in normalized for word in ("등록", "저장", "추가", "생성", "잡아"))
        and has_time_range
        and "참고자료" not in normalized
    )
    if is_personal_create:
        return (
            "personal_create_schedule",
            ("extract_schedule_request", "personal_create_schedule"),
        )
    return None


def _nana_read_retry_tool(query: str) -> str | None:
    """명시적인 Nana RAG 출처 요청을 읽기 전용 교정 재시도 대상으로 분류합니다."""

    normalized = " ".join(str(query).split())
    if any(word in normalized for word in ("기억해", "저장해", "등록해", "추가해")):
        return None
    if any(phrase in normalized for phrase in ("앱의 이전 일반 대화", "이전 일반 대화")):
        return "search_conversation_messages"
    if "저장된 요청" in normalized or "저장 기록" in normalized:
        return "search_saved_requests"
    if "참고자료" in normalized or "식별 코드" in normalized:
        return "search_personal_references"
    return None


def _retry_tool_evidence(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """재시도에 넘길 앞선 tool 결과만 JSON 직렬화 가능한 형태로 보존합니다."""

    return [
        {"tool_name": event.get("tool_name"), "content": event.get("content")}
        for event in events
        if event.get("event") == "tool_result" and event.get("tool_name")
    ]


def _last_tool_result(events: list[dict[str, Any]], tool: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event") == "tool_result" and event.get("tool_name") == tool:
            content = event.get("content")
            return content if isinstance(content, dict) else None
    return None


def _last_tool_arguments(events: list[dict[str, Any]], tool: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event") == "tool_call" and event.get("tool_name") == tool:
            arguments = event.get("arguments")
            return arguments if isinstance(arguments, dict) else None
    return None


def _remaining_sequence(sequence: tuple[str, ...], events: list[dict[str, Any]]) -> tuple[str, ...]:
    observed = {
        str(event.get("tool_name"))
        for event in events
        if event.get("event") == "tool_result"
        and event.get("tool_name")
        and (not isinstance(event.get("content"), dict) or event["content"].get("ok") is not False)
    }
    remaining = tuple(name for name in sequence if name not in observed)
    return remaining or sequence[-1:]


def _tools_named(tools: list[Any], names: tuple[str, ...]) -> list[Any]:
    by_name = {tool_name(item): item for item in tools}
    return [by_name[name] for name in names if name in by_name]


def _nana_retry_agent(tool_names: tuple[str, ...]) -> Any:
    """교정 시도에서는 남은 Nana 단계 외의 도구를 노출하지 않습니다."""

    return create_agent(
        model=chat_model(),
        tools=_tools_named(week04_tools(), tool_names),
        system_prompt=(
            "너는 Nana workflow의 누락된 단계만 한 번 수행하는 교정 agent다. 사용자 메시지에 적힌 "
            "원래 요청과 앞선 tool 결과를 읽고, 제공된 tool을 명시된 순서대로 반드시 호출한다. "
            "todo는 날짜와 제목만 있어도 저장할 수 있고 시작·종료 시각은 선택 값이다. reminder는 사용자가 "
            "말한 날짜·시각을 사용하며 말하지 않은 선택 값은 None 또는 빈 목록으로 둔다. "
            "extract_schedule_request는 얇은 첫 단계이므로 None 필드를 필수 값 누락으로 오해하지 말고 원래 "
            "사용자 요청에서 kind, title, date, start_time을 직접 읽어 최종 저장 tool 인자로 채운다. "
            "제공된 마지막 tool의 결과를 받기 전에는 질문하거나 자연어 최종 답변을 만들지 않는다."
        ),
    )


def _kana_retry_agent(tool_names: tuple[str, ...]) -> Any:
    """교정 시도에서는 필요한 Kana 완료 단계만 노출합니다."""

    return create_agent(
        model=chat_model(),
        tools=_tools_named(kana_tools(), tool_names),
        system_prompt=(
            kana_system_prompt()
            + "\n이번 실행은 누락되거나 잘못 전달된 workflow를 한 번 교정하는 실행이다. 앞선 tool 결과를 "
            "그대로 이어받고 제공된 남은 tool 결과 전에는 자연어 최종 답변을 만들지 않는다."
        ),
    )


def _explicit_time_window(query: str) -> tuple[str, str] | None:
    match = _EXPLICIT_WINDOW_PATTERN.search(" ".join(str(query).split()))
    if match is None:
        return None

    def as_time(hour_name: str, minute_name: str, korean_minute_name: str) -> str:
        hour = int(match.group(hour_name))
        minute = int(match.group(minute_name) or match.group(korean_minute_name) or 0)
        return f"{hour:02d}:{minute:02d}"

    return (
        as_time("start_hour", "start_minute", "start_korean_minute"),
        as_time("end_hour", "end_minute", "end_korean_minute"),
    )


def _kana_decision_retry_reason(query: str, events: list[dict[str, Any]]) -> str | None:
    """Kana 최종 결정이 앞선 검증 결과와 사용자 범위를 보존했는지 확인합니다."""

    find_result = _last_tool_result(events, "find_common_available_slots")
    decide_result = _last_tool_result(events, "decide_final_slot")
    if find_result is None:
        return "find_common_available_slots 결과 누락"
    if decide_result is None:
        return "decide_final_slot 결과 누락"

    for source_key, decision_key in (
        ("members", "members"),
        ("busy_rows", "busy_rows"),
        ("candidate_slots", "candidate_slots"),
    ):
        if find_result.get(source_key) != decide_result.get(decision_key):
            return f"find 결과의 {source_key}가 decide 결과에 보존되지 않음"

    explicit_window = _explicit_time_window(query)
    if explicit_window is not None:
        find_arguments = _last_tool_arguments(events, "find_common_available_slots") or {}
        if (
            find_arguments.get("workday_start") != explicit_window[0]
            or find_arguments.get("workday_end") != explicit_window[1]
        ):
            return "사용자 명시 허용 시간 범위 불일치"
    return None


def _known_empty_schedule_lookup(events: list[dict[str, Any]]) -> bool:
    """수정·삭제 선행 조회가 성공했고 후보가 명확히 비었는지 확인합니다."""

    for event in reversed(events):
        if event.get("event") != "tool_result" or event.get("tool_name") != "personal_list_saved_schedules":
            continue
        content = event.get("content")
        return isinstance(content, dict) and content.get("ok") is not False and content.get("schedules") == []
    return False


def _nana_retry_instruction(
    query: str,
    sequence: tuple[str, ...],
    events: list[dict[str, Any]],
) -> str:
    sequence_text = " -> ".join(sequence)
    evidence = json.dumps(_retry_tool_evidence(events), ensure_ascii=False)
    return (
        f"원래 사용자 요청:\n{query}\n\n"
        f"앞선 tool 결과(JSON):\n{evidence}\n\n"
        "이전 실행이 필요한 mutation tool 결과 없이 종료되었습니다. 앞선 결과를 그대로 이어받아 같은 요청을 "
        f"한 번만 다시 수행하세요. 이번 실행에서 아직 남은 필수 단계는 {sequence_text}입니다. "
        "이미 완료된 단계를 불필요하게 반복하지 말고 남은 단계를 순서대로 끝까지 실행한 뒤, 마지막 mutation "
        "tool의 성공 결과를 받은 뒤에만 완료 답변을 만드세요. 필수 값이 실제로 부족하면 추측하거나 "
        "mutation하지 말고 부족한 값만 질문하세요."
    )


def _nana_read_retry_instruction(query: str, expected_tool: str) -> str:
    return (
        f"원래 사용자 요청:\n{query}\n\n"
        "이전 실행이 요청에 명시된 검색 출처와 다른 tool을 사용했거나 검색 tool 없이 종료되었습니다. "
        f"이 요청은 읽기 전용이므로 {expected_tool}을 정확히 한 번 호출해 결과를 받은 뒤 그 결과만으로 답하세요."
    )


def _kana_required_terminal_tool(query: str) -> str | None:
    """필수 입력이 명확한 Kana 비교·결정 요청의 완료 tool을 판별합니다."""

    normalized = " ".join(str(query).split())
    has_date = _EXPLICIT_DATE_PATTERN.search(normalized) is not None
    has_named_participants = (
        re.search(r"나와\s*\S+", normalized) is not None
        or re.search(r"\S+와\s+\S+가", normalized) is not None
    )
    if not has_date or not has_named_participants:
        return None
    if "시간 결정은 하지 마" in normalized or "일정을 비교" in normalized:
        return "collect_member_schedules"
    if "회의" in normalized and any(word in normalized for word in ("최종", "정해", "결정")):
        return "decide_final_slot"
    return None


def _kana_retry_instruction(
    query: str,
    terminal_tool: str,
    events: list[dict[str, Any]],
) -> str:
    if terminal_tool == "collect_member_schedules":
        workflow = "collect_member_schedules를 호출해 비교 결과를 받은 뒤 답하세요. 시간 결정 tool은 호출하지 마세요."
    else:
        find_result = _last_tool_result(events, "find_common_available_slots")
        explicit_window = _explicit_time_window(query)
        find_arguments = _last_tool_arguments(events, "find_common_available_slots") or {}
        window_mismatch = explicit_window is not None and (
            find_arguments.get("workday_start") != explicit_window[0]
            or find_arguments.get("workday_end") != explicit_window[1]
        )
        if find_result is not None and not window_mismatch:
            workflow = (
                "앞선 find_common_available_slots를 다시 호출하지 말고 그 결과의 members, busy_rows, "
                "candidate_slots를 정확히 복사해 decide_final_slot만 호출하세요. 후보가 없으면 빈 list와 "
                "final_slot=null, needs_agent_selection=true로 호출하세요."
            )
        else:
            workflow = (
                "알맞은 일정 조회 결과를 busy_rows로 그대로 보존하고 candidate_slots list를 직접 만든 뒤 "
                "find_common_available_slots -> decide_final_slot까지 끝내세요. 후보가 없더라도 빈 list와 "
                "final_slot=null, needs_agent_selection=true로 decide_final_slot을 반드시 호출하세요."
            )
    evidence = json.dumps(_retry_tool_evidence(events), ensure_ascii=False)
    explicit_window = _explicit_time_window(query)
    window_instruction = ""
    if explicit_window is not None:
        window_instruction = (
            f" 사용자 명시 허용 시간은 {explicit_window[0]}부터 {explicit_window[1]}까지이므로 "
            f"find_common_available_slots의 workday_start={explicit_window[0]}, "
            f"workday_end={explicit_window[1]}로 고정하고 범위 밖 후보를 만들지 마세요."
        )
    return (
        f"원래 사용자 요청:\n{query}\n\n"
        f"앞선 tool 결과(JSON):\n{evidence}\n\n"
        "이전 실행이 Kana workflow의 필수 완료 단계 전에 종료되었습니다. 앞선 tool 결과의 rows, 후보, 멤버를 "
        "생략하거나 고쳐 쓰지 말고 그대로 이어받아 같은 요청을 안전하게 한 번만 다시 수행하세요. "
        + workflow
        + window_instruction
    )


@tool(args_schema=AgentQueryInput)
def nana_agent(query: str) -> str:
    """개인 일정과 개인 RAG 작업을 self-contained query로 Nana에게 위임합니다.

    query에는 원래 멤버·날짜·시간·생성/수정/삭제/검색 의도를 보존합니다. 명시 필드가
    충분한 mutation 요청이 mutation tool 없이 끝나면, 이미 mutation이 실행되지 않았고
    조회 후보가 명확히 빈 경우도 아닐 때에만 교정 지시로 안전하게 한 번 재시도합니다.
    """

    global _NANA_SUBAGENT
    if _NANA_SUBAGENT is None:
        _NANA_SUBAGENT = create_agent(
            model=chat_model(),
            tools=week04_tools(),
            system_prompt=nana_system_prompt(),
        )

    result = _NANA_SUBAGENT.invoke(
        {"messages": [{"role": "user", "content": query}]}
    )
    events = extract_agent_events(result)
    retry_count = 0
    effective_events = events
    retry_plan = _nana_mutation_retry_plan(query)
    if retry_plan is not None:
        mutation_tool, required_sequence = retry_plan
        observed_tools = {
            event.get("tool_name")
            for event in events
            if event.get("event") == "tool_result"
            and (not isinstance(event.get("content"), dict) or event["content"].get("ok") is not False)
        }
        lookup_is_empty = (
            mutation_tool in {"personal_update_saved_schedule", "personal_delete_saved_schedules"}
            and _known_empty_schedule_lookup(events)
        )
        if mutation_tool not in observed_tools and not lookup_is_empty:
            retry_count = 1
            remaining_sequence = _remaining_sequence(required_sequence, events)
            retry_result = _nana_retry_agent(remaining_sequence).invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": _nana_retry_instruction(query, remaining_sequence, events),
                        }
                    ]
                }
            )
            retry_events = extract_agent_events(retry_result)
            events = [*events, *retry_events]
            effective_events = events
            result = retry_result
    else:
        expected_read_tool = _nana_read_retry_tool(query)
        if expected_read_tool is not None and expected_read_tool not in _tool_call_names(events):
            retry_count = 1
            retry_result = _nana_retry_agent((expected_read_tool,)).invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": _nana_read_retry_instruction(query, expected_read_tool),
                        }
                    ]
                }
            )
            retry_events = extract_agent_events(retry_result)
            events = [*events, *retry_events]
            # 잘못 선택한 첫 읽기 전용 검색은 상태를 바꾸지 않으며 교정 결과로 대체됩니다.
            # 전체 시도는 trace/attempted_inner_tool_names에 남기되 계약 검증은 교정 시도를 봅니다.
            effective_events = retry_events
            result = retry_result
    payload = {
        "selected_agent": "nana_agent",
        "answer": extract_final_text(result),
        "trace": events,
        "inner_tool_names": _tool_call_names(effective_events),
        "attempted_inner_tool_names": _tool_call_names(events),
        "retry_count": retry_count,
    }
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=AgentQueryInput)
def kana_agent(query: str) -> str:
    """외부 멤버 일정과 그룹 조율을 self-contained query로 Kana에게 위임합니다.

    query에는 외부 멤버·날짜 범위·회의 길이·조회/비교/최종 결정 의도를 보존합니다.
    Supervisor는 외부 일정이나 그룹 조율을 직접 답하지 말고 이 wrapper를 호출합니다.
    """

    global _KANA_SUBAGENT
    if _KANA_SUBAGENT is None:
        _KANA_SUBAGENT = create_agent(
            model=chat_model(),
            tools=kana_tools(),
            system_prompt=kana_system_prompt(),
        )

    result = _KANA_SUBAGENT.invoke(
        {"messages": [{"role": "user", "content": query}]}
    )
    events = extract_agent_events(result)
    retry_count = 0
    terminal_tool = _kana_required_terminal_tool(query)
    retry_reason: str | None = None
    if terminal_tool == "decide_final_slot":
        retry_reason = _kana_decision_retry_reason(query, events)
    elif terminal_tool is not None and terminal_tool not in _tool_call_names(events):
        retry_reason = f"{terminal_tool} 호출 누락"
    if retry_reason is not None:
        retry_count = 1
        if terminal_tool == "collect_member_schedules":
            retry_tools = ("collect_member_schedules",)
        else:
            find_result = _last_tool_result(events, "find_common_available_slots")
            explicit_window = _explicit_time_window(query)
            find_arguments = _last_tool_arguments(events, "find_common_available_slots") or {}
            window_mismatch = explicit_window is not None and (
                find_arguments.get("workday_start") != explicit_window[0]
                or find_arguments.get("workday_end") != explicit_window[1]
            )
            if find_result is not None and not window_mismatch:
                retry_tools = ("decide_final_slot",)
            elif any(
                _last_tool_result(events, source_tool) is not None
                for source_tool in ("collect_member_schedules", "extract_schedules_from_history")
            ):
                retry_tools = ("find_common_available_slots", "decide_final_slot")
            else:
                retry_tools = (
                    "collect_member_schedules",
                    "find_common_available_slots",
                    "decide_final_slot",
                )
        retry_result = _kana_retry_agent(retry_tools).invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"교정 사유: {retry_reason}\n\n"
                            + _kana_retry_instruction(query, terminal_tool, events)
                        ),
                    }
                ]
            }
        )
        events = [*events, *extract_agent_events(retry_result)]
        result = retry_result
    final_slot_payload: dict[str, Any] | None = None
    final_decision_payload: dict[str, Any] | None = None
    for event in events:
        content = event.get("content")
        if not isinstance(content, dict):
            continue
        if event.get("tool_name") == "decide_final_slot" and "final_slot" in content:
            final_slot_payload = content
        if isinstance(content.get("final_decision"), dict):
            final_decision_payload = content["final_decision"]

    payload = {
        "selected_agent": "kana_agent",
        "answer": extract_final_text(result),
        "trace": events,
        "inner_tool_names": _tool_call_names(events),
        "final_slot_payload": final_slot_payload,
        "final_decision_payload": final_decision_payload,
        "retry_count": retry_count,
    }
    return json.dumps(payload, ensure_ascii=False)


_SUPERVISOR_REQUEST_KEYWORDS = (
    "일정",
    "회의",
    "할 일",
    "할일",
    "알림",
    "리마인더",
    "참고자료",
    "저장된 요청",
    "이전 일반 대화",
    "공유",
    "바쁜",
)


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _requires_supervisor_delegation(messages: list[Any]) -> bool:
    """일정·저장·RAG 범위 요청에만 Supervisor wrapper 재시도를 허용합니다."""

    last_user_text = ""
    for message in reversed(messages):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "type", None)
        if role in {"user", "human"}:
            last_user_text = _message_text(message)
            break
    return any(keyword in last_user_text for keyword in _SUPERVISOR_REQUEST_KEYWORDS)


def _supervisor_wrapper_observed(result: dict[str, Any]) -> bool:
    return any(
        event.get("tool_name") in {"nana_agent", "kana_agent"}
        for event in extract_agent_events(result)
        if event.get("event") in {"tool_call", "tool_result"}
    )


class Week06SupervisorRetryAgent:
    """wrapper 미호출만 안전하게 한 번 교정하는 Week 6 invoke adapter입니다."""

    def __init__(self, agent: Any):
        self._agent = agent

    def invoke(self, payload: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = self._agent.invoke(payload, *args, **kwargs)
        messages = list(payload.get("messages") or [])
        if _supervisor_wrapper_observed(result) or not _requires_supervisor_delegation(messages):
            if isinstance(result, dict):
                result["supervisor_retry_count"] = 0
            return result

        retry_payload = dict(payload)
        retry_payload["messages"] = [
            *messages,
            {
                "role": "user",
                "content": (
                    "직전 일정·저장·RAG 요청을 Supervisor가 직접 답하지 마세요. 역할 경계에 따라 "
                    "nana_agent 또는 kana_agent 중 담당 wrapper 하나를 정확히 한 번 호출하세요. "
                    "wrapper query는 직전 사용자 요청의 멤버·날짜·시간·작업 의도를 모두 보존한 "
                    "self-contained 요청이어야 합니다."
                ),
            },
        ]
        retry_result = self._agent.invoke(retry_payload, *args, **kwargs)
        if isinstance(retry_result, dict):
            retry_result["supervisor_retry_count"] = 1
        return retry_result

    def stream(self, payload: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        """stream에서도 wrapper 미호출을 확인한 뒤 안전하게 한 번만 재시도합니다."""

        collected_messages: list[Any] = []
        for chunk in self._agent.stream(payload, *args, **kwargs):
            collected_messages.extend(stream_chunk_messages(chunk))
            yield chunk

        messages = list(payload.get("messages") or [])
        first_result = {"messages": collected_messages}
        if _supervisor_wrapper_observed(first_result) or not _requires_supervisor_delegation(messages):
            return

        retry_payload = dict(payload)
        retry_payload["messages"] = [
            *messages,
            {
                "role": "user",
                "content": (
                    "직전 일정·저장·RAG 요청을 Supervisor가 직접 답하지 마세요. 역할 경계에 따라 "
                    "nana_agent 또는 kana_agent 중 담당 wrapper 하나를 정확히 한 번 호출하세요. "
                    "wrapper query는 직전 사용자 요청의 모든 조건을 보존한 self-contained 요청이어야 합니다."
                ),
            },
        ]
        yield from self._agent.stream(retry_payload, *args, **kwargs)


def build_langchain_supervisor_agent() -> object:
    """nana_agent와 kana_agent 위임 도구만 노출하는 LangChain v1 슈퍼바이저입니다."""

    global _SUPERVISOR_AGENT
    if _SUPERVISOR_AGENT is None:
        _SUPERVISOR_AGENT = Week06SupervisorRetryAgent(
            create_agent(
                model=chat_model(),
                tools=supervisor_tools(),
                system_prompt=supervisor_system_prompt(),
            )
        )
    return _SUPERVISOR_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_langchain_supervisor_agent()
