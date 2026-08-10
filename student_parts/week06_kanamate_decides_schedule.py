from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from fixed.external_people_store import PERSONAL_SHARED_MEMBER_NAME, normalize_external_member_names
from fixed.langchain_trace import extract_agent_events, extract_final_text
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


WEEK06_DELEGATION_PROMPT = (
    # supervisor가 직접 처리하지 않고 하위 agent를 고르는 기준을 정한다.
    "[Week 6 위임] 너는 supervisor이고, 직접 호출할 수 있는 tool은 nana_agent와 kana_agent 두 개뿐이다. "
    "앞선 주차 지시에 나오는 tool 이름은 모두 하위 agent가 가진 tool이므로 직접 호출하지 않고, "
    "어느 하위 agent에 위임할지 판단하는 근거로만 사용한다.\n"
    "  1) nana_agent(query) 담당: 내 개인 일정 생성·조회·수정·삭제, 할 일과 알림 저장, "
    "내가 적어 둔 개인 참고자료 검색, 앱 안에서 나눈 대화 기록 검색.\n"
    "  2) kana_agent(query) 담당: 다른 사람의 이전 대화 검색, 다른 사람의 일정 조회, "
    "공유 일정 저장소 row 조회, 내 일정과 다른 사람 일정을 함께 모으는 작업, "
    "여러 사람이 모두 비어 있는 시간 후보를 고르고 최종 회의 시간을 결정하는 작업.\n"
    "위임 기준은 요청에 다른 사람 이름이 나오는지가 아니라, "
    "다른 사람의 일정이나 대화 데이터를 읽어야 하는지다. "
    "다른 사람 데이터를 읽지 않고 처리할 수 있으면 nana_agent에 위임한다. "
    "다른 사람의 일정이나 대화를 조회해야 하면 kana_agent에 위임한다. "
    "날짜와 시작 시간이 모두 정해져 있어 조회 없이 저장만 하면 되는 요청은 "
    "참석자에 다른 사람 이름이 있어도 nana_agent 담당이다. "
    "날짜만 정해져 있고 시간을 정해야 하는 요청은 다른 사람의 일정을 읽어야 하므로 kana_agent 담당이다. "
    "'다들', '팀원들'처럼 이름을 적지 않아도 여러 사람이 가능한 시간을 알아야 하는 요청은 "
    "다른 사람 데이터를 읽어야 하므로 kana_agent 담당이다. "
    "두 담당이 모두 필요한 요청은 kana_agent로 외부 정보를 먼저 확보한 뒤 nana_agent로 저장을 위임한다. "
    "하위 agent가 자기 담당이 아니라고 답하면 같은 agent를 다시 호출하지 않고 다른 하위 agent에 위임한다."
)

WEEK06_SUBAGENT_QUERY_PROMPT = (
    # 하위 agent가 대화 이력을 보지 못하니 query에 어떤 값을 넣어야 하는지 지정한다.
    "[Week 6 query 작성] 하위 agent는 이 대화의 이전 메시지도 supervisor 지시도 보지 못하고 "
    "query 문자열 하나만 받는다. "
    "그러므로 query에는 원래 요청 문장과 함께 대상 사람 이름, 날짜, 시간, 일정 제목처럼 "
    "작업에 필요한 값을 빠짐없이 적는다. "
    "사용자가 '다음 주'처럼 상대적인 기간을 말했으면 query에는 YYYY-MM-DD 형식으로 바꿔 적는다. "
    "'그거', '아까 말한 일정'처럼 이전 메시지를 가리키는 표현은 query에 그대로 넣지 않고, "
    "이전 메시지에서 확인한 실제 값으로 바꿔 적는다. "
    "값이 부족해 보여도 위임 전에 사용자에게 되묻지 않고, 대화에서 확인한 값까지만 담아 위임한다. "
    "어떤 값이 더 필요한지는 하위 agent가 답변으로 알린다."
)

