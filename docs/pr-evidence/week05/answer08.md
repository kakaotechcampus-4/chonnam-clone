{
  "events": [
    {
      "event": "tool_call",
      "tool_name": "search_personal_references",
      "arguments": {
        "query": "혈액형"
      },
      "id": "call_f9HMMFo1V71aKnCQPUL5u3oI"
    },
    {
      "event": "tool_result",
      "tool_name": "search_personal_references",
      "content": {
        "hits": [
          {
            "id": "ref_7ca7611fdd",
            "content": "A형",
            "distance": 1.1625300645828247,
            "metadata": {
              "title": "혈액형",
              "tags": ""
            }
          },
          {
            "id": "ref_2978297b1c",
            "content": "우유 알러지가 있음",
            "distance": 1.590311050415039,
            "metadata": {
              "title": "우유 알러지",
              "tags": ""
            }
          }
        ]
      },
      "id": "call_f9HMMFo1V71aKnCQPUL5u3oI"
    }
  ],
  "mode": "active_week_agent",
  "active_week": 5,
  "conversation_id": "conv_4867ee8bc2"
}
