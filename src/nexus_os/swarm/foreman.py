"""
Foreman - Worker Pool Manager with Heartbeat Monitoring
Manages workers, distributes tasks, monitors health
"""

import json
import time
import threading
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class WorkerStatus:
    """Worker health status"""
    worker_id: str
    last_heartbeat: datetime
    healthy: bool
    tasks_assigned: int
    tasks_completed: int
    agent_card: Dict[str, Any]


class Foreman:
    """
    Worker pool management with 15-minute heartbeat monitoring
    Task distribution, health checks, dead worker cleanup
    """
    
    def __init__(self, 
                 foreman_id: str,
                 max_workers: int = 5,
                 heartbeat_interval: int = 900,  # 15 minutes
                 missed_heartbeats_threshold: int = 2):
        self.foreman_id = foreman_id
        self.max_workers = max_workers
        self.heartbeat_interval = heartbeat_interval
        self.missed_threshold = missed_heartbeats_threshold
        
        # Worker registry
        self._workers: Dict[str, WorkerStatus] = {}
        self._lock = threading.Lock()
        
        # Monitoring
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        
        # Task tracking
        self._task_assignments: Dict[str, str] = {}  # task_id -> worker_id
    
    def register_worker(self, agent_card: Dict[str, Any]) -> bool:
        """Register a new worker with the foreman"""
        worker_id = agent_card.get("agent_id")
        if not worker_id:
            return False
        
        with self._lock:
            if len(self._workers) >= self.max_workers:
                return False
            
            self._workers[worker_id] = WorkerStatus(
                worker_id=worker_id,
                last_heartbeat=datetime.now(),
                healthy=True,
                tasks_assigned=0,
                tasks_completed=0,
                agent_card=agent_card
            )
        
        print(f"[Foreman] Registered worker: {worker_id}")
        return True
    
    def deregister_worker(self, worker_id: str):
        """Remove a worker from the pool"""
        with self._lock:
            if worker_id in self._workers:
                del self._workers[worker_id]
                print(f"[Foreman] Deregistered worker: {worker_id}")
    
    def record_heartbeat(self, worker_id: str) -> bool:
        """Record heartbeat from a worker"""
        with self._lock:
            if worker_id not in self._workers:
                return False
            
            worker = self._workers[worker_id]
            worker.last_heartbeat = datetime.now()
            worker.healthy = True
            return True
    
    def check_worker_health(self, worker_id: str) -> bool:
        """Check if worker is healthy based on last heartbeat"""
        with self._lock:
            if worker_id not in self._workers:
                return False
            
            worker = self._workers[worker_id]
            elapsed = (datetime.now() - worker.last_heartbeat).total_seconds()
            
            # Mark unhealthy if missed too many heartbeats
            if elapsed > self.heartbeat_interval * self.missed_threshold:
                worker.healthy = False
                return False
            
            return worker.healthy
    
    def get_healthy_workers(self) -> List[str]:
        """Get list of healthy worker IDs"""
        with self._lock:
            return [
                wid for wid, status in self._workers.items()
                if self.check_worker_health(wid)
            ]
    
    def assign_task(self, task_id: str, worker_id: Optional[str] = None) -> Optional[str]:
        """
        Assign task to a worker
        If worker_id not specified, uses round-robin selection
        Returns assigned worker_id or None if no workers available
        """
        healthy_workers = self.get_healthy_workers()
        
        if not healthy_workers:
            return None
        
        if worker_id and worker_id in healthy_workers:
            assigned = worker_id
        else:
            # Round-robin: pick worker with fewest tasks
            with self._lock:
                worker_loads = [
                    (wid, self._workers[wid].tasks_assigned)
                    for wid in healthy_workers
                ]
                assigned = min(worker_loads, key=lambda x: x[1])[0]
        
        with self._lock:
            self._task_assignments[task_id] = assigned
            self._workers[assigned].tasks_assigned += 1
        
        return assigned
    
    def complete_task(self, task_id: str, success: bool = True):
        """Mark task as completed and update worker stats"""
        with self._lock:
            if task_id not in self._task_assignments:
                return
            
            worker_id = self._task_assignments[task_id]
            del self._task_assignments[task_id]
            
            if worker_id in self._workers:
                worker = self._workers[worker_id]
                worker.tasks_assigned -= 1
                if success:
                    worker.tasks_completed += 1
    
    def monitor_loop(self):
        """Background heartbeat monitoring loop"""
        while self._running:
            try:
                # Check all workers
                with self._lock:
                    for worker_id, status in list(self._workers.items()):
                        elapsed = (datetime.now() - status.last_heartbeat).total_seconds()
                        
                        if elapsed > self.heartbeat_interval * self.missed_threshold:
                            if status.healthy:
                                print(f"[Foreman] Worker {worker_id} missed heartbeats, marking unhealthy")
                                status.healthy = False
                        
                        # Remove dead workers after extended timeout
                        if elapsed > self.heartbeat_interval * (self.missed_threshold + 2):
                            print(f"[Foreman] Removing dead worker: {worker_id}")
                            del self._workers[worker_id]
                
                # Sleep for heartbeat interval
                time.sleep(self.heartbeat_interval / 4)  # Check 4x per interval
                
            except Exception as e:
                print(f"[Foreman] Monitor error: {e}")
                time.sleep(60)
    
    def start_monitoring(self):
        """Start the heartbeat monitoring thread"""
        if self._running:
            return
        
        self._running = True
        self._monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self._monitor_thread.start()
        print(f"[Foreman] Started monitoring (interval={self.heartbeat_interval}s)")
    
    def stop_monitoring(self):
        """Stop the monitoring thread"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        print("[Foreman] Stopped monitoring")
    
    def get_status(self) -> Dict[str, Any]:
        """Get foreman status report"""
        with self._lock:
            return {
                "foreman_id": self.foreman_id,
                "running": self._running,
                "total_workers": len(self._workers),
                "healthy_workers": len(self.get_healthy_workers()),
                "active_tasks": len(self._task_assignments),
                "workers": [
                    {
                        "worker_id": w.worker_id,
                        "healthy": w.healthy,
                        "last_heartbeat": w.last_heartbeat.isoformat(),
                        "tasks_assigned": w.tasks_assigned,
                        "tasks_completed": w.tasks_completed
                    }
                    for w in self._workers.values()
                ]
            }
    
    def get_worker_capabilities(self, worker_id: str) -> List[str]:
        """Get capabilities for a specific worker"""
        with self._lock:
            if worker_id not in self._workers:
                return []
            return self._workers[worker_id].agent_card.get("capabilities", [])
