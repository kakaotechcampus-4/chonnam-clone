{
  "events": [
    {
      "event": "tool_call",
      "tool_name": "search_previous_conversations",
      "arguments": {
        "query": "철수",
        "limit": 5
      },
      "id": "call_GsKJQFUJbIjD5vImTH5Wzpgj"
    },
    {
      "event": "tool_result",
      "tool_name": "search_previous_conversations",
      "content": {
        "ok": true,
        "tool_name": "search_previous_conversations",
        "rows": [
          {
            "conversation_id": "ext_cs",
            "member_name": "철수",
            "title": "철수의 일정 공유",
            "content": "철수: 7월 7일 10시는 API 연동 실습, 7월 9일 14시는 고객 인터뷰, 7월 15일 16시는 QA 리뷰가 있어요.",
            "created_at": "2026-07-29T20:37:35+09:00"
          }
        ]
      },
      "id": "call_GsKJQFUJbIjD5vImTH5Wzpgj"
    },
    {
      "event": "tool_call",
      "tool_name": "load_conversation_messages",
      "arguments": {
        "conversation_id": "ext_cs"
      },
      "id": "call_QD9RJiC75pca9HMvefrpK1Ge"
    },
    {
      "event": "tool_result",
      "tool_name": "load_conversation_messages",
      "content": {
        "ok": true,
        "tool_name": "load_conversation_messages",
        "rows": [
          {
            "role": "user",
            "sender": "철수",
            "content": "철수: 7월 7일 10시는 API 연동 실습, 7월 9일 14시는 고객 인터뷰, 7월 15일 16시는 QA 리뷰가 있어요.",
            "created_at": "2026-07-29T20:37:45+09:00"
          }
        ]
      },
      "id": "call_QD9RJiC75pca9HMvefrpK1Ge"
    }
  ],
  "mode": "active_week_agent",
  "active_week": 5,
  "conversation_id": "conv_4867ee8bc2"
}
