# 프로젝트 규칙 문서 (Commit & Assignment Rules)

## 1. 과제 진행 및 브랜치(Branch) 규칙
과제 제출 및 원활한 코드 리뷰를 위해 다음과 같은 브랜치 워크플로우를 따릅니다.

### 사용 브랜치
- **`main`**: 기준이 되는 메인 브랜치
- **`junyoung/final`**: 본인의 최종 결과물이 모이는 브랜치 (코드 리뷰 후 Merge 되는 곳)
- **`junyoung/weekX`**: 매 주차별 실제 과제 구현을 진행하는 작업 브랜치 (X는 주차 번호, 예: week1, week2)

### 과제 작업 흐름 (Workflow)
1. **주차별 브랜치 생성**: `git checkout -b junyoung/week1` (매 주차마다 해당 주차 이름으로 생성)
2. **과제 구현**: 주어진 과제 요구사항에 맞게 코드 작성 및 커밋
3. **원격 저장소 푸시**: `git push -u origin junyoung/week1`
4. **PR(Pull Request) 생성**: GitHub 웹에서 `junyoung/week1` 브랜치를 `junyoung/final` 브랜치로 병합(Merge)해 달라는 PR 작성
5. **코드 리뷰 및 수정**: 멘토나 동료의 리뷰를 받고, 추가 수정 사항이 있다면 현재 브랜치(`junyoung/week1`)에서 작업 후 다시 푸시
6. **Merge 완료**: PR이 승인되면 `junyoung/final` 브랜치로 머지
7. **다음 주차 시작**: 다음 주차 과제는 다시 `junyoung/final` (또는 `main`) 최신 상태에서 새로운 브랜치를 생성하여 반복

---

## 2. 커밋 메시지(Commit) 규칙
일관된 커밋 기록을 남겨 리뷰어와 본인이 변경 사항을 쉽게 파악할 수 있도록 **Conventional Commits** 방식을 권장합니다.

### 커밋 메시지 구조
```
<타입>: <제목>

<본문 (선택 사항)>
```

### 타입(Type) 분류
- `feat` : 새로운 기능 추가
- `fix` : 버그 수정
- `docs` : 문서 수정 (README.md, RULES.md, 주석 등)
- `style` : 코드 포맷팅, 세미콜론 누락 등 코드의 논리적 변경이 없는 경우
- `refactor` : 코드 리팩토링 (기능 변경 없이 코드 구조 개선)
- `test` : 테스트 코드 작성 및 수정
- `chore` : 빌드 설정 수정, 패키지 매니저(package.json 등) 설정, .gitignore 등 자잘한 작업

### 작성 예시
```bash
feat: 사용자 로그인 UI 구현
fix: 비밀번호 유효성 검사 로직 오류 수정
docs: 커밋 및 브랜치 규칙 문서 추가
style: 불필요한 공백 제거
```
