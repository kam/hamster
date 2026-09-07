---
description: Point hamster's local-model slot at whatever you run — oMLX, LM Studio, Ollama, llama.cpp, or any OpenAI-compatible server — and pick a fast and a quality model. Saved in ~/.claude/hamster/config.json; keys are never stored.
argument-hint: [detect | show | test | clear]
---

The local-model slot drafts summaries, error clusters and the "worth remembering?" verdict at zero API tokens. Order: configured server → Apple on-device (macOS 26+) → the in-session model. This command sets the server part.

## With an argument

`$ARGUMENTS` = `detect`, `show`, `test` or `clear` → run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lm.py $ARGUMENTS` and show the output. Done.

## Without an argument: setup

1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lm.py detect --json`. It probes oMLX (:8000), LM Studio (:1234), Ollama (:11434) and llama.cpp (:8080) and lists the models each serves. If none answer, say so, name the four defaults, and stop — the user starts their server and reruns. A custom URL can be passed straight to `lm.py set --url`.
2. `AskUserQuestion`, up to three questions, only for what detect could not decide:
   - which server (skip when exactly one answered);
   - **fast** model — yes/no and short labels; the smallest served model that is not an embedding/speech model (name it as the recommended option);
   - **quality** model — summaries and clustering; the largest served model (recommended). One model for both is fine.
   Show model ids exactly as served. Do not ask about API keys: oMLX's key path is filled in by detect; LM Studio, Ollama and llama.cpp need none. If the server later returns 401, tell the user to rerun with `--api-key-env <VAR>` or `--api-key-file <file>#<dotted.path>` — never paste a key into the command or the config.
3. Write it:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lm.py set --url <url> --fast <id> --quality <id> [--api-key-file <ref>] [--extra '{"chat_template_kwargs":{"enable_thinking":false}}']
   ```
   Add the `--extra` thinking-off flag for Qwen 3.x models on oMLX/llama.cpp (thinking tokens slow a 0.4 s verdict to 10 s). The command refuses when the server does not answer or a model is not served — fix and rerun, do not edit the JSON by hand.
4. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lm.py test` and show the two round-trips. Report in three lines: server, fast/quality models, and that Apple on-device (if present) remains the fallback.

Evidence for the tiering: `evals/haiku-vs-afm/REPORT.md` in the claude-settings repo — a 35B-A3B MoE gives Haiku-level yes/no verdicts at Apple-model speed; a 27B dense model beat Haiku on session summaries.
