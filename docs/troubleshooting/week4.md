# Week 4 — Troubleshooting

## `week04_prompt_parts()`에서 참고자료 질문 안내가 `search_personal_references` 대신 `personal_list_saved_schedules`를 가리키도록 잘못 바뀜

- 증상: 커밋되지 않은 로컬 수정에서 `student_parts/week04_retrieve_nanas_memory.py`의 `week04_prompt_parts()` system prompt 문구가
  "선호/습관/메모/참고자료가 있는지" 질문의 안내 tool을 `search_personal_references`에서 `personal_list_saved_schedules`로 바꿔놓은 상태였다.
  같은 줄에서 앞의 여는 따옴표(`'저장된 일정...`)도 함께 사라져 있었다. Claude가 코드를 읽다가 발견해 사용자에게 확인을 요청했다.
- 원인: `student_parts/week04_retrieve_nanas_memory.py:369` 문자열이 참고자료(ChromaDB, `search_personal_references`)와
  저장된 일정(SQLite, `personal_list_saved_schedules`)이라는 서로 다른 출처를 가리키는 tool을 뒤바꿔 참조하고 있었다.
  이대로면 "내가 적어둔 참고자료 있어?" 같은 질문에도 LLM이 일정 조회 tool을 호출하도록 유도될 수 있었다.
- 해결: 사용자가 실수로 들어간 변경이라고 확인해줘서, `search_personal_references`와 여는 따옴표를 원래대로 되돌렸다.

## 개인 참고자료(ChromaDB)에 데이터가 있는데도 "내가 좋아하는 회의 시간대"를 물으면 저장된 게 없다고 답함

- 증상: 사용자가 "chroma db에 저장된 내용은 대화 없이도 알 수 있어야 하는데 왜 내가 좋아하는 일정 시간대를 물어봐도 저장된 것이 없다고 나오지?"라고 보고했다.
  ChromaDB 컬렉션(`kanana_personal_references_openai`)을 직접 조회해 시드 데이터 3건(`ref_focus`/`ref_lunch`/`ref_sync`)이 정상 저장돼 있음을 확인했고,
  `build_week04_agent()`로 실제 trace를 떠보니 `search_personal_references` tool도 정상 호출되고 있었다.
- 원인: `student_parts/week04_retrieve_nanas_memory.py`의 `SearchPersonalReferencesInput.top_k` 기본값과
  `search_personal_references(query, top_k: int = 2)` 함수 시그니처/`safe_limit(top_k, default=2, ...)` 호출이 모두 `2`로 되어 있었다.
  LLM이 짧은 키워드("회의 시간대")로 검색하면 세 참고자료 간 임베딩 거리가 비슷해 `ref_focus`(회의 시간대 선호, 바로 사용자가 물은 내용)가
  3위로 밀려 top_k=2 안에 들지 못하고 잘려나갔다. 재현: `search_personal_reference_hits(..., query="회의 시간대", top_k=2)` → `ref_lunch`, `ref_sync`만 반환, `ref_focus` 누락.
- 해결: `SearchPersonalReferencesInput.top_k` 기본값과 `search_personal_references`의 함수 시그니처 기본값·`safe_limit` 기본값을 모두 `2` → `3`으로 올렸다.
  같은 질문으로 `build_week04_agent()`를 다시 실행해 `ref_focus`가 hits에 포함되고 답변에도 반영되는 것을 확인했다.
