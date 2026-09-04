# CLIP FINDER PROMPT (verbatim from the playbook)

Paste campaign rules + the approved transcript into this prompt on claude.ai. Goal: locate complete mini-stories you can verify in the raw footage — **not** to generate viral clips.

---

```
I have permission from the campaign owner to use the transcript below. Act as a senior short-form editor.

Find 12 candidate clips. Return a table with:
- Exact source start/end timestamps. Do not invent them.
- Verbatim first line that could open the short.
- The viewer question / curiosity gap.
- Setup → tension → payoff.
- Best emotion: surprise, conflict, utility, awe, humour, status, or relief.
- One fact-risk item to verify in the original footage.
- One materially useful value-add: a short voiceover, context graphic, sourced comparison, or framing question.
- A score out of 10. Reject weak soundbites with no payoff.

Rules:
- Prioritise 20–45 seconds unless a longer story is necessary.
- Do not write claims that are not in the source.
- Do not use a clip if the viewer needs too much missing context.

Campaign rules:
[PASTE RULES]

Transcript:
[PASTE APPROVED TRANSCRIPT]
```

---

### How to use it

1. Only run it on transcripts you have permission to use (approved campaign assets).
2. Fill in `[PASTE RULES]` from your campaign sheet (`playbook/03-workflow.md`, Step 1).
3. Paste the approved transcript after `[PASTE APPROVED TRANSCRIPT]`.
4. Treat the output as a **shortlist to verify** — never as ready-to-post clips. See Step 4 of the workflow.
