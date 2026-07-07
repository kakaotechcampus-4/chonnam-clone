# Ruff 스터디 가이드

## 1. Ruff란?

**Ruff**는 Python 코드를 검사하고 정리해주는 도구이다.

쉽게 말하면 다음 두 가지 역할을 한다.

1. **Linter**  
   코드에서 잠재적인 문제, 스타일 위반, 안 쓰는 import, 안 쓰는 변수 등을 찾아준다.

2. **Formatter**  
   코드의 들여쓰기, 줄바꿈, 공백, 괄호 배치 등을 자동으로 정리해준다.

기존에는 Python 프로젝트에서 보통 여러 도구를 조합해서 사용했다.

```bash
black .
isort .
flake8 .
pylint .
```

Ruff는 이 중 상당 부분을 하나의 도구로 대체할 수 있다.

```bash
ruff check .
ruff format .
```

즉, Ruff는 **Python 코드 품질 검사 + 자동 포매팅 + import 정렬**을 빠르게 처리하는 통합형 도구라고 볼 수 있다.

---

## 2. Ruff가 필요한 이유

Python은 문법이 비교적 자유롭기 때문에 사람마다 코드 스타일이 달라질 수 있다.

예를 들어 같은 기능을 하는 코드라도 이런 차이가 생긴다.

```python
def create_schedule(title,date,start_time,end_time):
    return {"title":title,"date":date,"start_time":start_time,"end_time":end_time}
```

이 코드는 동작은 하지만 읽기 어렵다. Ruff formatter를 적용하면 다음처럼 정리된다.

```python
def create_schedule(title, date, start_time, end_time):
    return {
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
    }
```

또한 Ruff는 다음과 같은 문제도 잡아준다.

```python
import os
import sys


def hello():
    x = 1
    print("hello")
```

이 코드에서 `os`, `sys`, `x`는 사용되지 않는다. Ruff는 이런 문제를 알려준다.

```text
F401 `os` imported but unused
F401 `sys` imported but unused
F841 local variable `x` is assigned to but never used
```

이런 식으로 Ruff는 사람이 일일이 확인하기 귀찮은 코드 스타일과 기본적인 품질 문제를 자동으로 점검해준다.

---

## 3. Ruff의 핵심 기능

## 3.1 코드 검사: `ruff check`

```bash
ruff check .
```

현재 프로젝트 전체의 Python 코드를 검사한다.

특정 파일만 검사하려면 다음처럼 실행한다.

```bash
ruff check student_parts/week01_wake_up_nana.py
```

주로 다음과 같은 문제를 찾는다.

- 사용하지 않는 import
- 사용하지 않는 변수
- 잘못된 import 순서
- PEP 8 스타일 위반
- 잠재적인 버그 패턴
- 너무 복잡하거나 권장되지 않는 코드 패턴

---

## 3.2 자동 수정: `ruff check --fix`

```bash
ruff check . --fix
```

Ruff가 자동으로 고칠 수 있는 문제를 수정한다.

예를 들어 다음과 같은 작업이 가능하다.

- 사용하지 않는 import 삭제
- import 순서 정리
- 일부 단순한 스타일 문제 수정

단, 모든 문제를 자동으로 고쳐주지는 않는다. Ruff가 자동으로 고치기 위험하다고 판단하는 문제는 직접 수정해야 한다.

---

## 3.3 코드 포매팅: `ruff format`

```bash
ruff format .
```

Python 코드의 모양을 자동으로 정리한다.

예를 들어 다음과 같은 부분을 정리한다.

- 들여쓰기
- 줄바꿈
- 공백
- 괄호 배치
- 긴 줄 정리
- 딕셔너리, 리스트, 함수 호출의 줄바꿈

Ruff formatter는 Black과 비슷한 역할을 한다.

---

## 4. Ruff와 다른 도구 비교

| 도구 | 역할 | 특징 |
|---|---|---|
| Black | Formatter | 코드 모양을 자동 정리한다. 설정을 많이 하지 않는 것이 특징이다. |
| isort | Import 정렬 | import 순서를 자동으로 정리한다. |
| flake8 | Linter | 코드 스타일과 기본 오류를 검사한다. |
| pylint | Linter | 더 엄격하고 상세하게 코드 품질을 검사한다. 초반에는 메시지가 많아 부담될 수 있다. |
| Ruff | Linter + Formatter | 빠르고, 여러 도구의 역할을 하나로 통합한다. |

