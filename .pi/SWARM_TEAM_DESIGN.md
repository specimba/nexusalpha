# NEXUS OS — Swarm & Team Coordination Design

**Version**: 3.0.0-beta  
**Date**: 2026-04-16  
**Author**: Pi Agent  
**Status**: DESIGN DOCUMENT

---

## Overview

NEXUS OS implements a **two-tier coordination system**:

1. **Swarm Layer** (`src/nexus_os/swarm/`) — Low-level worker pool management
2. **Team Layer** (`src/nexus_os/team/`) — High-level task dispatch and orchestration

```
┌─────────────────────────────────────────────────────────────┐
│                     TEAM LAYER                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TeamCoordinator                         │   │
│  │  • Task classification (Hermes)                     │   │
│  │  • Memory lookup (Mem0)                             │   │
│  │  • Skill matching                                   │   │
│  │  • Worker selection                                 │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    SWARM LAYER                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  Foreman                             │   │
│  │  • Worker registration                              │   │
│  │  • Heartbeat monitoring (15min)                     │   │
│  │  • Health checks                                    │   │
│  │  • Dead worker cleanup                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Worker 1 │  │ Worker 2 │  │ Worker 3 │  │ Worker N │   │
│  │ (GLM-5)  │  │ (GLM-5)  │  │ (GLM-5)  │  │ (GLM-5)  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Swarm Layer

### Foreman (`swarm/foreman.py`)

**Purpose**: Worker pool management with heartbeat monitoring.

**Key Features**:
- Worker registration/deregistration
- 15-minute heartbeat interval
- 2 missed heartbeats = unhealthy
- 4 missed heartbeats = removal
- Round-robin task distribution
- Thread-safe worker registry

**Configuration**:
```python
Foreman(
    foreman_id="foreman-1",
    max_workers=5,           # Maximum workers in pool
    heartbeat_interval=900,   # 15 minutes
    missed_heartbeats_threshold=2  # Unhealthy after 2 misses
)
```

**State Model**:
```
Worker Lifecycle:
  register_worker() → HEALTHY
         │
         ▼ (heartbeat missed ×2)
      UNHEALTHY
         │
         ▼ (heartbeat missed ×4)
      REMOVED
         
         │ (heartbeat received)
         ▼
      HEALTHY (recovery)
```

**Thread Safety**:
```python
# All state changes are protected by threading.Lock
self._lock = threading.Lock()

def register_worker(self, agent_card):
    with self._lock:
        # State mutation
        self._workers[worker_id] = WorkerStatus(...)
```

### Worker (`swarm/worker.py`)

**Purpose**: Individual worker implementation.

**Key Features**:
- Heartbeat emission
- Task execution
- Result reporting
- Graceful shutdown

---

## Team Layer

### TeamCoordinator (`team/coordinator.py`)

**Purpose**: High-level task dispatch and orchestration.

**Dispatch Pipeline**:

```
┌──────────────────────────────────────────────────────────────┐
│                    DISPATCH PIPELINE                         │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. RECEIVE TASK                                            │
│     │   dispatch(task_description, context)                  │
│     ▼                                                        │
│  2. MEMORY LOOKUP (Mem0)                                    │
│     │   Query mem0 for relevant past experience             │
│     │   Returns: List[MemoryRecord]                         │
│     ▼                                                        │
│  3. TASK CLASSIFICATION (Hermes)                            │
│     │   domain, complexity = hermes.classify(task)          │
│     │   Returns: (TaskDomain, TaskComplexity)               │
│     ▼                                                        │
│  4. SKILL MATCHING                                          │
│     │   Check skill registry for fast-path                  │
│     │   If match: route to skill worker                     │
│     ▼                                                        │
│  5. WORKER SELECTION                                         │
│     │   Select worker based on:                             │
│     │   - Availability (no in_progress task)                │
│     │   - Specialization (domain match)                     │
│     │   - Trust score (Hermes)                              │
│     │   - Load (fewest active tasks)                        │
│     ▼                                                        │
│  6. TASK FILE CREATION                                       │
│     │   Create .task.md in worker's pending queue           │
│     │   Format: YAML frontmatter + task body                │
│     ▼                                                        │
│  7. MONITORING                                               │
│     │   Poll worker's done/failed queue                     │
│     │   Timeout: STALL_THRESHOLD (10 minutes)               │
│     ▼                                                        │
│  8. OUTCOME RECORDING                                        │
│     │   Update Hermes experience scores                      │
│     │   Write to Mem0 (success/failure learning)            │
│     │   Update worker stats                                  │
│     ▼                                                        │
│  9. RETURN RESULT                                            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**WorkerProfile Data Structure**:
```python
@dataclass
class WorkerProfile:
    worker_id: str
    agent_dir: Path
    specializations: List[str]  # ["code", "analysis"]
    stats: Dict[str, int]       # {completed, failed, stalled}
    trust_score: float          # 0.0 to 1.0
    available: bool
    
    @property
    def pending_queue(self) -> Path:
        return self.agent_dir / "tasks" / "pending"
    
    @property
    def done_queue(self) -> Path:
        return self.agent_dir / "tasks" / "done"
    
    @property
    def failed_queue(self) -> Path:
        return self.agent_dir / "tasks" / "failed"
```