WEEK06_SUPERVISOR_EXECUTION_PROMPT = (
    # 위임 결과만 근거로 답하게 하는 실행 규칙이다.
    "[Week 6 실행] 어떤 요청이든 nana_agent 또는 kana_agent를 최소 한 번 호출한 뒤에 답한다. "
    "tool을 호출하지 않고 추측으로 답하지 않는다. "
    "하위 agent는 JSON 문자열을 반환하고, 그 안의 answer가 사용자에게 전달할 내용이다. "
    "answer에 없는 날짜·시간·일정을 덧붙이지 않는다. "
    "trace와 inner_tool_names는 어떤 tool이 실행됐는지 확인하는 근거이므로 사용자 답변에 옮기지 않는다. "
    "answer가 값이 부족해 작업을 끝내지 못했다고 알리면, 그 값을 사용자에게 묻고 "
    "답을 받은 뒤 같은 하위 agent에 다시 위임한다. 사용자 답을 받기 전에 값을 임의로 정하지 않는다. "
    "위임 결과가 JSON이 아닌 오류 메시지이거나 answer가 비어 있으면 위임한 작업이 끝나지 않았다는 "
    "뜻이므로, 무엇이 처리되지 않았는지 사용자에게 알린다."
)

WEEK06_NANA_ROLE_PROMPT = (
    # Nana 하위 agent가 담당하는 범위와 담당 밖 요청의 처리 방식을 적는다.
    "[Week 6 Nana 역할] 너는 supervisor가 개인 업무를 위임할 때 실행되는 하위 agent다. "
    "담당 범위는 내 개인 일정 생성·조회·수정·삭제, 할 일과 알림 저장, "
    "내가 적어 둔 개인 참고자료 검색, 앱 안에서 나눈 대화 기록 검색이다. "
    "다른 사람의 이전 대화, 다른 사람의 일정, 공유 일정 저장소 조회, "
    "여러 사람이 모두 가능한 시간을 찾는 작업은 Kana 담당이다. "
    "그런 요청을 받으면 tool을 호출하지 않고 Kana 담당이라는 사실만 한 문장으로 답한다. "
    "너는 사용자와 직접 대화하지 않고 query 문자열 하나만 받으므로 되묻지 않는다. "
    "값이 부족해 작업을 끝낼 수 없으면 무엇이 필요한지 답변에 적는다. "
    "답변은 supervisor가 사용자에게 그대로 전달할 수 있는 문장으로 쓰고, "
    "tool 결과에 없는 내용을 추측해서 넣지 않는다."
)

WEEK06_KANA_ROLE_PROMPT = (
    # Kana 하위 agent는 누적 조각이 없어 역할과 답변 규칙을 처음부터 세운다.
    "[Week 6 Kana 역할] 너는 supervisor가 외부 멤버 관련 업무를 위임할 때 실행되는 하위 agent다. "
    "담당 범위는 다른 사람의 이전 대화 검색, 다른 사람의 일정 조회, 공유 일정 저장소 row 조회, "
    "내 일정과 다른 사람 일정을 함께 모아 바쁜 시간과 비어 있는 시간을 설명하는 작업, "
    "그리고 여러 사람이 모두 비어 있는 시간 후보를 고르고 최종 회의 시간을 결정하는 작업이다. "
    "내 개인 일정을 새로 만들거나 수정·삭제하는 것, 할 일과 알림을 저장하는 것, "
    "개인 참고자료를 검색하는 것은 Nana 담당이다. "
    "그런 요청을 받으면 tool을 호출하지 않고 Nana 담당이라는 사실만 한 문장으로 답한다. "
    "너는 사용자와 직접 대화하지 않고 query 문자열 하나만 받으므로 되묻지 않는다. "
    "값이 부족해 조회를 끝낼 수 없으면 무엇이 필요한지 답변에 적는다. "
    "답변은 supervisor가 사용자에게 그대로 전달할 수 있는 문장으로 쓴다."
)

