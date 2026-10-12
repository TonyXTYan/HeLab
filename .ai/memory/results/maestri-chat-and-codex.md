---
date: 2026-10-12
status: settled
---
Maestri Chat routing, command approvals and Codex chat context are separate concerns.

## Replies and approvals

- For a message carrying the Maestri Chat header, load the `maestri-chat` skill and reply only through `maestri say`; ordinary terminal output does not reach that chat. Use `--progress` for updates, and do not duplicate a delivered answer in the terminal.
- Prefer a directly shell-quoted message argument, or `maestri say --file PATH` for an existing UTF-8 reply file. Quote literal text safely: never interpolate unescaped backticks, `$()` or other shell expansions. Do not use heredoc/here-string redirection for routine replies when relying on a command-prefix allow rule.
- Codex treats advanced shell syntax, including redirection, as a shell-wrapper invocation rather than matching the inner command alone. A `maestri` prefix rule therefore does not necessarily auto-approve `maestri say <<'EOF' ... EOF`. Do not respond by broadly allowing arbitrary shell wrappers.
- On 2026-10-12, `~/.codex/rules/default.rules` already contained `prefix_rule(pattern=["maestri"], decision="allow")`; `codex execpolicy check` returned `allow` for a plain `maestri say` command. Plain quoted replies succeeded without further approval, whereas heredoc replies needed escalation after `Operation not permitted`. Recheck the live rules if this changes; adding a redundant `maestri say` rule will not fix heredoc handling.

## Routing and history

- Use `maestri` from PATH. Run `maestri list` to determine the current `You:` identity and exact connected-agent names before messaging peers. Check `MAESTRI_TERMINAL_ID` live when diagnosing routing; never assume an old terminal number or ID is current.
- Never claim delivery unless the CLI confirms it. Report a failed connection plainly rather than treating prepared terminal text as a delivered chat reply.
- Maestri keeps seven color threads per terminal. Read `maestri recall <color>` on the first message, a color change, or after a restart/replacement/compaction. Default recall is the last 10 turns; request more only when needed.
- Maestri Chat history is retrievable history, not a complete Codex tool transcript or automatically loaded model context. Direct terminal exchanges may be absent. Switching color does not itself reset the active Codex conversation.
- Recommended workflow from this discussion: retain Maestri terminal/chat history; continue or resume the same Codex chat for related work; use `/new` for an independent task, explicitly stating the new objective. Use `/compact` to summarize a long ongoing task, `/resume` to return to saved work, and `/fork` to explore an alternative with inherited context. Enter these commands in the Codex terminal. New concurrent agents can use separate terminals.

## Sources

- Local skills: `/Users/tonyyan/.agents/skills/maestri/SKILL.md` and `/Users/tonyyan/.agents/skills/maestri-chat/SKILL.md`; live `maestri help` and `maestri recall --help`.
- [OpenAI command approval rules](https://learn.chatgpt.com/docs/agent-configuration/rules), especially shell wrappers and redirection.
- [OpenAI Codex commands](https://learn.chatgpt.com/docs/developer-commands) and [project/chat guidance](https://learn.chatgpt.com/docs/projects).
