코드를 이해할 때는 “한 줄씩 해석”보다 먼저 **흐름의 뼈대**를 잡는 게 좋아요. 보통 이렇게 보면 덜 막힙니다.

1. **파일의 목적부터 말로 정리하기**
- import 해오는 부분 분석
1-1. pydantic에서 BaseModel과 Field를 import 해온다

1-2. student_parts.week01_wake_up_nana.py에서 join_system_prompt, week01_prompt_parts, week01_tools를 import 해온다
    - join_system_prompt: 각 파일에 있는 프롬프트 글을 누적 system 프롬프트로 join해줌
    - week01_prompt_parts: 1주차의 요구사항에 맞는 프롬프트 내용이다. 페르소나가 정의되어있고, tool 호출 전에 해야할 일, tool에 전달할 형식, 삭제시 정확한 schedule_id 가 필요하다고 명시해놓았다.
    프롬프트의 마지막 부분에, 정보가 부족한 부분이 있다면 missing_field 부분을 다시 질문하도록 명시되어있다.
    - week01_tools: 3개의 tool들을 리스트 형태로 반환한다 ([personal_create_schedule, personal_list_schedules, personal_delete_schedule])

week02_structure_natural_language_requests.py 파일은 week01_wake_up_nana.py 파일에서 tool을 실행시킨 결과를 가져와서, 일정 키워드를 추출한 후 json 형식으로 저장하기 쉽도록 반환하는 목적을 가진 파일이다



2. **실행 시작점 찾기**
   - `if __name__ == "__main__":`
   - 함수 호출부
   - 테스트 코드
   - 예제 실행 부분

   여기서부터 “처음 실행되는 순서”를 따라가면 됩니다.

3. **함수 단위로 나누어 보기**
   각 함수마다 아래처럼 한 문장으로 적어보세요.

   ```python
   def some_function(...):
       ...
   ```

   → “이 함수는 ___를 받아서 ___를 만든다.”

4. **변수의 변화 추적하기**
   특히 중요한 변수는 옆에 메모하면 좋아요.

   ```python
   user_request = "..."
   structured_request = ...
   ```

   → `user_request`가 어떤 값이고, 다음 줄에서 어떻게 바뀌는지 확인합니다.

5. **직접 작은 입력으로 실행해보기**
   가장 빠른 이해 방법은 예제를 넣고 출력해보는 거예요.

   ```python
   print("현재 값:", variable)
   ```

   또는 함수 앞뒤에 `print()`를 넣어서 흐름을 확인하면 됩니다.

6. **주석을 “내 말”로 다시 쓰기**
   코드 주석을 그대로 믿기보다, 내가 이해한 방식으로 바꿔 적어보세요.

   ```python
   # 사용자의 자연어 요청을 구조화된 딕셔너리로 변환한다
   ```

7. **전체 흐름을 그림처럼 적기**
   예를 들면:

   ```text
   사용자 요청 입력
   → 요청에서 핵심 정보 추출
   → 딕셔너리 형태로 정리
   → 결과 출력
   ```

현재 열어둔 `week02_structure_natural_language_requests.py` 같은 파일은 이름상 “자연어 요청을 구조화하는 연습 코드”일 가능성이 높으니, 먼저 **입력 문장 → 처리 함수 → 구조화된 결과** 흐름으로 보면 좋아요.

가장 좋은 습관은 코드 위에 이런 식으로 짧게 써보는 겁니다.

```python
# 이 파일의 목표:
# 자연어로 된 요청을 받아서, 코드가 이해하기 쉬운 구조화된 데이터로 바꾼다.
```

그리고 함수마다:

```python
# 이 함수의 목표:
# 사용자의 요청 문장에서 필요한 정보를 뽑아낸다.
```

이렇게 “코드를 한국어 문장으로 번역”하는 연습을 하면 흐름이 훨씬 잘 보입니다.
