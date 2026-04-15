# 09 — PITFALLS & TRAPS

Known mistakes, scope creep patterns, and process violations. Read this BEFORE starting any new work.

---

## The Big 5 Mistakes (That Actually Happened)

### 1. The GLM-5 Website Incident
**What happened**: GLM-5 Full-Stack built a Next.js showcase website (15,574 lines) during Plan Mode, when "no coding before Combined Master Plan" was the rule.
**Why it happened**: "Usual habits" — implementing is more fun than planning.
**Result**: Speci said "cool presentation frontpage but no plan and backend at all." 1,300+ lines of implementation logs polluted the Review 3 document.
**Lesson**: If the directive says Plan Mode, plan. Don't sneak in implementation. If you can't resist building, ask for a separate track first.
**Fix applied**: GLM-5 reassigned to backend/data-layer work. Website frozen.

### 2. The MiMo CLAW Scope Explosion
**What happened**: MiMo CLAW interpreted Speci's compliance answer as a mandate to add SQLCipher, Chroma Lite, RBAC, and connection pooling to Phase 1. Deliverable list went from 13→24 items.
**Why it happened**: Answer interpretation as scope change — "compliance = encryption = SQLCipher" chain.
**Result**: Doubled MVP surface area. Directly contradicted unanimous consensus to defer encryption to Phase 2.
**Lesson**: Speci's answers to open questions are about APPROACH DIRECTION, not SCOPE EXPANSION. "Satisfy GDPR and HIPAA" means "design for compliance" not "add encryption now."
**Fix applied**: Explicitly rejected in master plan freeze.

### 3. The Document Bloat Spiral
**What happened**: Review 3 grew to 8,579 lines (2.4x Review 2, 3.4x Review 1). The 8 open questions appeared 6+ times. The 14 gap resolutions repeated 8+ times. "Awaiting combined master plan" appeared 15+ times.
**Why it happened**: Every agent restated everything from scratch rather than cross-referencing.
**Result**: 3x necessary length. Contradictory versions of the same information. Real risk of confusion about what's authoritative.
**Lesson**: The master plan is ONE document, ~30KB, zero duplication. Everything else references it.
**Fix applied**: QWEN's recommendation adopted — single canonical document.

### 4. The Quantized Routing Ghost
**What happened**: A "quantized coordination model" appeared in Phase 3 of every roadmap. No agent ever specified its architecture, training data, latency targets, or accuracy benchmarks.
**Why it happened**: Sounds impressive, feels like forward-thinking, everyone included it because everyone else did.
**Result**: Speculative R&D distraction with no substance.
**Lesson**: If you can't specify the architecture, training data, and benchmarks — it doesn't belong on the roadmap.
**Fix applied**: Removed entirely. If rule-based routing shows limitations after Phase 2, evaluate ML routing then.

### 5. The Agent Grading Theater
**What happened**: Multiple agents assigned letter grades (A-, B+, B) to other agents' contributions.
**Why it happened**: Feels rigorous, looks like quality control.
**Result**: QWEN correctly identified: "Grades are subjective, not reproducible, and do not improve the architecture."
**Lesson**: Use concrete evidence, not subjective scores. "Agent X identified 3 gaps that Agent Y missed" is useful. "Agent X gets an A-" is not.
**Fix applied**: Grades removed from canonical documentation.

---

## Scope Creep Patterns (Watch For These)

| Pattern | Example | How to Catch It |
|---------|---------|-----------------|
| **Answer interpretation** | "Compliance" → "Add SQLCipher" | Ask: "Did Speci say add this, or did I infer it?" |
| **Everybody included it** | Quantized routing in Phase 3 | Ask: "Can anyone specify the architecture?" |
| **Research citation creep** | "Paper X says we need Y" | Ask: "Is this MVP scope or Phase 2 scope?" |
| **Feature envy** | "Agent Z's system has this feature" | Ask: "Is this in the locked MVP list?" |
| **Incremental expansion** | 13 → 15 → 18 → 24 items | Track count. If it grows >10%, flag it. |

---

## Process Violations (Don't Repeat)

| Rule | What Happens If Broken |
|------|----------------------|
| No coding in Plan Mode | GLM-5 website incident — corrective reassignment |
| Don't expand scope without vote | MiMo CLAW 13→24 — explicitly rejected |
| One canonical document | Bloat to 8,579 lines — confusion about authority |
| No grades in docs | Subjective noise — removed |
| Respect locked decisions | SQLCipher in Phase 1 — contradicted consensus |
| Cross-reference, don't repeat | 8 questions × 6+ repetitions = 3x bloat |

---

## Anti-Patterns in Agent Collaboration

| Anti-Pattern | Symptom | Fix |
|--------------|---------|-----|
| **Echo chamber** | Everyone agrees but nobody specifies details | Ask for concrete specs |
| **Scope laundering** | Change scope by reinterpreting answers | Read Speci's literal words |
| **Premature optimization** | Building for Phase 3 in Phase 1 | Check the locked MVP list |
| **Analysis paralysis** | More reviews, more agents, more debate | CODEX voting gate — vote and move |
| **Implementation wanderlust** | Can't resist building things | Strict Plan Mode enforcement |

---

## Golden Rules (From Hard Lessons)

1. **Read the locked MVP list before proposing anything.** If it's not on the IN list, propose it — don't implement it.
2. **Speci's words are literal.** Don't infer scope changes from approach statements.
3. **One document to rule them all.** The master plan is canonical. Everything else references it.
4. **Plan Mode means Plan Mode.** No sneaking in implementation.
5. **If you can't specify it, don't include it.** "Sounds good" is not a specification.
6. **Cross-reference, don't restate.** If Agent X already said it, cite Agent X.
7. **Security is non-negotiable. Performance is a target.** Don't sacrifice safety for speed.
8. **Vote, then build.** Architecture convergence ≠ implementation readiness.