WEEK06_KANA_TOOL_PROMPT = (
    # Kana가 가진 tool을 어떤 기준으로 고르고 결과를 어떻게 해석할지 명시한다.
    "[Week 6 Kana tool 사용] 다른 사람의 이전 대화와 일정은 앱 데이터베이스가 아니라 외부 저장소에 있고, "
    "외부 저장소는 MCP tool로만 조회할 수 있다.\n"
    "  1) extract_schedule_request(query): 요청 문장에서 날짜·시간·대상을 구조화해야 할 때 사용한다.\n"
    "  2) search_previous_conversations(query, member_names, limit): 어떤 대화가 있었는지 찾을 때 사용하고, "
    "query에는 문장 전체가 아니라 짧은 핵심 명사나 구를 넣는다.\n"
    "  3) load_conversation_messages(conversation_id): 찾은 대화의 전체 내용이 필요할 때만 사용한다.\n"
    "  4) extract_schedules_from_history(member_names, date_from, date_to): "
    "다른 사람이 언제 바쁜지만 알면 될 때 대화 전문을 읽지 않고 일정 row를 바로 받는다.\n"
    "  5) list_shared_schedules(member_names, date_from, date_to, ...): "
    "공유 일정 저장소에 어떤 row가 등록되어 있는지 확인할 때만 사용하고 member_names를 반드시 지정한다. "
    "조건을 모두 비워 두면 실습용 기본 일정만 조회되고 내 일정은 결과에 포함되지 않는다.\n"
    "  6) collect_member_schedules(member_names, date_from, date_to): "
    "내 일정과 다른 사람 일정을 함께 모아야 하는 요청은 이 tool 한 번으로 처리한다. "
    "이 tool이 내부에서 외부 일정 조회까지 수행하므로 extract_schedules_from_history를 따로 다시 호출하지 않는다.\n"
    "  7) find_common_available_slots(member_names, date_from, date_to, busy_rows, candidate_slots, ...): "
    "여러 사람이 모두 비어 있는 회의 시간을 찾아야 할 때 사용한다. "
    "6)의 rows를 busy_rows에 그대로 넘기고, 그 rows와 겹치지 않는 시간을 직접 골라 candidate_slots에 넣는다.\n"
    "  8) decide_final_slot(candidate_slots, selected_index, final_slot, needs_agent_selection, reason, ...): "
    "7)이 검증한 후보 중 하나를 최종 회의 시간으로 확정할 때 사용한다. "
    "7)을 호출하지 않고 이 tool을 먼저 호출하지 않는다.\n"
    "MCP tool 호출은 한 번에 수 초가 걸리므로 같은 조회를 반복하지 않는다. "
    "일정을 설명할 때는 tool 결과의 rows와 schedule_summary만 근거로 삼고, "
    "rows에 없는 날짜나 시간을 추측해서 답변에 넣지 않는다. "
    "tool 결과의 unknown_end_time_count가 0보다 크면 종료 시간이 확정되지 않은 일정이 있다는 뜻이므로, "
    "unknown_end_time_rows에 담긴 일정은 겹침 여부를 판단하지 않고 "
    "종료 시간 확인이 필요하다는 사실을 답변에 적는다. "
    "tool 결과의 errors 항목이 비어 있지 않으면 조회하지 못한 대상이 있다는 뜻이므로, "
    "확보한 rows로 답하면서 어떤 조회가 실패했는지 함께 알린다. "
    "회의 시간을 정해 달라는 요청은 6) → 7) → 8) 순서로 호출해 최종 시간까지 확정한 뒤 답한다. "
    "8)의 반환값에서 needs_agent_selection이 true이면 확정하지 못했다는 뜻이므로 "
    "확정했다고 말하지 않고 reason에 적힌 이유를 답변에 옮긴다. "
    "최종 시간을 확정해도 그 시간을 내 개인 일정으로 저장하는 것은 Nana 담당이므로 "
    "저장했다고 말하지 않는다."
)


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

    """누적 조각이 supervisor의 tool 목록과 어긋나는 문제와 처리 방식.

    1. 누적 조각은 supervisor에게 없는 tool을 지시한다.
       week05_prompt_parts()에는 personal_create_schedule이나 collect_member_schedules를
       직접 호출하라는 지시가 들어 있다. supervisor_tools()가 노출하는 tool은
       nana_agent와 kana_agent 둘뿐이다. 그 지시는 그대로 실행할 수 없다.

    2. 조각을 제거하지 않고 뒤 조각에서 용도를 바꾼다.
       join_system_prompt는 뒤에 오는 지시를 우선한다고 안내하므로
       WEEK06_DELEGATION_PROMPT가 앞선 tool 이름을 위임 대상 판단 근거로 다시 정의한다.
       누적 조각을 지우면 어떤 tool이 어느 하위 agent에 있는지 판단할 근거도 없어진다.

    3. 마지막 조각에는 실행 시점 값이 들어간다.
       current_app_date_iso()는 호출 시점의 앱 기준 날짜를 반환한다. 상수로 둘 수 없으므로
       이 함수 안에서 문자열을 만든다.
    """
    return [
        *week05_prompt_parts(),
        WEEK06_DELEGATION_PROMPT,
        WEEK06_SUBAGENT_QUERY_PROMPT,
        (
            f"오늘 날짜는 {current_app_date_iso()}이다. 이번 주(Week 6)의 범위는 "
            "한 agent가 모두 처리하던 일을 Nana와 Kana 하위 agent로 나누어 위임하는 것이다. "
            "supervisor는 일정 조회나 저장을 직접 수행하지 않고 담당 하위 agent를 고르는 판단만 한다."
        ),
    ]


