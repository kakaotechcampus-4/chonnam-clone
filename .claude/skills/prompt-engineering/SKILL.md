---
name: prompt-engineering
description: Use this skill whenever the user wants to create, review, or optimize a system prompt, agent instructions, or tool/function definitions for any AI agent (Claude, OpenAI, or other LLM platforms). Applies Anthropic's context engineering principles — signal-to-noise optimization, progressive disclosure, and structured markdown — to make prompts and tool schemas more effective. Trigger this for requests like "이 프롬프트 최적화해줘", "system prompt 만들어줘", "tool description 다듬어줘", or any agent-design task involving prompts or tool definitions.
---

# Prompt Engineering Skill

A self-contained skill for creating and optimizing system prompts, agent instructions, and tool definitions. No external services, hooks, or network calls — pure guidance applied directly to the text you produce.

## Core Philosophy

Context engineering is the practice of curating the smallest possible set of high-signal tokens that maximizes the likelihood of the desired outcome from an LLM.

Every token in a prompt competes for a limited "attention budget." Performance degrades as irrelevant or redundant tokens accumulate — so treat context as a scarce resource, not free real estate.

## Key Principles

**1. Context is finite.** Cut anything that doesn't change the model's behavior. If a sentence could be deleted without changing what the agent does, delete it.

**2. Optimize signal-to-noise.** Prefer direct imperatives over hedged suggestions. Remove overlapping or repeated instructions.

**3. Progressive disclosure.** Don't front-load every detail. Give the agent lightweight references (IDs, tool calls, file paths) and let it pull details just-in-time.

## Structure Standard

Organize any prompt into these semantic sections, in this order:

```markdown
## Background Information
Minimal essential context — what and why, not how it evolved.

## Instructions
Imperative, specific, ordered by priority.

## Examples
2-3 concrete input/output pairs. Show, don't tell.

## Constraints
Explicit boundaries, what NOT to do, success/failure criteria.
```

Omit any section that isn't needed — an empty "Background" header is noise.

## Writing Style Rules

| Instead of | Write |
|---|---|
| "You should always make sure to validate input before processing, because invalid input could cause problems." | "Validate input before processing." |
| "You might want to consider using the calculate_tax tool if you need tax amounts." | "Use `calculate_tax(amount, jurisdiction)` for tax calculations." |
| A paragraph of requirements | A bulleted list of requirements |

Ban hedge words in instructions: *might, could, should consider, perhaps*. State the rule directly.

## Tool / Function Definition Rules

- **Single purpose per tool.** `calculate_shipping_cost(origin, destination, weight, service_level)` — not `process_order(order_data)`.
- **Self-contained.** Include every parameter the tool needs; don't rely on the agent inferring hidden state.
- **Structured errors.** Tools should return errors the agent can act on, not raw stack traces.
- **No overlapping tools.** If two tools could both handle a request, merge them or sharply differentiate their descriptions.
- Each tool's `description` field should say what it does AND when to call it — that's the model's only signal for tool selection.

## Context Management for Longer Agents

- **Just-in-time loading:** replace full data dumps with a lookup tool + a short list of IDs.
- **External state:** for multi-step tasks, persist state outside the context window (files, DB) and reference it by ID rather than repeating it every turn.
- **Sub-agents:** split complex tasks so each sub-agent gets only the minimal context it needs, and the parent synthesizes results.

## Anti-Patterns

Reject these on sight, in your own drafts and in prompts you're asked to review:

- Verbose justification for every instruction
- Historical/background dumps not needed for the task
- Overlapping tool definitions
- Loading full data before it's needed
- Vague, hedged instructions
- More than 2-3 examples for a simple pattern

## Workflows

Two concrete workflows are provided as reference files — read the relevant one when the user's request matches its trigger:

- `references/create-prompt.md` — building a new system prompt or tool set from scratch
- `references/optimize-prompt.md` — tightening an existing prompt or tool set

## Review Checklist

Before finalizing any prompt or tool definition, confirm:

- [ ] Semantic markdown sections, none empty
- [ ] No hedge words in instructions
- [ ] No redundant or overlapping statements
- [ ] Every tool has one clear purpose and a selection-relevant description
- [ ] Examples are concrete and minimal (2-3, not 10)
- [ ] Constraints are explicit, not implied

## Source

Adapted from Anthropic's "Effective Context Engineering for AI Agents": https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
