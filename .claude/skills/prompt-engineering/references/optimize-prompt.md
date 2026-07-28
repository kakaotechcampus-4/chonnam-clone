# Workflow: Optimize an Existing Prompt or Tool Set

Trigger: "이 프롬프트 최적화해줘", "optimize this prompt", "tool description 다듬어줘"

## Steps

1. **Audit first, edit second.** Read the whole prompt/tool set and flag, without rewriting yet:
   - Hedge words (might, could, should consider)
   - Redundant or overlapping instructions
   - Paragraphs that should be lists
   - Full data dumps that could be just-in-time lookups
   - Tools with overlapping purposes

2. **Apply fixes by category:**
   - **Verbose → Direct:** collapse justification-heavy sentences into one imperative line.
   - **Paragraph → List:** convert requirement prose into bullets.
   - **Full data → Reference:** replace embedded datasets/schemas with a pointer ("see schema.json" / "call `get_product(sku)`").
   - **Overlapping tools → Merge or differentiate:** either combine them or sharpen each description so tool selection is unambiguous.

3. **Show a before/after.** Note roughly how much shorter the result is and confirm no requirement was silently dropped — cutting tokens must not cut meaning.

4. **Run the review checklist** (see main SKILL.md) on the final version.