**Task File Format** (`.task.md`):
```markdown
---
task_id: task-abc123
created_at: 2026-04-16T10:00:00Z
source: coordinator
priority: high
domain: code
complexity: standard
assigned_to: glm5-worker-1
timeout_seconds: 600
context:
  project: nexus-os
  agent_id: foreman-1
---

# Task Description

Implement the TokenGuard integration into the Bridge layer.

## Requirements
1. Add token tracking to all JSON-RPC responses
2. Implement budget checking before request processing
3. Return appropriate error when budget exceeded

## Success Criteria
- [ ] Token headers added to responses
- [ ] Budget pre-check implemented
- [ ] 429 error returned when budget exceeded
```

---

## Integration Points

### Hermes ↔ TeamCoordinator

```python
class TeamCoordinator:
    def __init__(self, db, hermes: HermesRouter):
        self.hermes = hermes
        self.workers: Dict[str, WorkerProfile] = {}
    
    def dispatch(self, task_description, context):
        # Use Hermes for classification
        decision = self.hermes.route(
            task_id=str(uuid.uuid4()),
            description=task_description,
            context=context
        )
        
        # Select worker based on domain
        worker = self._select_worker(decision.domain)
        
        # Create task file
        self._create_task_file(worker, task_description, decision)
```

### Foreman ↔ TeamCoordinator

```python
class TeamCoordinator:
    def __init__(self, foreman: Foreman):
        self.foreman = foreman
    
    def get_healthy_workers(self) -> List[str]:
        return self.foreman.get_healthy_workers()
    
    def assign_task(self, task_id, worker_id):
        return self.foreman.assign_task(task_id, worker_id)
```

### Mem0 ↔ TeamCoordinator

```python
class TeamCoordinator:
    def __init__(self, mem0: Mem0Adapter):
        self.mem0 = mem0
    
    def dispatch(self, task_description, context):
        # Query relevant memories
        memories = self.mem0.search(
            query=task_description,
            agent_id="coordinator",
            limit=5
        )
        
        # Inject context
        context["relevant_memories"] = [m.content for m in memories]
```

---

## Scalability Considerations

### Current Limits

| Component | Limit | Reason |
|-----------|-------|--------|
| Workers per Foreman | 5 | Configurable (`max_workers`) |
| Heartbeat interval | 15 min | Trade-off: responsiveness vs overhead |
| Task timeout | 10 min | `STALL_THRESHOLD` |
| In-flight tasks | 1/worker | Single-task execution |

### Scaling Strategies

**1. Horizontal Scaling (Multiple Foremen)**:
```
┌─────────────────────────────────────────────────────────────┐
│                    Load Balancer                             │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
    ┌─────────┐         ┌─────────┐         ┌─────────┐
    │Foreman 1│         │Foreman 2│         │Foreman 3│
    │(code)   │         │(analysis)│        │(ops)    │
    └─────────┘         └─────────┘         └─────────┘
         │                    │                    │
    [5 workers]          [5 workers]          [5 workers]
```

**2. Domain-based Partitioning**:
```python
class PartitionedForeman:
    """Assign workers by domain specialization."""
    
    DOMAIN_FOREMAN_MAP = {
        "code": "foreman-code",
        "analysis": "foreman-analysis",
        "operations": "foreman-ops",
        "security": "foreman-security",
    }
```

**3. Priority Queues**:
```
tasks/
├── pending/
│   ├── critical/    # Immediate processing
│   ├── high/        # Next available worker
│   ├── normal/      # Standard queue
│   └── low/         # Background processing
├── in_progress/
├── done/
└── failed/
```

