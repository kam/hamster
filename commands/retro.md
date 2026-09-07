---
description: Retrospective on the current session — prompting, tooling, context, errors — routed into durable fixes (rule, skill, CLAUDE.md, memory). The manual counterpart of the error-retro Stop hook.
---

You are conducting a retrospective on the **current Claude Code session**. Your goal is to help the user become a more effective collaborator with you, and to help yourself work more efficiently through better skills, memory, and instructions. Be candid and specific — generic advice is useless.

## Step 1 — Usage numbers (optional)

If `~/.claude/scripts/session-stats.py` exists, run it via Bash and show its stdout verbatim first. If it is absent or fails, skip this step in one line and continue — the qualitative review does not depend on it.

## Step 1b — What the loop already knows

- `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rules.py list` — rules already enforcing lessons; do not re-propose one.
- `cat ~/.claude/hamster/session-errors/<session_id>.jsonl 2>/dev/null` — this session's failed tool calls (the `error-retro` hook's source). If the file is absent, use the `is_error` tool results you can see.
- `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/summarize.py cluster < ~/.claude/hamster/session-errors/<session_id>.jsonl` — free root-cause grouping from the on-device model when built (exit 3 otherwise); treat as a draft.
- When `navigator` is on PATH: `navigator search "<top error cause>" --type solutions --limit 5` — lessons other projects already paid for.

## Step 2 — Review the conversation

Look back over the entire session so far. Pay attention to:

- The user's prompts (initial framing, follow-ups, corrections, clarifications)
- Your own tool calls (which tools, how many, in what order, parallel vs sequential, any cutoffs)
- Agent invocations (which agents, how they were prompted, whether they hit transcript cutoffs, whether they returned useful output)
- Context usage (re-reads of the same file, redundant searches, places where memory or prior tool results would have answered the question)
- Error recovery (failed commands, retries, escalations, places you got stuck or guessed instead of asking)
- Memory and skill usage (did you load relevant memory at the start? did you use the right skill? did you skip a skill that should have triggered?)

Do NOT just describe what happened — analyse it. Each observation should answer "what was suboptimal and why."

## Step 3 — Produce a structured review

Output the review in this exact format. Be concise — bullets, not paragraphs. Concrete examples from the actual session, not hypotheticals.

### 1. Prompting feedback (for the user)

Specific things the user could have done to get better results faster. Examples:
- Ambiguity in the initial request that caused rework
- Missing constraints that would have narrowed scope
- Information the user had but didn't share until later
- Places where the user had to correct you that an upfront constraint would have prevented
- Places where the user gave perfect prompts — call those out too, so they keep doing it

If the user prompted well throughout, say so. Do not invent criticism.

### 2. Tooling issues

- Tools you reached for that were wrong, redundant, or inefficient
- Agents that hit transcript cutoffs (and why — almost always prompt discipline)
- Parallelisation you missed (independent tool calls that ran sequentially)
- Bash commands where a dedicated tool would have been better
- Skills that should have been invoked but weren't, or vice versa

### 3. Context usage

- Files you read more than once unnecessarily
- Searches that returned more than you needed (missing `head_limit`, too-broad globs)
- Information that was already in memory or CLAUDE.md but you re-derived
- Places where loading less context up front would have left more room later

### 4. Error handling

- Failures and how you recovered
- Places you guessed instead of using `AskUserQuestion`
- Places you retried the same failing approach instead of changing strategy
- Places you correctly escalated — call those out

### 5. Proposed improvements

For each issue above that has a durable fix, **decide where it belongs before you write the proposal**. Routing comes first — a good fix in the wrong place is either dead weight (bloats unrelated sessions) or under-reach (re-learned in every project). Do not default to project memory; justify the destination.

**Routing decision (run this per fix, before drafting):**
1. **Transferable across projects, or specific to this one?** Cross-project → a command/skill/agent definition or global CLAUDE.md. Project-specific → project CLAUDE.md or project memory.
2. **Behavior or fact?** A rule about *how to run a recurring task* belongs in the command/skill/agent that runs it, so it actually fires — not in passive memory. A fact to recall belongs in memory/CLAUDE.md.
3. **Don't over-elevate.** A narrow, project-bound technique does NOT belong in global CLAUDE.md or a general skill just because it's reusable in principle — global loads into every unrelated session, and a niche addition bloats a general skill. Elevate only when the fix genuinely fires across projects; otherwise keep it project-scoped and say why.