def nana_prompt_parts() -> list[str]:
    """Week 6 Nana 하위 에이전트 전용 system prompt 조각입니다."""

    """week04 조각을 그대로 누적하고 역할 조각만 덧붙이는 이유.

    1. 누적 범위가 Nana의 tool 목록과 일치한다.
       nana_agent가 하위 agent에 넘기는 tool은 week04_tools()다.
       week04_prompt_parts()는 그 tool들의 사용 기준을 담는다. supervisor와 달리
       지시와 tool 목록이 어긋나지 않으므로 용도를 바꾸는 조각은 필요 없다.

    2. 하위 agent에서만 성립하는 조건을 추가한다.
       WEEK06_NANA_ROLE_PROMPT는 담당 범위를 정하고 사용자에게 되물을 수 없다는
       실행 조건도 넣는다. 두 조건 모두 단일 agent였던 Week 4에는 없었다.
    """
    return [
        *week04_prompt_parts(),
        WEEK06_NANA_ROLE_PROMPT,
    ]


def kana_prompt_parts() -> list[str]:
    """Week 6 Kana 하위 에이전트 전용 system prompt 조각입니다."""

    """누적 조각이 없어 다시 적어야 하는 내용.

    1. tool 사용 기준을 이 조각에서 다시 정한다.
       kana_tools()의 tool 8개 중 6개는 Week 2·5에서 만들었지만
       week05_prompt_parts()를 누적하지 않아 호출 기준이 전달되지 않는다.
       WEEK06_KANA_TOOL_PROMPT가 그 기준을 Kana 담당 범위에 맞춰 다시 정의한다.

    2. 기준 날짜도 다시 넣는다.
       상대 기간 표현을 날짜로 바꾸려면 기준 날짜가 필요하다. 누적 조각에서 오지
       않으니 current_app_date_iso()를 이 함수에서 직접 넣는다.

    3. 추가 과제 tool 2개는 호출 순서를 함께 적는다.
       find_common_available_slots와 decide_final_slot은 각 tool의 description에도
       호출 조건이 있지만, description은 그 tool 하나의 계약만 말한다.
       collect_member_schedules → find_common_available_slots → decide_final_slot으로
       이어지는 순서는 tool 세 개에 걸쳐 있으므로 prompt에서 정한다.
    """
    return [
        WEEK06_KANA_ROLE_PROMPT,
        WEEK06_KANA_TOOL_PROMPT,
        (
            f"오늘 날짜는 {current_app_date_iso()}이다. "
            "query에 '다음 주'처럼 상대적인 기간 표현이 남아 있으면 이 날짜를 기준으로 "
            "YYYY-MM-DD 범위로 바꿔 tool 인자에 넣는다."
        ),
    ]


