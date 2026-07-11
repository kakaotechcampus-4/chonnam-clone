# Week 2 프롬프트 기법 비교 리포트

| 순위 | variant | 정확도 | 정답/전체 | 평균 input 토큰 | 평균 output 토큰 | 평균 total 토큰 |
|---|---|---|---|---|---|---|
| 1 | role_rules | 100.0% | 14/14 | 587.0 | 72.9 | 659.9 |
| 2 | few_shot_cot | 100.0% | 14/14 | 713.0 | 88.1 | 801.1 |
| 3 | zero_shot | 92.9% | 13/14 | 495.0 | 78.1 | 573.1 |
| 4 | few_shot_baseline | 92.9% | 13/14 | 665.0 | 58.5 | 723.5 |

## kind별 정확도

### role_rules
- group_schedule: 3/3
- personal_schedule: 3/3
- reminder: 3/3
- todo: 3/3
- unknown: 2/2

### few_shot_cot
- group_schedule: 3/3
- personal_schedule: 3/3
- reminder: 3/3
- todo: 3/3
- unknown: 2/2

### zero_shot
- group_schedule: 3/3
- personal_schedule: 3/3
- reminder: 3/3
- todo: 2/3
- unknown: 2/2

### few_shot_baseline
- group_schedule: 2/3
- personal_schedule: 3/3
- reminder: 3/3
- todo: 3/3
- unknown: 2/2

## 결론

분류 정확도 우선, 동점이면 토큰 적은 쪽 기준으로 **role_rules**가 가장 우수했다 (정확도 100.0%, 평균 total 토큰 659.9).