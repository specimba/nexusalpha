# 05 — TOOLS & SKILLS REFERENCE

What tools were used, how to use them, and what's available.

---

## Deliverable Generation

### PDF Generation
- **Tool**: Python scripts with reportlab or similar
- **Pattern**: Generate Python script → sanitize → execute → output PDF
- **Used for**: Nexus_OS_A2A_Review2_Coverage_Report.pdf
- **Speci's preference**: DON'T use. Speci rejected PDFs.

### PPTX Generation
- **Tool**: html2pptx skill — generates PowerPoint from HTML slides
- **Pattern**: Create HTML slide files → run conversion script → .pptx output
- **Used for**: Nexus_OS_A2A_Review2_Coverage_Report.pptx (19 slides)
- **Speci's preference**: Only when explicitly asked

### Text Reports (PREFERRED)
- **Format**: Markdown or plain text, copy-paste ready
- **No external files** — output directly in chat
- **Structure**: H1 sections, tables with | separators, proof-level tags
- **This is what Speci wants.**

---

## Research & Analysis

### Web Search
- **Skill**: `mimo-web-search` — real-time web search
- **Used for**: arXiv papers, technical research, A2A protocol specs
- **Key sources found**: SkillX (arXiv:2604.04804), MIA (arXiv:2604.04503), eTAMP, MCFA, ZeroClaw, Zvec, A2A v0.3, AgentSocialBench

### File Reading
- **Pattern**: Read uploaded files line by line when "reading limitations OFF"
- **Used for**: Review documents (2,500-8,500 lines each)
- **Cross-referencing**: grep for key terms, count occurrences, map agent contributions

### Git
- **Used for**: Backup tags before major phases, commit snapshots
- **Pattern**: `git add . && git commit -m "backup" && git tag pre-phase2`

---

## Testing

### Test Framework
- **488 tests passing** (316 pre-Phase1 + 172 Phase 1)
- **Pattern**: pytest-style, run before and after every change
- **Regression check**: `0 regressions` is a hard requirement
- **New tests run immediately** after writing — verify pass before proceeding

### Test Runner
- Execute: `python -m pytest` or equivalent
- Always run full suite, not just new tests
- Report: passed/failed/regressions count

---

## Implementation Patterns

### Code Style
- Python (primary), TypeScript (secondary)
- SQLAlchemy/Prisma for database
- JSON-RPC 2.0 for inter-agent protocol
- SQLite as primary storage (WAL mode)

### File Structure (Nexus OS)
```
nexus/
├── bridge/          # Pillar I — MCP+ communication
│   ├── protocol.py
│   └── headers.py
├── vault/           # Pillar II — S-P-E-W memory
│   ├── session.py
│   ├── episodic.py
│   ├── semantic.py
│   ├── wisdom.py
│   ├── search/rrf.py      # Phase 2
│   └── trust/provenance.py # Phase 2
├── engine/          # Pillar III — DAG orchestration
│   ├── executor.py
│   ├── heartbeat.py
│   └── router.py
├── governor/        # Pillar IV — Policy & safety
│   ├── isolation.py
│   ├── audit.py
│   └── poisoning.py       # Phase 2
├── db/
│   └── manager.py
├── tests/
│   ├── security/
│   └── integration/
└── worklog.md       # Ground truth
```

---

## Backup & Restore

### Backup Pattern
1. Git commit with descriptive message
2. Git tag (e.g., `pre-phase2`)
3. Filesystem backup (tar.gz of project directory)
4. Update worklog.md

### Restore Pattern
1. Read starter-pack files (this directory)
2. Check git log for latest commit
3. Read worklog.md for latest state
4. Run test suite to verify integrity
