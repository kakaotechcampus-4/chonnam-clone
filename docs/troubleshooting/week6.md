# Week 6 — Troubleshooting

## 기본 Python에서 `langchain` import가 실패함

- 증상: `python -c "import student_parts.week06_kanamate_decides_schedule"` 실행 시 `ModuleNotFoundError: No module named 'langchain'`이 발생했다.
- 원인: 시스템 기본 Python에는 프로젝트 의존성이 설치되어 있지 않았고, 저장소는 `.venv`와 `uv` 실행 환경을 사용한다.
- 해결: `.venv\Scripts\python.exe`로 import와 검증을 다시 실행해 성공했다.

## 프로젝트 가상환경에서 `pytest` 모듈을 찾지 못함

- 증상: `.venv\Scripts\python.exe -m pytest -q` 실행 시 `No module named pytest`가 발생했다.
- 원인: 공개 테스트는 `unittest.TestCase` 기반이며 현재 프로젝트 `.venv`에 `pytest`가 설치되어 있지 않다.
- 해결: 새 패키지를 설치하지 않고 `.venv\Scripts\python.exe -m unittest discover -s tests -v`로 실행 방식을 바꿨고, 공개 테스트 16개가 모두 통과했다.
