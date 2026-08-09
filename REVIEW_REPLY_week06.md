# PR #155 리뷰 답글 (→ @GitJIHO)

리뷰 감사합니다. 세 지적 모두 트레이스로 확인하고 반영했습니다. 각 항목의 결정과 근거, 남은 판단을 정리했습니다.

---

## ① `find_common_available_slots`의 `member_names` 필수 → 선택화 (week5와 일관)

**결론: week5와 동일하게 선택 필드로 바꿨습니다.** `list[str] | None = None`, 생략 = 등록 멤버 전원 + 나.

먼저 "다들 언제 되는지" 같은 요청을 트레이스로 돌려보니, `required`인 상태에서도 Kana가 전원 6명을 매번 스스로 열거해 실제 조율은 문제없이 돌았습니다(전원 커버 재현). 그래서 이건 "버그"는 아니었습니다.

다만 지적하신 우려의 핵심은 **week5에서 이미 확정한 결정(생략=전원)과 표면 API가 갈라진다**는 점이라고 봤습니다. week5는 `collect_member_schedules`/`extract_schedules_from_history`를 선택 필드로 두고 "생략=전원"을 store 레벨에서 처리하기로 근거까지 남겼는데, week6만 required로 두면 같은 의미를 다른 계약으로 표현하게 됩니다. 그래서 **결정을 일관되게 이어받아** 선택화했습니다.

구현 시 확인한 메커니즘(트레이스 근거):
- Kana는 `collect_member_schedules`(생략 → 전원 7명, busy row 35건)를 먼저 부르고, 그 rows를 `find_common_available_slots`에 `busy_rows`로 복사해 넘깁니다.
- **겹침 계산은 `busy_rows`가** 하므로, LLM이 `member_names` 인자를 `[]`/`null`로 비워 넘겨도 전원 일정이 그대로 검증 대상에 들어갑니다.
- 날짜가 있는 실제 요청("다들 2026년 7월에...")은 **전원 커버(busy_rows∪members 기준) 6/6, 누락 없음**으로 확인했습니다.
- 이 과정에서 발견한 실제 버그 하나: LLM이 `member_names=[]` + `busy_rows`(전원)을 넘기면 payload의 `members` **라벨**만 `["나"]`로 좁아졌습니다(스케줄링은 정상, 기록 라벨만 부정확). `busy_rows`가 있으면 라벨을 rows가 덮는 멤버로 채우도록 고쳐 `[]`/`null`이어도 라벨이 전원으로 남게 했습니다.
- 검증 지표도 바로잡았습니다: 처음엔 `member_names` **인자**로 커버를 쟀는데(라벨이라 `[]`면 0으로 오독됨), 실제 겹침 근거인 `busy_rows`+payload `members`로 재도록 대본을 고쳤습니다.

`[]`(빈 목록)은 week5 규칙과 맞춰 "외부 멤버 지정 없음 = 나 기준"으로 문서화했습니다(전원과 구분).

## ② 서브에이전트 호출 예외 처리 부재 → try/except 추가 (week5 패턴 재사용)

`_NANA_SUBAGENT.invoke()` / `_KANA_SUBAGENT.invoke()`를 각각 감쌌습니다.
- 판정 기준을 week5의 `_INTERNAL_BUG_ERRORS`(NameError/AttributeError/KeyError/IndexError) **그대로 import해서 재사용**했습니다. week5 docstring이 "사본이 갈라지면 한쪽만 버그를 삼킨다"고 경고한 만큼, 단일 소스로 공유하는 게 일관적이라 봤습니다.
- 내 버그(위 예외)는 `raise`로 그대로 올리고, 그 외(모델 API/네트워크 등 경계 너머 실행 실패)만 `{"ok": false, ..., "error": ...}` payload로 돌려줍니다. `try`에는 `invoke` 한 줄만 두어, 결과 가공 중 나는 프로그래밍 오류가 실행 실패로 오분류되지 않게 했습니다.
- 실패 payload는 두 wrapper 공용 헬퍼(`_subagent_failure_payload`)로 한 번만 정의했습니다.

결정적 검증: 외부 실패(`RuntimeError`) → `ok:false` 반환, 내 버그(`KeyError`) → 삼키지 않고 재전파 확인.

## ③ 혼합 요청(시간 찾기→저장) 2단계 위임 불안정 → 원인 규명 + 프롬프트 강화

**원인은 구조적 한계가 아니라 프롬프트 튜닝 문제였습니다.**

같은 혼합 발화를 6회 반복한 트레이스:
- **개선 전**: `kana→nana` 5/6, `kana만` 1/6 (구조는 2단계 재위임을 지원하지만 supervisor가 가끔 첫 위임에서 멈춤).
- supervisor system prompt에 "저장·등록이 요청에 포함되면 kana의 시간 확정 결과만으로 답을 끝내지 말고, 확정 시간을 담아 nana에 저장을 반드시 이어서 위임한다"를 명시적으로 강화.
- **개선 후**: `kana→nana` **6/6**, 실제 저장 도구 실행도 6/6.

즉 "요청당 하나 위임"이라는 가이드 기본값 때문에 재위임이 확률적으로 새던 것이라, 지시를 강화하니 안정화됐습니다.

---

## 회고 / 남은 것

- ①에서 배운 점: `find_common_available_slots`의 `member_names`는 사실상 **기록 라벨**이고 실제 겹침은 `busy_rows`가 결정합니다. 처음엔 인자만 보고 "커버 0/6"으로 오독할 뻔했는데, 결과(payload members + busy_rows)를 봐야 정확했습니다. 검증 대본도 인자가 아니라 결과 기준으로 재게 고쳤습니다.
- 재현용 트레이스 2개를 추가했습니다: `trace_week06_member_scope.py`(전원 조율 유지), `trace_week06_mixed_stability.py`(2단계 위임 분포). 둘 다 실행 후 생성 row는 자동 정리합니다.
- 선택화하면서 드러난 **날짜 축** 문제도 같이 잡았습니다: "다들 언제 되는지"처럼 날짜가 없는 요청은 선택화 후 Kana가 빈 busy_rows로 find_slots를 불러 근거 없는 후보를 냈습니다(3/3, 전원고려 0/6). Kana 프롬프트에 "날짜/기간이 없을 때만 후보를 내지 말고 되묻는다"는 가드를 추가했습니다. 되묻기는 **날짜 축에만** 한정했고, 회의 대상 멤버·소요 시간은 되묻지 않게(=`member_names` 비워 전원, 소요 시간 기본값) 명시해 ①의 선택화와 일관되게 뒀습니다. 검증: 날짜 없는 요청 3/3 되묻기, 날짜 있는 요청 3/3 전원고려 6/6(회귀 없음).
