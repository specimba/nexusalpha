# C5 INTEGRATION EVIDENCE
**Generated**: 2026-04-16T04:44:07Z
**Gate Status**: [PASSED]
**Execution Time**: 19.47s
**Branch**: `main`
**Target Tag**: `m3-hardened`

## Test Summary
| Metric | Value |
|---|---|
| **Passed** | 450 |
| **Failed** | 0 |
| **Duration** | 19.47s |

## Verified Surfaces (CODE_CONFIRMED)
| Component | File | Verification Target |
|---|---|---|
| Bridge Token Headers | `bridge/server.py` | x-nexus-input-tokens present |
| Governor Hard-Stop | `governor/base.py` | TokenGuard.check() enforced |
| Trust Hot-Path | `vault/trust.py` | get_score_hotpath() O(1) |
| VAP Audit Chain | `governor/proof_chain.py` | SHA-256 chain valid |

## Gate Decision
[PASSED]