과거에는 다음처럼 여러 도구를 함께 쓰는 경우가 많았다.

```bash
black .
isort .
flake8 .
pylint .
```

최근에는 간단한 프로젝트나 과제에서는 다음처럼 Ruff만으로 시작해도 충분한 경우가 많다.

```bash
ruff check . --fix
ruff format .
```

---

## 5. Ruff와 PEP 8, Google Python Style Guide의 관계

Ruff는 특정 회사의 스타일 문서 자체는 아니다.

구분하면 다음과 같다.

| 구분 | 의미 |
|---|---|
| PEP 8 | Python의 대표적인 공식 스타일 가이드 |
| Google Python Style Guide | Google에서 정리한 Python 코드 작성 규칙 |
| pylint | 코드가 특정 규칙을 잘 따르는지 검사하는 전통적인 도구 |
| Ruff | 빠른 속도로 코드 스타일과 품질을 검사하고 포매팅하는 도구 |

즉, **PEP 8이나 Google Python Style Guide는 규칙 문서**이고, **Ruff는 그와 비슷한 코드 품질 기준을 실제 코드에 적용해 검사하고 정리해주는 도구**라고 볼 수 있다.

---

## 6. 설치 방법

가장 간단한 설치 방법은 `pip`를 사용하는 것이다.

```bash
pip install ruff
```

설치 확인은 다음 명령어로 한다.

```bash
ruff --version
```

`uv`를 사용한다면 다음처럼 설치할 수도 있다.

```bash
uv tool install ruff
```

---

## 7. 기본 사용법

## 7.1 전체 프로젝트 검사

```bash
ruff check .
```

## 7.2 특정 파일 검사

```bash
ruff check student_parts/week01_wake_up_nana.py
```

## 7.3 자동 수정 가능한 문제 고치기

```bash
ruff check . --fix
```

## 7.4 코드 포매팅

```bash
ruff format .
```

## 7.5 포매팅이 필요한지 확인만 하기

```bash
ruff format . --check
```

이 명령은 코드를 직접 바꾸지 않고, 포매팅이 필요한 파일이 있는지만 확인한다. CI에서 유용하다.

---

## 8. PR 올리기 전 추천 워크플로우

과제나 팀 프로젝트에서 PR을 올리기 전에는 다음 순서로 실행하면 좋다.

```bash
ruff check . --fix
ruff format .
ruff check .
```

각 명령의 의미는 다음과 같다.

1. `ruff check . --fix`  
   자동으로 고칠 수 있는 lint 문제를 수정한다.

2. `ruff format .`  
   코드 모양을 정리한다.

3. `ruff check .`  
   아직 남아 있는 문제가 있는지 최종 확인한다.

과제 파일만 대상으로 하고 싶다면 다음처럼 실행해도 된다.

```bash
ruff check student_parts/week01_wake_up_nana.py --fix
ruff format student_parts/week01_wake_up_nana.py
ruff check student_parts/week01_wake_up_nana.py
```

---

## 9. 설정 파일 작성하기

Ruff는 설정 없이도 사용할 수 있다. 하지만 프로젝트 기준을 명확히 하고 싶다면 루트 디렉토리에 `pyproject.toml` 파일을 만들 수 있다.

예시:

```toml
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I"]
```

각 설정의 의미는 다음과 같다.

| 설정 | 의미 |
|---|---|
| `line-length = 88` | 한 줄 길이 기준을 88자로 설정한다. Black 기본값과 비슷하다. |
| `target-version = "py311"` | Python 3.11 기준으로 코드를 검사한다. |
| `select = ["E", "F", "I"]` | 기본 스타일 오류, Pyflakes 오류, import 정렬 규칙을 사용한다. |

처음부터 규칙을 너무 많이 켜면 lint 오류가 과도하게 많이 나올 수 있다. 과제나 입문 단계에서는 `E`, `F`, `I` 정도로 시작하는 것이 무난하다.

---

## 10. 주요 규칙 코드 이해하기

