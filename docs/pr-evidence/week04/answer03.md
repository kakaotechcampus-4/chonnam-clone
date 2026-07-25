{
  "events": [
    {
      "event": "tool_call",
      "tool_name": "search_saved_requests",
      "arguments": {
        "query": "코칭",
        "top_k": 3
      },
      "id": "call_BKXdE9J0j6AYKe4ST8yyR04s"
    },
    {
      "event": "tool_result",
      "tool_name": "search_saved_requests",
      "content": {
        "rows": [
          {
            "request_id": "req_ff5a4a0d3f",
            "kind": "personal_schedule",
            "title": "개인 코칭",
            "date": "2026-07-18",
            "start_time": "10:00",
            "end_time": null,
            "members_json": "[]",
            "priority": null,
            "reason": "내일 10시에 개인 일정 생성 요청",
            "raw_json": "{\"kind\": \"personal_schedule\", \"title\": \"개인 코칭\", \"date\": \"2026-07-18\", \"start_time\": \"10:00\", \"members\": [], \"reason\": \"내일 10시에 개인 일정 생성 요청\", \"original_text\": \"내일 10시 개인 코칭 저장해줘\"}",
            "created_at": "2026-07-17T11:39:25.299554+09:00"
          },
          {
            "request_id": "req_6fd4ddba53",
            "kind": "personal_schedule",
            "title": "개인 코칭",
            "date": "2026-07-18",
            "start_time": "10:00",
            "end_time": null,
            "members_json": "[]",
            "priority": null,
            "reason": "특정 날짜·시간의 개인 일정 생성 요청",
            "raw_json": "{\"kind\": \"personal_schedule\", \"title\": \"개인 코칭\", \"date\": \"2026-07-18\", \"start_time\": \"10:00\", \"members\": [], \"reason\": \"특정 날짜·시간의 개인 일정 생성 요청\", \"original_text\": \"내일 10시 개인 코칭 저장해줘\"}",
            "created_at": "2026-07-17T11:38:06.583492+09:00"
          },
          {
            "request_id": "req_7352f97dd0",
            "kind": "personal_schedule",
            "title": "개인 코칭",
            "date": "2026-07-18",
            "start_time": "10:00",
            "end_time": null,
            "members_json": "[]",
            "priority": null,
            "reason": "특정 날짜·시간의 개인 일정 생성 요청",
            "raw_json": "{\"kind\": \"personal_schedule\", \"title\": \"개인 코칭\", \"date\": \"2026-07-18\", \"start_time\": \"10:00\", \"members\": [], \"reason\": \"특정 날짜·시간의 개인 일정 생성 요청\", \"original_text\": \"내일 10시 개인 코칭 저장해줘\"}",
            "created_at": "2026-07-17T11:31:38.809509+09:00"
          }
        ]
      },
      "id": "call_BKXdE9J0j6AYKe4ST8yyR04s"
    }
  ],
  "mode": "active_week_agent",
  "active_week": 4,
  "conversation_id": "conv_5c7afaa8ee"
}