def nana_system_prompt() -> str:
    return join_system_prompt(nana_prompt_parts())


def kana_system_prompt() -> str:
    return join_system_prompt(kana_prompt_parts())


def supervisor_system_prompt() -> str:
    """supervisor system prompt를 파트 순서대로 합칩니다."""

    """되묻기 시점을 두 파트가 다르게 지시하던 문제와 처리 방식.

    1. 파트 순서는 뒤에 오는 지시가 우선한다.
       join_system_prompt가 붙이는 header에 "더 뒤에 있는 지시를 우선한다"가 있다.
       이 함수가 만드는 순서는 (1) week05_prompt_parts(), (2) WEEK06_DELEGATION_PROMPT,
       (3) WEEK06_SUBAGENT_QUERY_PROMPT, (4) 기준 날짜 파트,
       (5) WEEK06_SUPERVISOR_EXECUTION_PROMPT다.

    2. 두 파트가 되묻기 시점을 다르게 지시했다.
       (3)은 값이 부족하면 위임 전에 사용자에게 확인하라고 했고,
       (5)는 어떤 요청이든 하위 agent를 최소 한 번 호출한 뒤에 답하라고 했다.
       (3)을 따르면 tool 호출 없이 답하게 되어 (5)를 위반한다.

    3. 뒤 파트인 (5)를 기준으로 (3)을 맞췄다.
       supervisor는 하위 agent에 어떤 값이 필요한지 모른다. AgentQueryInput의 필드는
       query 하나뿐이라 tool 스키마로도 알 수 없다. 그래서 (3)에서 위임 전 되묻기를
       빼고, 값이 부족하다는 판단은 하위 agent 답변으로 받아 (5)에서 사용자에게
       확인한 뒤 다시 위임하도록 옮겼다.
    """
    return join_system_prompt(
        [
            *week06_prompt_parts(),
            WEEK06_SUPERVISOR_EXECUTION_PROMPT,
        ]
    )


def _tool_call_names(events: list[dict[str, Any]]) -> list[str]:
    return [event["tool_name"] for event in events if event.get("event") == "tool_call" and event.get("tool_name")]