Pick exactly ONE target per fix. **First ask: can a hook catch this without the model?** A command shape, a path, a flag, a file that must not be edited — anything a regex can see is a rule, and a rule never has to be remembered.

- **A rule** (`/hamster:promote`) — deterministic guard with keep-tests; project scope when the lesson is repo-bound, user scope when it travels
- **A command** (`~/.claude/commands/<name>.md`) — when the fix changes how a slash-command workflow should behave
- **A skill** (e.g. `~/.claude/skills/fact-checker/SKILL.md`, or a plugin skill like `~/Projects/smile/multiply-plugins/dev-lead/skills/tech-lead/SKILL.md`) — when the fix changes a skill's procedure; name the section to edit
- **An agent** (agent definition file) — when the fix changes how a specific subagent should be prompted or behave
- **Global CLAUDE.md** (`~/.claude/CLAUDE.md`) — passive cross-project rules
- **Project CLAUDE.md** (`<cwd>/CLAUDE.md`) — project-specific conventions/gotchas
- **Project auto-memory** (`~/.claude/projects/<project-slug>/memory/`) — feedback, user, project, or reference facts. Use the format from the auto-memory system prompt; add `decay_days: 120` under `metadata:` so `memory-prune` can retire it.
- **Navigator `solutions` node** — when the lesson recurred across projects and `navigator` is on PATH: `printf '<Why + How to apply>' | navigator insert --type solutions --title "<cause pattern>" --tags <a,b> --source-project "<repo>" --body - --actor agent:claude-code`. Never write the vault markdown directly.

Each proposal should have:
- **Target**: file path
- **Type**: rule / command / skill / agent / global CLAUDE.md / project CLAUDE.md / memory / solutions node
- **Scope rationale**: one line — why THIS destination over the alternatives (transferable vs project-bound; behavior vs fact). If you considered elevating to global/skill and rejected it, state the dead-weight trade-off.
- **Change**: a literal diff or precise description ("add this bullet under section X", "change line Y from … to …")
- **Why**: which session issue this resolves

If a fix is one-off or already covered by an existing rule, do NOT propose it. Quality over quantity — five excellent proposals beat fifteen mediocre ones.

## Step 4 — Ask the user which changes to apply

After presenting the review, use `AskUserQuestion` to ask the user which proposed changes they want applied. Include one option per proposed change plus an "All of them" option and a "None — I'll handle it myself" option. Use multiSelect if the tool supports it.

Wait for the user's selection.

## Step 5 — Apply approved changes

For each approved proposal:

- **Command / skill / agent / CLAUDE.md changes**: use the `Edit` tool. Read the file first if you haven't already this turn. Make the edit exactly as proposed — do not silently expand scope. If the proposal touches a command, skill, or agent outside the user's home directory (e.g. a plugin-provided one), warn the user the change may be overwritten by plugin updates.
- **Rules**: invoke `/hamster:promote <memory-name or text>`; it drafts, proves and installs the rule and refuses on a red test.
- **Memory writes**: follow the two-step memory process from the auto-memory system prompt — write the memory file with frontmatter, then add a one-line entry to `MEMORY.md`. Check whether an existing memory should be updated instead of creating a duplicate.
- After applying, report what was changed in a brief summary (file paths only, not full diffs).

Do NOT apply changes that the user did not approve. Do NOT apply changes silently. Do NOT add improvements you thought of after the AskUserQuestion step — surface them in a follow-up question or ignore them.

## Constraints

- This command is a retrospective, not a continuation of the prior task. Do not resume any in-progress work.
- Do not flatter. If the session was genuinely smooth, a short review is the right answer.
- Do not propose changes the user explicitly rejected earlier in the same session.
- Memory writes must follow the format in the auto-memory system prompt: own file with frontmatter, plus one-line index entry in `MEMORY.md`.
- `~/.claude/scripts/session-stats.py` is a local convenience, not part of this plugin.
- If you discover the session had no meaningful issues to learn from, say so plainly and skip Step 3.