Ruff가 출력하는 메시지에는 보통 규칙 코드가 붙는다.

예시:

```text
F401 `os` imported but unused
F841 local variable `x` is assigned to but never used
I001 Import block is un-sorted or un-formatted
```

자주 볼 수 있는 코드는 다음과 같다.

| 코드 | 의미 |
|---|---|
| `F401` | import했지만 사용하지 않음 |
| `F841` | 변수를 선언했지만 사용하지 않음 |
| `E501` | 한 줄이 너무 김 |
| `I001` | import 정렬이 필요함 |

Ruff 메시지는 처음에는 낯설 수 있지만, 대부분 “어디가 문제인지”와 “어떻게 고치면 되는지”를 함께 알려준다.

---

## 11. VS Code에서 사용하기

VS Code를 사용한다면 확장 프로그램에서 **Ruff**를 설치할 수 있다.

설치 후 Python 파일을 열면 Ruff가 문제를 표시해준다.

저장할 때 자동 포맷을 적용하고 싶다면 VS Code의 `settings.json`에 다음과 같이 설정할 수 있다.

```json
{
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  }
}
```

처음에는 VS Code 설정까지 하지 않아도 된다. 터미널에서 다음 명령만 사용해도 충분하다.

```bash
ruff check . --fix
ruff format .
```

---

## 12. GitHub Actions에서 사용하기

팀 프로젝트나 과제에서 PR마다 자동 검사를 하고 싶다면 GitHub Actions에 Ruff를 붙일 수 있다.

예시 `.github/workflows/ruff.yml`:

```yaml
name: Ruff

on:
  pull_request:
  push:

jobs:
  ruff:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install Ruff
        run: pip install ruff

      - name: Run Ruff Check
        run: ruff check .

      - name: Run Ruff Format Check
        run: ruff format . --check
```

이렇게 설정하면 PR을 올릴 때 자동으로 코드 스타일과 포매팅 여부를 검사할 수 있다.

---

## 13. pre-commit과 함께 사용하기

커밋하기 전에 자동으로 Ruff를 실행하고 싶다면 `pre-commit`을 사용할 수 있다.

설치:

```bash
pip install pre-commit
```

