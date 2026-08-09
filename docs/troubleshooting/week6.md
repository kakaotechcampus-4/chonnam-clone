# Week 6 — Troubleshooting

## 기본 Python에서 `langchain` import가 실패함

- 증상: `python -c "import student_parts.week06_kanamate_decides_schedule"` 실행 시 `ModuleNotFoundError: No module named 'langchain'`이 발생했다.
- 원인: 시스템 기본 Python에는 프로젝트 의존성이 설치되어 있지 않았고, 저장소는 `.venv`와 `uv` 실행 환경을 사용한다.
- 해결: `.venv\Scripts\python.exe`로 import와 검증을 다시 실행해 성공했다.

## 프로젝트 가상환경에서 `pytest` 모듈을 찾지 못함

- 증상: `.venv\Scripts\python.exe -m pytest -q` 실행 시 `No module named pytest`가 발생했다.
- 원인: 공개 테스트는 `unittest.TestCase` 기반이며 현재 프로젝트 `.venv`에 `pytest`가 설치되어 있지 않다.
- 해결: 새 패키지를 설치하지 않고 `.venv\Scripts\python.exe -m unittest discover -s tests -v`로 실행 방식을 바꿨고, 공개 테스트 16개가 모두 통과했다.

## Prompt 문장별 소스 줄을 나눈 뒤 실제 system prompt에서 문장 사이 공백이 사라짐

- 증상: Supervisor/Nana/Kana prompt의 문장을 소스 코드에서 한 줄씩 분리했지만 실제 조립 결과가 `위임한다.개인`, `담당한다.필요한`, `사용한다.과거`처럼 붙고, 규칙들도 여전히 한 문단으로 출력된다.
- 원인: `student_parts/week06_kanamate_decides_schedule.py:201-204`, `214-216`, `225-230`, `247-249`의 인접 문자열 리터럴 끝에 공백이나 줄바꿈이 없다. Python은 이 문자열들을 구분자 없이 하나로 결합하며, 각 묶음이 리스트 요소 하나이므로 `join_system_prompt()`도 묶음 내부에는 단락 구분을 넣지 않는다.
- 해결: Supervisor/Nana/Kana prompt의 소스 줄을 사람이 읽기 좋은 의미와 문장 단위로 재배치해 각 역할과 규칙의 시작·끝을 쉽게 파악할 수 있도록 개선했다. 이번 피드백은 실행 문자열의 출력 형식이 아니라 소스 코드 가독성에 관한 것이므로 해결 완료로 판단했다.

## `다음 주` 일정 조율 요청에서 Kana가 날짜 범위를 계산하지 않고 되물음

- 증상: 앱 기준일이 2026-08-09일 때 `철수랑 다음 주에 시간 맞춰줘`를 Week 6 supervisor와 Kana에 각각 실행하면 supervisor는 `kana_agent`를 선택하지만, Kana는 일정 조회 tool을 호출하지 않고 다음 주의 구체적인 날짜 범위를 다시 묻는다. 따라서 `date_from`과 `date_to`가 생성되지 않는다.
- 원인: `student_parts/week06_kanamate_decides_schedule.py:13`에서 `current_app_date_iso`를 import하지만 `kana_prompt_parts()`에는 기준일이 포함되지 않고, 224줄의 지시는 날짜 범위가 불명확하면 먼저 확인하라고만 한다. 상대 날짜 구조화용으로 노출한 `student_parts/week02_structure_natural_language_requests.py:202`의 `extract_schedule_request`도 현재 미구현이라 호출 결과가 `None`이다.
- 해결: Kana prompt에 앱 기준일과 다음 주의 월요일~일요일 범위를 명시하고, 계산 가능한 상대 날짜는 되묻지 않도록 했다. 미구현 `extract_schedule_request`는 Kana 도구에서 제외하고, 일정 조율 요청에는 반드시 `collect_member_schedules`를 사용하도록 조회 도구의 역할을 구분했다. 회귀 테스트 19개가 모두 통과했으며, 실제 supervisor 실행에서도 `collect_member_schedules(member_names=["철수"], date_from="2026-08-10", date_to="2026-08-16")` 호출을 확인했다.
