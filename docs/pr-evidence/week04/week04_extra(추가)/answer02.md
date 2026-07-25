{
  "events": [
    {
      "event": "tool_call",
      "tool_name": "add_personal_reference",
      "arguments": {
        "title": "매운 음식 못 먹음",
        "content": "나는 매운 음식을 못 먹음"
      },
      "id": "call_l78xd2tklKVh17Ph7Wy3H3dI"
    },
    {
      "event": "tool_result",
      "tool_name": "add_personal_reference",
      "content": {
        "reference_backend": {
          "vector_store": "chromadb",
          "embedding_provider": "openai",
          "embedding_model": "openai/text-embedding-3-small",
          "embedding_base_url": "https://mlapi.run/b54ff33e-6d14-42df-93f9-0f1132160ee8/v1",
          "collection_name": "kanana_personal_references_openai",
          "chroma_dir": "C:\\Users\\alstj\\Downloads\\kakaotechcampus04\\chonnam-clone\\data\\chroma"
        },
        "reference": {
          "reference_id": "ref_6aad0bdb56",
          "title": "매운 음식 못 먹음",
          "content": "나는 매운 음식을 못 먹음",
          "tags": [],
          "backend": {
            "vector_store": "chromadb",
            "embedding_provider": "openai",
            "embedding_model": "openai/text-embedding-3-small",
            "embedding_base_url": "https://mlapi.run/b54ff33e-6d14-42df-93f9-0f1132160ee8/v1",
            "collection_name": "kanana_personal_references_openai",
            "chroma_dir": "C:\\Users\\alstj\\Downloads\\kakaotechcampus04\\chonnam-clone\\data\\chroma"
          }
        }
      },
      "id": "call_l78xd2tklKVh17Ph7Wy3H3dI"
    }
  ],
  "mode": "active_week_agent",
  "active_week": 4,
  "conversation_id": "conv_ca66c4d201"
}