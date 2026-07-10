# Week 2 프롬프트 엔지니어링 기법 비교 실험 설계

## 배경

멘토(kim1034)가 Week 2 리뷰에서 제안: 동일한 사용자 입력에 대해 다양한 프롬프트 기법으로
system prompt를 바꿔가며 (1) token 사용량과 (2) `personal_schedule/group_schedule/todo/
reminder/unknown` 분류 결과가 어떻게 달라지는지 비교하고, 어떤 기준으로 "더 좋은 프롬프트"인지
판단해보라는 과제.

과제 코드(`student_parts/week02_structure_natural_language_requests.py`)는 채점 대상이므로
건드리지 않는다. 비교 실험은 별도 스크립트와 리포트로만 수행한다.

## 목적

같은 입력 세트 → 4가지 system prompt variant → 분류 정확도 + 토큰 사용량을 표로 정리하고,
"분류 정확도 우선, 동점이면 토큰 적은 쪽이 더 좋은 프롬프트"라는 기준으로 결론을 낸다.

## 폴더 구조

모든 산출물을 새 폴더 `experiments/week02_prompt_comparison/`에 모은다.

```
experiments/week02_prompt_comparison/
  test_cases.py       # 라벨링된 테스트 문장 14개
  prompt_variants.py   # 4개 system prompt 빌더 함수
  run_comparison.py    # 실행기 (CLI, --dry-run 지원)
  report.md            # 실행 결과 리포트 (실행 후 생성/갱신)
```

## 구성 요소

### 1. `test_cases.py`

`kind`당 2~3개, 총 14개 라벨링된 문장. dataclass 또는 named tuple로 `(text, expected_kind)` 목록:

- personal_schedule (3): 병원 예약, 헬스장 일정, 치과 검진 — 모두 members 없음
- group_schedule (3): 철수랑 회의, 가족 저녁 모임, 팀 스탠드업 — 모두 members 있음
- todo (3): 보고서 초안(급함), 장보기, 슬라이드 정리 — 시각 미확정 작업
- reminder (3): 어제 낸 과제 리마인더, 병원 진료 리마인더, 세미나 참석 리마인더 — 이미 존재하는 일
- unknown (2): 모호한 문장 2개
- 경계 케이스 (1개 이상, 위 개수에 포함 가능): todo vs reminder처럼 헷갈리는 문장 1개를 섞어서
  프롬프트 기법 간 차이가 더 잘 드러나게 한다.

### 2. `prompt_variants.py`

각 함수는 `list[str]`(prompt parts)를 반환하고, `join_system_prompt()`로 합쳐 system prompt
문자열을 만든다. 4개 variant는 모두 `RequestKind` 정의와 오늘 날짜만 공통으로 포함하고, 그 외
지침 수준만 다르게 한다:

- `zero_shot_parts()`: kind 목록 설명 + 필드 설명만. few-shot 예시, 판단 규칙, role 없음.
- `few_shot_baseline_parts()`: 현재 `week02_prompt_parts()`의 지침 텍스트를 그대로 복사(원본은
  import하지 않고 문자열을 이 파일에 독립적으로 옮겨 적어, 원본이 나중에 바뀌어도 비교 실험이
  흔들리지 않게 고정한다). 예시 2개 포함.
- `few_shot_cot_parts()`: baseline + "최종 구조화 전에 먼저 이 요청이 어떤 kind에 해당하는지와
  그 근거를 생각한 뒤 reason 필드에 근거를 적고 나서 나머지 필드를 채워라"는 지시 추가.
- `role_rules_parts()`: "너는 다년간 일정관리 비서로 일해온 전문가다" 역할 부여 + kind별 명시적
  판단 규칙(예: "members가 1명 이상이면 group_schedule, 없으면 personal_schedule", "특정 시각
  약속이 아니라 완료해야 할 작업이면 todo", "이미 존재하는 사안에 대한 알림이면 reminder",
  "판단 근거가 부족하면 unknown") 나열. few-shot 예시는 없음.

### 3. `run_comparison.py`

- `student_parts/week02_structure_natural_language_requests.py`에서 `StructuredRequestBatch`,
  `RequestKind`를 import (스키마는 재사용, 프롬프트 텍스트만 독립).
- `fixed/llm.py`의 `chat_model()`, `fixed/runtime_clock.py`의 `current_app_date_iso()` 재사용.
- 각 variant × 각 test case에 대해:
  ```python
  structured_llm = chat_model().with_structured_output(
      StructuredRequestBatch, method="function_calling", include_raw=True
  )
  result = structured_llm.invoke([("system", system_prompt), ("user", text)])
  ```
  `result["raw"].usage_metadata`에서 `input_tokens`/`output_tokens`/`total_tokens`를,
  `result["parsed"].requests[0].kind`를 추출해 기록. `requests`가 비어 있거나 2개 이상이면
  "구조 이상"으로 별도 표시(오답 처리).
- API 예외 발생 시 해당 (variant, case) 한 건만 실패로 기록하고 계속 진행.
- CLI 옵션 `--dry-run`: variant당 test case를 앞 2개로 제한해 빠르게 파싱/토큰 추출 확인.
- 실행이 끝나면 `report.md`를 생성/덮어쓴다.

### 4. `report.md` (실행 결과물)

- variant별 전체 정확도(14문항 중 정답 수), kind별 정확도, 평균 토큰(요청당 input/output/total)
- 정확도 내림차순, 동점이면 평균 토큰 오름차순으로 정렬한 순위표
- 마지막에 "분류 정확도 우선, 동점이면 토큰 적은 쪽" 기준에 따른 결론 1~2문장

## 에러 처리

- 개별 API 호출 실패(네트워크/rate limit 등): 해당 셀을 "ERROR"로 남기고 전체 실행은 중단하지 않는다.
- `PROXY_TOKEN` 미설정: `chat_model()`이 이미 `RuntimeError`를 던지므로 그대로 전파해 스크립트를
  즉시 종료한다(과도한 방어 코드 추가하지 않음).

## 검증 방법

1. `--dry-run`으로 variant당 2케이스만 실행 → 4개 파일이 모두 파싱되고 토큰 수치가 0이 아닌지 확인.
2. 문제 없으면 전체 56회(4 variant × 14 case) 실행 → `report.md` 생성 확인.
3. `report.md`의 표 합계(정답 수 합)가 실제 CLI 출력 로그와 일치하는지 육안 확인.

## 범위 밖

- `week02_prompt_parts()`/`week02_system_prompt()` 등 과제 코드 수정 없음.
- StructuredRequest 필드 정확도(title/date/members 등) 채점은 하지 않음 — kind 분류와 토큰만 비교.
- self-consistency, few-shot 예시 개수 스윕 등 추가 기법은 이번 실험 범위 밖(향후 확장 가능).
