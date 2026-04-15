"""
Open Claw Swarm Spawner - Dynamic Agent Spawning Based on Task Volume
Spawns Foreman + Workers when pending tasks > 3
"""

import os
import json
import time
import threading
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Import swarm components
from .foreman import Foreman
from .worker import Worker


@dataclass
class SpawnConfig:
    """Configuration for swarm spawning"""
    task_threshold: int = 3  # Spawn when pending > 3
    max_workers: int = 5
    heartbeat_interval: int = 900  # 15 minutes in seconds
    tasks_dir: str = "tasks"
    spawn_cooldown: int = 60  # Seconds between spawns


class OpenClawSpawner:
    """
    Dynamic spawn based on task volume >3 pending
    15min heartbeat monitoring
    File-driven coordination via tasks/pending, tasks/done, tasks/failed
    """
    
    def __init__(self, config: Optional[SpawnConfig] = None):
        self.config = config or SpawnConfig()
        self.pending_dir = Path(self.config.tasks_dir) / "pending"
        self.done_dir = Path(self.config.tasks_dir) / "done"
        self.failed_dir = Path(self.config.tasks_dir) / "failed"
        
        # Ensure directories exist
        for d in [self.pending_dir, self.done_dir, self.failed_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        # State tracking
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._foreman: Optional[Foreman] = None
        self._workers: List[Worker] = []
        self._last_spawn_time: Optional[datetime] = None
        self._lock = threading.Lock()
    
    def get_pending_count(self) -> int:
        """Count pending tasks in tasks/pending directory"""
        try:
            return len(list(self.pending_dir.glob("*.task.md")))
        except Exception:
            return 0
    
    def get_task_files(self) -> List[Path]:
        """Get list of pending task files"""
        try:
            return list(self.pending_dir.glob("*.task.md"))
        except Exception:
            return []
    
    def should_spawn(self) -> bool:
        """Check if spawning conditions are met"""
        pending = self.get_pending_count()
        
        # Check threshold
        if pending <= self.config.task_threshold:
            return False
        
        # Check cooldown
        if self._last_spawn_time:
            elapsed = (datetime.now() - self._last_spawn_time).total_seconds()
            if elapsed < self.config.spawn_cooldown:
                return False
        
        # Check max workers
        with self._lock:
            if len(self._workers) >= self.config.max_workers:
                return False
        
        return True
    
    def spawn_foreman(self) -> Foreman:
        """Spawn a new Foreman instance"""
        foreman = Foreman(
            foreman_id=f"foreman-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            max_workers=self.config.max_workers,
            heartbeat_interval=self.config.heartbeat_interval
        )
        self._foreman = foreman
        return foreman
    
    def spawn_worker(self, worker_id: Optional[str] = None) -> Worker:
        """Spawn a new Worker instance"""
        if worker_id is None:
            worker_id = f"worker-{len(self._workers)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        worker = Worker(
            worker_id=worker_id,
            tasks_dir=str(self.config.tasks_dir),
            heartbeat_interval=self.config.heartbeat_interval
        )
        
        with self._lock:
            self._workers.append(worker)
        
        return worker
    
    def spawn_swarm(self, num_workers: int = 2) -> Dict[str, Any]:
        """
        Spawn complete swarm: 1 Foreman + N Workers
        Returns spawn report
        """
        spawn_time = datetime.now()
        self._last_spawn_time = spawn_time
        
        # Spawn foreman
        foreman = self.spawn_foreman()
        
        # Spawn workers
        spawned_workers = []
        for i in range(num_workers):
            worker = self.spawn_worker()
            spawned_workers.append(worker.worker_id)
            
            # Register worker with foreman
            foreman.register_worker(worker.get_agent_card())
        
        # Start foreman heartbeat monitoring
        foreman.start_monitoring()
        
        # Start workers
        for worker in self._workers:
            if not worker.is_running():
                worker.start()
        
        return {
            "spawned_at": spawn_time.isoformat(),
            "foreman_id": foreman.foreman_id,
            "worker_ids": spawned_workers,
            "pending_tasks": self.get_pending_count(),
            "status": "active"
        }
    
    def monitor_loop(self):
        """Background monitoring loop - checks task volume and spawns as needed"""
        while self._running:
            try:
                if self.should_spawn():
                    pending = self.get_pending_count()
                    workers_needed = min(
                        pending // 2,  # 1 worker per 2 tasks
                        self.config.max_workers - len(self._workers)
                    )
                    
                    if workers_needed > 0:
                        print(f"[Spawner] Task volume {pending} > threshold {self.config.task_threshold}")
                        print(f"[Spawner] Spawning {workers_needed} workers...")
                        
                        if self._foreman is None:
                            self.spawn_swarm(num_workers=workers_needed)
                        else:
                            # Add workers to existing swarm
                            for _ in range(workers_needed):
                                worker = self.spawn_worker()
                                self._foreman.register_worker(worker.get_agent_card())
                                worker.start()
                
                # Sleep before next check
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                print(f"[Spawner] Monitor error: {e}")
                time.sleep(30)  # Back off on error
    
    def start(self):
        """Start the spawner monitoring"""
        if self._running:
            return
        
        self._running = True
        self._monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self._monitor_thread.start()
        print(f"[Spawner] Started monitoring (threshold={self.config.task_threshold})")
    
    def stop(self):
        """Stop the spawner and all spawned agents"""
        self._running = False
        
        # Stop workers
        with self._lock:
            for worker in self._workers:
                worker.stop()
            self._workers.clear()
        
        # Stop foreman
        if self._foreman:
            self._foreman.stop_monitoring()
            self._foreman = None
        
        print("[Spawner] Stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current spawner status"""
        return {
            "running": self._running,
            "pending_tasks": self.get_pending_count(),
            "foreman_active": self._foreman is not None,
            "worker_count": len(self._workers),
            "max_workers": self.config.max_workers,
            "last_spawn": self._last_spawn_time.isoformat() if self._last_spawn_time else None
        }
    
    def distribute_tasks(self) -> int:
        """
        Manually trigger task distribution to workers
        Returns number of tasks distributed
        """
        if not self._foreman:
            return 0
        
        task_files = self.get_task_files()
        distributed = 0
        
        for task_file in task_files:
            # Simple round-robin distribution
            with self._lock:
                if not self._workers:
                    break
                worker_idx = distributed % len(self._workers)
                worker = self._workers[worker_idx]
            
            # Move task to worker's processing queue
            # In real implementation, this would use A2A protocol
            distributed += 1
        
        return distributed


# Convenience function
def spawn_swarm_if_needed(tasks_dir: str = "tasks", threshold: int = 3) -> Optional[Dict[str, Any]]:
    """Check task volume and spawn swarm if needed"""
    spawner = OpenClawSpawner(SpawnConfig(tasks_dir=tasks_dir, task_threshold=threshold))
    
    if spawner.should_spawn():
        return spawner.spawn_swarm()
    
    return None