---

## Failure Handling

### Worker Failure

```
Worker Failure Detection:
  1. Foreman misses heartbeat (15min × 2)
  2. Worker marked UNHEALTHY
  3. Foreman misses heartbeat (15min × 2 more)
  4. Worker REMOVED from pool
  5. Tasks reassigned to healthy workers
```

### Task Failure

```
Task Failure Handling:
  1. Worker writes to failed_queue
  2. Coordinator detects failed task
  3. Options:
     a. Retry (up to N times)
     b. Reassign to different worker
     c. Escalate to human
     d. Record as permanent failure
```

### Stall Detection

```
Stall Detection:
  1. Task in pending > STALL_THRESHOLD (10 min)
  2. Worker marked as potentially stalled
  3. Foreman sends ping
  4. If no response, mark worker UNHEALTHY
  5. Reassign task
```

---

## Token Efficiency

### File-Driven Coordination

**Problem**: Passing context through LLM prompts is token-expensive.

**Solution**: Use files for state persistence.

```
Traditional (Token-Expensive):
┌─────────┐     ┌─────────┐
│ LLM A   │────▶│ LLM B   │
│         │     │         │
│ (sends  │     │ (gets   │
│  full   │     │  full   │
│ context)│     │ context)│
└─────────┘     └─────────┘
Cost: O(n²) tokens per handoff

File-Driven (Token-Efficient):
┌─────────┐     ┌───────┐     ┌─────────┐
│ LLM A   │────▶│ FILE  │────▶│ LLM B   │
│         │     │ .task │     │         │
│ (writes │     │ .md   │     │ (reads  │
│  task)  │     │       │     │  task)  │
└─────────┘     └───────┘     └─────────┘
Cost: O(n) tokens (one read/write each)
```

### Context Injection

```python
# Instead of full history
full_context = memory.get_all()  # BAD: 100K+ tokens

# Use targeted injection
relevant_memories = memory.search(task_description, limit=5)
injected_context = relevant_memories[:5]  # GOOD: ~5K tokens
```

---

## Monitoring & Observability

### Metrics to Export

```python
# Foreman metrics
foreman_workers_total{status="healthy|unhealthy"}
foreman_tasks_assigned_total
foreman_tasks_completed_total
foreman_heartbeat_misses_total

# Coordinator metrics
coordinator_tasks_dispatched_total{domain, complexity}
coordinator_tasks_succeeded_total
coordinator_tasks_failed_total
coordinator_tasks_stalled_total
coordinator_dispatch_latency_seconds
```

### Logging

```python
# Structured logging
logger.info("Task dispatched", extra={
    "task_id": task_id,
    "worker_id": worker_id,
    "domain": domain.value,
    "complexity": complexity.value,
    "memories_found": len(memories),
})

logger.warning("Worker unhealthy", extra={
    "worker_id": worker_id,
    "last_heartbeat": last_heartbeat.isoformat(),
    "missed_heartbeats": missed,
})
```

---

## Future Work

### Short-term (P1)
- [ ] Integrate TokenGuard with Foreman (budget per worker)
- [ ] Add priority queue support
- [ ] Implement task retry logic

### Medium-term (P2)
- [ ] Multi-foreman coordination
- [ ] Redis-backed state (multi-instance)
- [ ] Prometheus metrics export

### Long-term (P3)
- [ ] Dynamic worker scaling
- [ ] Cross-project worker sharing
- [ ] A2A protocol for inter-foreman communication

---

## Appendix: Worker Definitions

```python
WORKER_DEFINITIONS = [
    {
        "worker_id": "glm5-worker-1",
        "agent_dir": "glm5-worker-1",
        "specializations": ["code", "analysis", "reasoning"],
    },
    {
        "worker_id": "glm5-worker-2",
        "agent_dir": "glm5-worker-2",
        "specializations": ["code", "operations", "security"],
    },
]

DOMAIN_WORKER_MAP = {
    "code": "glm5-worker-1",
    "analysis": "glm5-worker-2",
    "reasoning": "glm5-worker-1",
    "creative": "glm5-worker-2",
    "operations": "glm5-worker-2",
    "security": "glm5-worker-2",
    "unknown": "glm5-worker-1",
}
```

---

**Document Status**: COMPLETE  
**Next Review**: 2026-04-23  
**Owner**: Pi Agent
