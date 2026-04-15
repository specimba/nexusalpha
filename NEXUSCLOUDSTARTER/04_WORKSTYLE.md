# 04 — WORKSTYLE (Speci's Preferences)

How Speci wants work delivered. Read this BEFORE producing any output.

---

## Format Rules

| Rule | Details |
|------|---------|
| **TEXT, NOT PDF** | Speci explicitly rejected PDF: "I do not need slides or a PDF. I want your detailed review in text format here for simple copy-paste purposes" |
| **Copy-paste ready** | Output must be directly usable — no "download this file" dependencies |
| **No slides** | "I did not want PDF" — text presentations, not PPTX unless specifically asked |
| **Markdown tables** | Preferred for comparisons, matrices, status |
| **Structured headings** | H1 for major sections, H2 for subsections — hierarchical and scannable |

## Communication Style

- **Be direct.** No filler. "Got it, here's the answer" not "That's a great question! I'd love to help!"
- **Show work.** Sources, cross-references, line numbers when citing.
- **Proof-level tags**: BLOCKED / ACHIEVED / PARTIAL / NOT_STARTED — mandatory for status reports
- **Grades are subjective.** QWEN correctly noted: "Grades have no engineering value. They are not reproducible." Use concrete evidence instead.

## Worklog Discipline

- **Always update worklog.md** after significant work
- Format: Date + What Was Done + Files Created/Modified + Proof Tags
- The worklog is the ground truth — it's the first thing read on boot

## Research Standards

- **Read ALL of the material.** "Reading limitations OFF" means every line.
- **Cross-reference agents.** Same claim across 3+ agents = high confidence signal.
- **Distinguish signal from noise.** Document duplication is noise. Unique architectural decisions are signal.
- **Proof-level tags**: BLOCKED (needs external artifact), ACHIEVED (verified), PARTIAL (working but incomplete), NOT_STARTED

## Scope Discipline

- **Never expand scope without explicit approval.** MiMo CLAW went from 13→24 items — this was a problem.
- **"Half the full plan" MVP boundary survived 3 review cycles.** Respect it.
- **If in doubt: propose, don't implement.** Let the collective vote on scope changes.

## Anti-Patterns (What NOT to Do)

| Anti-Pattern | Example from History | Why It's Bad |
|--------------|---------------------|-------------|
| Implement during Plan Mode | GLM-5 built website | Violated "no coding" directive |
| Expand via answer interpretation | MiMo CLAW 13→24 items | Scope creep through reinterpretation |
| Repeat what others said | 8 questions appearing 6+ times | 3x document bloat, no new info |
| Grade other agents | Letter grades (A-, B+) | Subjective, not reproducible |
| Propose speculative tech | Quantized routing in Phase 3 | No spec, no benchmarks, distraction |
| Ignore locked decisions | SQLCipher in Phase 1 | Contradicted unanimous consensus |

---

## Speci's Tone Preferences

- Casual-professional mix. Not corporate-speak.
- "Regards, speci" sign-off (consistent pattern)
- Emoji use: sparingly, for emphasis on status (✅ for locked/done, 🔍 for analysis)
- Respond in the language/dialect Speci uses (mixed Chinese-English context likely)

## Multi-Language Context

- The project has Chinese-speaking participants (GLM-5, Kimi, DeepSeek, QWEN)
- Chinese context may appear in agent outputs
- Keep deliverables in English unless Speci requests otherwise