`.pre-commit-config.yaml` 예시:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.12.0
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
```

설정 적용:

```bash
pre-commit install
```

이후 커밋할 때마다 Ruff가 자동으로 실행된다.

단, 과제 초반에는 pre-commit까지 설정하지 않아도 된다. 먼저 터미널 명령어에 익숙해지는 것이 좋다.

---

## 14. 현재 과제에서의 적용 예시

카카오테크캠퍼스 과제처럼 특정 파일을 구현하는 상황에서는 다음처럼 사용하면 된다.

```bash
ruff check student_parts/week01_wake_up_nana.py --fix
ruff format student_parts/week01_wake_up_nana.py
ruff check student_parts/week01_wake_up_nana.py
```

다음 주차 과제라면 예를 들어 다음처럼 사용할 수 있다.

```bash
ruff check student_parts/week02_*.py --fix
ruff format student_parts/week02_*.py
ruff check student_parts/week02_*.py
```

PR 설명이나 회고에는 다음과 같이 적을 수 있다.

```text
멘토님 피드백을 반영하여 이번 주차부터 Ruff를 사용해 Python 코드 포매팅과 기본 린트 검사를 수행했습니다.
```

---

## 15. Ruff를 사용할 때 주의할 점

## 15.1 자동 수정 전에는 변경 사항을 확인하기

`ruff check . --fix`는 파일을 직접 수정한다. 따라서 실행 후에는 반드시 변경 내용을 확인해야 한다.

```bash
git diff
```

## 15.2 모든 Ruff 경고가 무조건 버그는 아니다

Ruff가 알려주는 내용 중 일부는 스타일 권장 사항이다. 프로젝트 상황에 따라 무시해도 되는 경우가 있다.

## 15.3 처음부터 너무 많은 규칙을 켜지 않기

Ruff는 매우 많은 규칙을 지원한다. 처음부터 모든 규칙을 켜면 코드 작성보다 lint 오류 수정에 시간을 더 많이 쓸 수 있다.

입문 단계에서는 다음 정도로 시작하는 것이 좋다.

```toml
[tool.ruff.lint]
select = ["E", "F", "I"]
```

## 15.4 포매터와 린터의 역할을 구분하기

```bash
ruff check .
```

이 명령은 문제를 검사한다.

```bash
ruff format .
```

이 명령은 코드 모양을 정리한다.

둘은 역할이 다르므로 PR 전에는 둘 다 실행하는 것이 좋다.

---

## 16. 추천 사용 단계

처음 Ruff를 도입한다면 다음 순서가 좋다.

### 1단계: 터미널에서 수동 실행

```bash
ruff check . --fix
ruff format .
```

### 2단계: 설정 파일 추가

```toml
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I"]
```

### 3단계: VS Code 연동

저장할 때 자동 포매팅을 적용한다.

### 4단계: GitHub Actions 적용

PR마다 자동으로 Ruff 검사가 돌도록 만든다.

### 5단계: pre-commit 적용

커밋 전에 자동으로 Ruff가 실행되도록 만든다.

---

## 17. 한 줄 요약

Ruff는 Python 코드의 **스타일 정리, import 정렬, 기본 오류 탐지**를 빠르게 처리해주는 도구이다.

과제나 팀 프로젝트에서는 PR을 올리기 전에 다음 명령어를 실행하는 습관을 들이면 좋다.

```bash
ruff check . --fix
ruff format .
ruff check .
```

처음에는 pylint처럼 엄격한 도구보다 Ruff로 시작하는 것이 부담이 적고 실용적이다.

---

## 18. 실전 도입 실험 및 교훈 (카카오테크캠퍼스 과제 적용기)

실제 `week01_wake_up_nana.py` 과제 코드에 Ruff를 실험적으로 적용해보며 다음과 같은 사실들을 확인했습니다.

### 🔬 우리가 한 일
1. `pyproject.toml`에 기본 규칙(`E`, `F`, `I`)과 줄 길이 제한(88자)을 설정했습니다.
2. VS Code `.vscode/settings.json`에 `editor.formatOnSave` 및 `source.fixAll.ruff` 설정을 추가해 저장 시 자동 포매팅이 되도록 구성했습니다.
3. 일부러 엉망으로 짠 코드를 넣고 저장해보며 동작을 테스트했습니다.

### 💡 새롭게 알게 된 점과 주의사항
1. **강력한 포매팅 효과:** 딕셔너리, 리스트, 긴 파라미터를 가진 함수들이 저장 한 번에 매우 예쁘고 가독성 좋게 줄바꿈(Wrapping) 및 정렬되었습니다.
2. **미사용 변수 경고:** 쓰지 않는 변수(`F841`)는 코드가 꼬일 위험 때문에 자동으로 삭제하지 않고 노란 줄로 경고만 해주는 안전성을 확인했습니다.
3. **🚨 뼈대 코드(Scaffolding) 유실 위험 (가장 중요한 교훈):** 
   - 과제 템플릿에는 "나중에 가져다 쓰세요"라는 의미로 미리 작성된 미사용 `import` 문들이 존재합니다.
   - Ruff의 `F401` 규칙(안 쓰는 import 자동 삭제)이 켜져 있으면, **과제를 위해 남겨둔 중요한 뼈대 import 코드들이 모두 자동으로 지워지는 대참사**가 발생할 수 있다는 것을 발견했습니다.

### 🛡️ 해결책 (결과)
이러한 불상사를 막기 위해서는 과제용 레포지토리의 경우 `pyproject.toml`에 다음과 같이 `unfixable` 설정을 추가해야 합니다.

```toml
[tool.ruff.lint]
select = ["E", "F", "I"]
unfixable = ["F401"] # 과제용 뼈대 코드의 미사용 import 자동 삭제 방지
```

위와 같이 설정하면 안 쓰는 `import`가 있다는 것은 알려주되, 멋대로 삭제하지는 않게 됩니다. 

*(참고: 이번 실험은 학습 목적이었으므로, 혹시 모를 코드 꼬임을 방지하기 위해 파일들은 다시 원상복구(봉인) 해두었습니다. 향후 과제를 진행할 때 위 설정법을 참고하여 안전하게 적용하면 됩니다!)*