def _final_payloads_from_events(
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """하위 agent trace에서 최종 시간 payload와 최종 결정 payload를 찾습니다."""

    """두 값을 wrapper 반환 상위 키로 올리는 이유와 판정 기준.

    1. supervisor는 하위 agent의 tool 결과를 직접 보지 못한다.
       supervisor가 읽는 것은 wrapper가 반환한 문자열뿐이다. extract_langchain_trace(...)도
       wrapper 반환 JSON의 final_slot_payload / final_decision_payload 키를 읽는다.
       중첩된 trace 안에 남겨 두면 UI trace의 해당 항목이 비어 있다.

    2. tool 이름이 아니라 키 존재로 판정한다.
       decide_final_slot_payload(...)의 반환값은 final_slot 키를 항상 포함한다.
       propose_group_schedule은 final_decision 키에 payload를 담는다. 키를 기준으로
       판정하면 어느 tool이 호출됐는지에 따라 분기하지 않아도 된다.

    3. 마지막 값을 남긴다.
       같은 tool이 여러 번 호출되면 뒤에 나온 결과가 최종 판단이므로 덮어쓴다.
    """
    final_slot_payload: dict[str, Any] | None = None
    final_decision_payload: dict[str, Any] | None = None
    for event in events:
        if event.get("event") != "tool_result":
            continue
        content = event.get("content")
        if not isinstance(content, dict):
            continue
        if "final_slot" in content:
            final_slot_payload = content
        if content.get("final_decision"):
            final_decision_payload = content["final_decision"]
    return final_slot_payload, final_decision_payload


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
    # description이 Kana agent가 이 tool의 호출 조건과 인자 형식을 판단하는 유일한 근거다.
    "여러 사람이 모두 비어 있는 회의 시간 후보를 검증해 기록한다. "
    "이 tool은 후보를 계산하지 않는다. busy_rows를 읽고 겹치지 않는 시간을 고르는 것은 네가 하고, "
    "이 tool은 네가 고른 candidate_slots가 실제로 busy_rows와 겹치지 않는지만 확인한다. "
    "호출 전에 collect_member_schedules로 대상 멤버의 일정을 먼저 조회한다. "
    "busy_rows에는 그 결과의 rows를 그대로 복사해 넘긴다. "
    "busy_rows를 넘기지 않으면 이 tool이 같은 조회를 다시 수행하므로 수 초가 더 걸린다. "
    "candidate_slots의 각 항목에는 date('YYYY-MM-DD'), start_time('HH:MM'), end_time('HH:MM'), "
    "duration_minutes(정수 분), reason(그 시간을 고른 짧은 근거)을 모두 넣는다. "
    "후보는 date_from부터 date_to 사이의 날짜여야 하고, workday_start와 workday_end 사이에 있어야 하며, "
    "어떤 busy row와도 겹치면 안 된다. 조건을 어긴 후보는 반환값의 candidate_slots에서 제외된다. "
    "busy row의 시작 시간이 '미정'이면 00:00부터, 종료 시간이 '미정'이면 24:00까지 "
    "차지하는 것으로 계산되므로 그 시간대의 후보는 제외된다. "
    "반환값의 candidate_slots가 비어 있으면 다른 시간을 골라 이 tool을 한 번 더 호출한다. "
    "이 tool의 결과만으로 답변을 끝내지 않는다. 후보를 확보했으면 이어서 decide_final_slot을 호출한다."
)


DECIDE_FINAL_SLOT_DESCRIPTION = (
    # description이 Kana agent가 이 tool의 호출 조건과 인자 형식을 판단하는 유일한 근거다.
    "그룹 회의의 최종 시간 결정을 기록한다. find_common_available_slots를 호출한 뒤에만 호출한다. "
    "이 tool은 최종 시간을 고르지 않는다. 후보 중 하나를 고르는 것은 네가 하고, "
    "이 tool은 네가 고른 결과를 최종 payload로 기록한다. "
    "candidate_slots에는 find_common_available_slots 반환값의 candidate_slots를 그대로 복사해 넘긴다. "
    "고른 후보는 selected_index(candidate_slots에서 0부터 세는 번호)로 지정하고, "
    "final_slot에는 'YYYY-MM-DD HH:MM-HH:MM' 형식 문자열을 적고 needs_agent_selection은 false로 둔다. "
    "후보가 하나도 없거나 아직 고르지 못했으면 final_slot은 null, needs_agent_selection은 true로 두고 "
    "reason에 확정하지 못한 이유를 적는다. 값을 채우려고 후보를 지어내지 않는다. "
    "reason은 사용자에게 그대로 전달되므로 그 시간을 고른 근거를 한 문장으로 적는다. "
    "member_names, date_from, date_to, duration_minutes, busy_rows는 결정 근거로 함께 기록되므로 "
    "앞선 tool 호출에서 사용한 값을 그대로 넘긴다."
)


