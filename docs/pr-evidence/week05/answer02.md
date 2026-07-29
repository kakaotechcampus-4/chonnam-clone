{
  "events": [
    {
      "event": "tool_call",
      "tool_name": "collect_member_schedules",
      "arguments": {
        "member_names": [
          "영희",
          "민준"
        ],
        "date_from": "2026-07-07",
        "date_to": "2026-07-17"
      },
      "id": "call_kSPWHyjXJmC62K2smRSF20fA"
    },
    {
      "event": "tool_result",
      "tool_name": "collect_member_schedules",
      "content": {
        "ok": true,
        "tool_name": "collect_member_schedules",
        "member_names": [
          "영희",
          "민준"
        ],
        "external_member_names": [
          "영희",
          "민준"
        ],
        "date_from": "2026-07-07",
        "date_to": "2026-07-17",
        "personal_row_count": 0,
        "external_row_count": 6,
        "rows": [
          {
            "member_name": "영희",
            "title": "디자인 피드백",
            "date": "2026-07-07",
            "start_time": "13:00",
            "end_time": "14:00",
            "notes": "",
            "source_conversation_id": "ext_yh"
          },
          {
            "member_name": "민준",
            "title": "데이터 정리",
            "date": "2026-07-08",
            "start_time": "09:30",
            "end_time": "10:30",
            "notes": "",
            "source_conversation_id": "ext_mj"
          },
          {
            "member_name": "민준",
            "title": "백엔드 리뷰",
            "date": "2026-07-09",
            "start_time": "11:00",
            "end_time": "12:00",
            "notes": "",
            "source_conversation_id": "ext_mj"
          },
          {
            "member_name": "영희",
            "title": "콘텐츠 점검",
            "date": "2026-07-10",
            "start_time": "10:00",
            "end_time": "11:30",
            "notes": "",
            "source_conversation_id": "ext_yh"
          },
          {
            "member_name": "민준",
            "title": "운영 회의",
            "date": "2026-07-14",
            "start_time": "15:00",
            "end_time": "16:30",
            "notes": "",
            "source_conversation_id": "ext_mj"
          },
          {
            "member_name": "영희",
            "title": "발표 리허설",
            "date": "2026-07-16",
            "start_time": "15:00",
            "end_time": "16:00",
            "notes": "",
            "source_conversation_id": "ext_yh"
          }
        ],
        "schedule_summary": "- 영희 | 디자인 피드백 | 2026-07-07 13:00-14:00\n- 민준 | 데이터 정리 | 2026-07-08 09:30-10:30\n- 민준 | 백엔드 리뷰 | 2026-07-09 11:00-12:00\n- 영희 | 콘텐츠 점검 | 2026-07-10 10:00-11:30\n- 민준 | 운영 회의 | 2026-07-14 15:00-16:30\n- 영희 | 발표 리허설 | 2026-07-16 15:00-16:00"
      },
      "id": "call_kSPWHyjXJmC62K2smRSF20fA"
    }
  ],
  "mode": "active_week_agent",
  "active_week": 5,
  "conversation_id": "conv_4867ee8bc2"
}
