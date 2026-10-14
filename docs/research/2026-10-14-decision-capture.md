---
date: 2026-10-14
question: How do AI practitioners keep decision records from agent sessions (incl. pasted client emails), and how do we build it into hamster/dev-lead?
status: built — hamster 0.7.0 (feature/decision-log)
---

# Decision capture — research digest

## Findings

1. **A committed decisions file is the most common pattern.** Fields converge on Decision / Why / Rejected, plus a read-first instruction in CLAUDE.md/AGENTS.md. Independent implementations: spec-kit `research.md` (Decision / Rationale / Alternatives considered, https://raw.githubusercontent.com/github/spec-kit/main/templates/commands/plan.md), Engincan Veske's decision-log.md (Chose / Why / Rejected, https://engincanveske.substack.com/p/decision-log-md-gives-your-ai-sessions-memory), whyline `.whyline/decisions.md` (https://pypi.org/project/whyline/), Roo Memory Bank `decisionLog.md`, BMAD community skill. Cline's official Memory Bank has no decision log (https://docs.cline.bot/best-practices/memory-bank).
2. **Agents skip reading it.** whyline measured Claude Code running the start-of-session brief in 3 of 7 sessions. Veske reports the model re-suggesting rejected options. Fix: inject, don't instruct.
3. **Supersede, never edit.** ADR/adr-tools `Superseded by`, MADR 4.0.0 (`status, date, decision-makers, consulted, informed`, https://adr.github.io/madr/), Graphiti bi-temporal `invalid_at`, decisionlog.ai supersession. Counters "ghost context": stale and current versions returned with equal weight (https://tianpan.co/blog/2026-05-05-ghost-context-agent-memory-contradictory-beliefs). Claude Code docs: with contradictory instructions "Claude may pick one arbitrarily" (https://code.claude.com/docs/en/memory).
4. **Agent proposals stay apart from human decisions.** Viola's schema: Decision / Decided by / Status / Ends when / Replaces; agent inferences are proposals until a person approves (https://dev.to/oaleviola/decision-records-for-ai-agents-how-to-keep-what-the-team-decided-from-being-forgotten-2li4). decisionlog.ai: `DecisionCandidate` awaits review; records carry Actor, DecisionSource, SourceContent (https://www.decisionlog.ai/, vendor).
5. **After-the-fact transcript LLM extraction is lossy and fragile.** claude-mem (≈100k stars) issues are mostly infrastructure: worker liveness, migrations, quota stalls (https://github.com/thedotmack/claude-mem). Zenn author: raw transcripts are "too much noise"; keep user/assistant text only, last 200 lines, 20KB cap (https://zenn.dev/ryuka_lucas/articles/1e50ed03029b49?locale=en).
6. **No published agency practice links a pasted client email to a repo decision record.** PM decision logs (RAID) carry ID, date, decision maker, rationale, alternatives, status, review date. Agency guidance: name the approver and exact version; email approvals drift (https://skedsocial.com/blog/how-to-build-an-agency-approval-process-that-survives-15-clients.md).
7. **Context files cost tokens.** ETH Zurich: repo context files raise inference cost >20% without general success gains (https://arxiv.org/abs/2602.11988) — about overviews, not decision logs; still argues for a capped, active-only injection.

## Claude Code mechanics (https://code.claude.com/docs/en/hooks, read 2026-10-14)

- **UserPromptSubmit** sees the full prompt with pastes expanded inside `<pasted_content id=…>` markers — a hook can cut the paste out exactly. Can inject `additionalContext`; cannot rewrite the prompt. 30 s timeout. A `type: prompt` hook here that returns `ok:false` ends the turn — unusable as a pass-through classifier.
- **Stop** gets `stop_hook_active`, `last_assistant_message`. `decision: block` + `reason` keeps Claude working. Claude Code overrides after 8 consecutive continuations.
- **SessionEnd**: output discarded, 1.5 s default budget — no LLM extraction there.
- **PreCompact**: command hooks only.
- Auto memory is model-discretionary: "Claude doesn't save something every session." Not a decision log.

## Injection and provenance

- A pasted email is third-party text in the user turn — the riskiest channel. Delimiters alone are weak (Spotlighting, https://arxiv.org/abs/2403.14720; Gemini defences, https://arxiv.org/pdf/2505.14534).
- Practice: a deterministic hook stores the raw source with its SHA-256 before the model acts; the record quotes the decisive lines and cites path + hash; the record never triggers actions.

## What already exists in multiply-plugins

- Gated decision tables: product-discovery `docs/product/DECISIONS.md` (+ `decision-guard.py`: person, channel, date), design-skills `DECISIONS.md`/`decisions.json`, course-design `GATE_STATE.md`, marketing artifact `Decisions` section (Date | Decision | Why | Supersedes).
- dev-lead `ask-ledger.py` logs every AskUserQuestion answer to `~/.claude/dev-lead/ask-ledger.<host>.jsonl`.
- hamster: handoff Decisions section, PreCompact snapshot, `_common.redact()` secret scrubber.
- Gap: nothing captures a decision made in open chat or arriving as a pasted email.

## UNVERIFIED

Kiro steering file names; Agent OS decisions.md; RooFlow entry fields; CommitLore; adr-skills Stop-hook behaviour; Recall (repo 404); bonkey decision-log skill's ExitPlanMode trigger; `additionalContext` size cap.

## Audit log

- 2026-10-14 created from three research agents (practitioner patterns, hook mechanics, local inventory).
- 2026-10-14 Kam decided: raw sources gitignored ("in case there are sensitive history"); v1 is repo file only, no Navigator node. Asked how oversized logs avoid polluting context → answered with load caps, archive, sources read on demand. Built as hamster 0.7.0.