class FindCommonAvailableSlotsInput(BaseModel):
    member_names: list[str] = Field(description="공통 가능 시간을 찾아야 하는 외부 멤버 이름 목록")
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

    """busy_rows를 인자로 받으면서도 직접 수집하는 경로를 함께 두는 이유.

    1. 인자로 받은 busy_rows를 우선한다.
       Kana agent는 이 tool을 호출하기 전에 collect_member_schedules를 호출한다.
       그 결과의 rows를 그대로 넘기면 같은 조회를 반복하지 않는다. MCP 호출 1회는
       서버 subprocess를 새로 기동하므로 수 초가 걸린다.

    2. None일 때만 직접 수집한다.
       agent가 rows를 넘기지 않으면 검증 기준이 없어 모든 후보가 통과한다.
       겹침 검증을 하지 않은 결과를 검증한 결과처럼 반환하지 않도록, 이 경우에는
       collect_member_schedules를 호출해 rows를 채운다. 빈 list는 조회 결과가
       비어 있다는 값이므로 다시 수집하지 않는다.

    3. payload의 members에는 "나"를 포함한다.
       collect_member_schedules는 인자에 "나"가 없어도 내 일정 row를 항상 포함한다.
       busy_rows에 내 일정이 들어 있으므로, 후보 판정 근거가 된 대상 목록에도
       "나"를 넣어야 payload의 members와 busy_rows가 같은 범위를 가리킨다.
    """
    members = normalize_external_member_names(member_names)
    normalized_date_from = normalize_date_bound(date_from)
    normalized_date_to = normalize_date_bound(date_to)

    rows = busy_rows
    if rows is None:
        collected = json.loads(
            collect_member_schedules.invoke(
                {
                    "member_names": members,
                    "date_from": normalized_date_from,
                    "date_to": normalized_date_to,
                }
            )
        )
        rows = collected.get("rows") or []

    members_with_me = (
        members if PERSONAL_SHARED_MEMBER_NAME in members else [PERSONAL_SHARED_MEMBER_NAME, *members]
    )
    return find_common_available_slots_payload(
        member_names=members_with_me,
        date_from=normalized_date_from,
        date_to=normalized_date_to,
        busy_rows=rows,
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

    """tool 본문을 find_common_available_slots_dict와 분리해 둔 이유.

    tool 반환 타입은 문자열이라 dict를 그대로 반환할 수 없다. 검증 로직을
    find_common_available_slots_dict에 두면 LangChain tool 호출 없이도 같은 함수를
    직접 호출해 반환 dict를 확인할 수 있다.
    """
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

    """인자를 그대로 넘기고 반환값을 감싸지 않는 이유.

    1. 최종 시간 선택은 이 함수에서 하지 않는다.
       후보 중 무엇을 고를지는 Kana agent가 tool description을 읽고 판단한다.
       여기서 selected_index가 비어 있을 때 첫 후보를 대신 고르는 식으로 보완하면
       description이 말하는 계약과 실제 동작이 달라진다. 인자를 그대로
       decide_final_slot_payload(...)에 넘기고 판정은 그 함수에 맡긴다.

    2. 반환 payload를 {"ok", "tool_name"}으로 감싸지 않는다.
       구현 가이드가 정한 반환 계약은 top-level에 final_slot, reason, candidates가
       오는 것이다. 한 겹 더 감싸면 _final_payloads_from_events가 판정 기준으로 삼는
       final_slot 키가 상위에서 사라진다.
    """
    payload = decide_final_slot_payload(
        candidate_slots=candidate_slots,
        selected_slot=selected_slot,
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
    """Kana 하위 agent가 볼 수 있는 tool 목록입니다."""

    """find_common_available_slots와 decide_final_slot을 목록에 다시 넣은 이유와 순서.

    1. 두 tool의 본문과 description을 구현했다.
       이전 범위에서는 본문이 `...`이라 호출되면 None을 반환하고 description도 비어 있어
       목록에서 제외했다. 이번에 둘 다 구현해 목록에 넣는 조건이 맞는다.

    2. 호출 순서대로 목록에 둔다.
       collect_member_schedules로 busy_rows를 모으고, find_common_available_slots로 후보를
       검증하고, decide_final_slot으로 최종 시간을 기록하는 순서다. 목록 순서가 호출
       순서를 정하지는 않지만, 순서를 정하는 근거는 WEEK06_KANA_TOOL_PROMPT에 적었다.

    3. propose_group_schedule은 넣지 않는다.
       최종 결정 payload를 만드는 tool이 두 개가 되면 어느 쪽을 호출할지 판단할 근거가
       필요해진다. 구현 가이드도 이 tool을 호환용으로만 남기라고 안내한다.
    """
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


def _run_subagent(agent: Any, agent_name: str, query: str) -> dict[str, Any]:
    """하위 agent를 실행하고 wrapper 두 개가 공통으로 반환하는 항목을 만듭니다."""

    """query를 user 메시지 하나로만 넘기는 이유와 예외를 처리하지 않는 이유.

    1. 하위 agent는 상위 대화 이력을 받지 않는다.
       supervisor의 messages를 그대로 전달하면 하위 agent가 supervisor 지시와 이전
       답변까지 읽게 되어 담당 범위가 불분명해진다. 전달 경로를 query 문자열 하나로 좁히면
       supervisor가 무엇을 넘겼는지 trace의 arguments에서 그대로 확인할 수 있다.

    2. 예외를 여기서 잡지 않는다.
       하위 agent 실행이 실패하면 LangChain이 tool 오류 메시지를 supervisor에게 전달한다.
       그보다 상위 실패는 fixed/week_agent_registry.py의 run_active_week_agent가 받는다.
       여기서 try/except로 감싸면 실패가 정상 payload로 바뀌어 두 경로 모두 우회한다.
    """
    result = agent.invoke({"messages": [{"role": "user", "content": query}]})
    events = extract_agent_events(result)
    return {
        "ok": True,
        "tool_name": agent_name,
        "selected_agent": agent_name,
        "answer": extract_final_text(result),
        "trace": {"events": events},
        "inner_tool_names": _tool_call_names(events),
    }


@tool(args_schema=AgentQueryInput)
def nana_agent(query: str) -> str:
    """개인 일정과 개인 RAG 작업을 프롬프트 기반 Nana 하위 에이전트에게 위임합니다."""

    global _NANA_SUBAGENT
    if _NANA_SUBAGENT is None:
        _NANA_SUBAGENT = create_agent(
            model=chat_model(),
            tools=week04_tools(),
            system_prompt=nana_system_prompt(),
        )
    return json.dumps(_run_subagent(_NANA_SUBAGENT, "nana_agent", query), ensure_ascii=False)


@tool(args_schema=AgentQueryInput)
def kana_agent(query: str) -> str:
    """그룹 일정 종합 작업을 프롬프트 기반 Kana 하위 에이전트에게 위임합니다."""

    """두 payload 키를 값이 없을 때도 반환하는 이유.

    decide_final_slot을 호출하지 않은 요청에서는 두 값이 None이다. 단순 일정 조회가
    여기 해당한다. 키 자체를 빼면 extract_langchain_trace(...)가 읽는 반환 계약이
    요청마다 달라지므로, 값이 없다는 사실은 None으로 남긴다.
    """
    global _KANA_SUBAGENT
    if _KANA_SUBAGENT is None:
        _KANA_SUBAGENT = create_agent(
            model=chat_model(),
            tools=kana_tools(),
            system_prompt=kana_system_prompt(),
        )
    payload = _run_subagent(_KANA_SUBAGENT, "kana_agent", query)
    final_slot_payload, final_decision_payload = _final_payloads_from_events(payload["trace"]["events"])
    payload["final_slot_payload"] = final_slot_payload
    payload["final_decision_payload"] = final_decision_payload
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
