# Workflow: Create a New Prompt or Tool Set

Trigger: "system prompt 만들어줘", "create a prompt", "이 에이전트용 프롬프트/tool 설계해줘"

## Steps

1. **Clarify the goal.** What should the agent do, who is the audience (end user vs. developer), and what's the smallest context it needs to succeed? If this isn't clear from the conversation, ask one focused question rather than guessing.

2. **Draft using the structure standard.**
   ```markdown
   ## Background Information
   [Minimal essential context]

   ## Instructions
   - [Imperative, specific directive]
   - [Imperative, specific directive]

   ## Examples
   [1-3 concrete input/output pairs]

   ## Constraints
   - [Explicit boundary]
   - [Explicit boundary]
   ```

3. **Design tools alongside the prompt, not after.** Each tool: one purpose, self-contained parameters, a description that states both what it does and when to call it. Check for overlap between tools before finalizing.

4. **Run the review checklist** (see main SKILL.md) before presenting the draft.

5. **State assumptions explicitly.** If you filled gaps (e.g., default timezone, default duration), call them out in one line so the user can correct them.
