"""
Worker - A2A Agent with Heartbeat and Task Execution
A2A Agent Card format support, 15min heartbeat, file-driven task processing
"""

import os
import json
import time
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import hashlib


@dataclass
class AgentCard:
    """A2A Agent Card format"""
    agent_id: str
    lane: str
    trust_band: str  # COMMUNITY_VERIFIED, etc.
    capabilities: list
    availability: str = "ready"
    hold_state: Optional[str] = None
    failure_patterns: list = field(default_factory=list)
    last_verified_event: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "lane": self.lane,
            "trust_band": self.trust_band,
            "capabilities": self.capabilities,
            "availability": self.availability,
            "hold_state": self.hold_state,
            "failure_patterns": self.failure_patterns,
            "last_verified_event": self.last_verified_event
        }


class Worker:
    """
    A2A Agent Worker with:
    - Agent Card format support
    - 15min heartbeat
    - Task execution from tasks/pending
    - Results to tasks/done or tasks/failed
    """
    
    def __init__(self,
                 worker_id: str,
                 tasks_dir: str = "tasks",
                 lane: str = "code",
                 capabilities: Optional[list] = None,
                 heartbeat_interval: int = 900,  # 15 minutes
                 foreman_endpoint: Optional[str] = None):
        self.worker_id = worker_id
        self.tasks_dir = Path(tasks_dir)
        self.lane = lane
        self.capabilities = capabilities or ["python", "debugging", "analysis"]
        self.heartbeat_interval = heartbeat_interval
        self.foreman_endpoint = foreman_endpoint
        
        # Directories
        self.pending_dir = self.tasks_dir / "pending"
        self.done_dir = self.tasks_dir / "done"
        self.failed_dir = self.tasks_dir / "failed"
        
        for d in [self.pending_dir, self.done_dir, self.failed_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        # State
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._current_task: Optional[str] = None
        self._tasks_completed = 0
        self._tasks_failed = 0
        
        # Agent Card
        self._agent_card = AgentCard(
            agent_id=worker_id,
            lane=lane,
            trust_band="COMMUNITY_VERIFIED",
            capabilities=self.capabilities,
            availability="ready",
            last_verified_event=datetime.now().isoformat()
        )
    
    def get_agent_card(self) -> Dict[str, Any]:
        """Generate A2A Agent Card"""
        self._agent_card.last_verified_event = datetime.now().isoformat()
        return self._agent_card.to_dict()
    
    def send_heartbeat(self):
        """Send heartbeat to foreman (file-based for now)"""
        heartbeat = {
            "worker_id": self.worker_id,
            "timestamp": datetime.now().isoformat(),
            "status": "healthy" if self._running else "stopped",
            "current_task": self._current_task,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "agent_card": self.get_agent_card()
        }
        
        # Write to heartbeat file
        heartbeat_file = self.tasks_dir / ".heartbeats" / f"{self.worker_id}.json"
        heartbeat_file.parent.mkdir(exist_ok=True)
        
        with open(heartbeat_file, 'w') as f:
            json.dump(heartbeat, f, indent=2)
    
    def heartbeat_loop(self):
        """Background heartbeat sender"""
        while self._running:
            try:
                self.send_heartbeat()
                time.sleep(self.heartbeat_interval)
            except Exception as e:
                print(f"[Worker {self.worker_id}] Heartbeat error: {e}")
                time.sleep(60)
    
    def get_next_task(self) -> Optional[Path]:
        """Get next pending task file"""
        try:
            tasks = sorted(self.pending_dir.glob("*.task.md"))
            return tasks[0] if tasks else None
        except Exception:
            return None
    
    def parse_task(self, task_file: Path) -> Dict[str, Any]:
        """Parse task from .task.md file"""
        content = task_file.read_text()
        
        # Parse frontmatter if present
        task = {
            "task_id": str(task_file.name).replace(".task.md", ""),
            "content": content,
            "received_at": datetime.now().isoformat()
        }
        
        # Extract metadata from content
        if "---" in content:
            parts = content.split("---", 2)
            if len(parts) >= 3:
                # Parse YAML-like frontmatter
                for line in parts[1].strip().split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        task[key.strip()] = value.strip()
                task["content"] = parts[2].strip()
        
        return task
    
    def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute task and return result
        Override this method for custom task execution
        """
        # Default: simulate task execution
        task_type = task.get("type", "unknown")
        content = task.get("content", "")
        
        result = {
            "task_id": task["task_id"],
            "worker_id": self.worker_id,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "status": "pending",
            "output": None,
            "error": None
        }
        
        try:
            # Simulate work
            time.sleep(0.5)
            
            # Simple task execution based on type
            if task_type == "summarize":
                result["output"] = f"Summary of: {content[:100]}..."
            elif task_type == "analyze":
                result["output"] = f"Analysis complete for: {content[:100]}..."
            elif task_type == "code":
                result["output"] = f"Code review for: {content[:100]}..."
            else:
                result["output"] = f"Processed: {content[:100]}..."
            
            result["status"] = "success"
            result["completed_at"] = datetime.now().isoformat()
            
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            result["completed_at"] = datetime.now().isoformat()
        
        return result
    
    def save_result(self, result: Dict[str, Any]):
        """Save task result to done or failed directory"""
        task_id = result["task_id"]
        
        if result["status"] == "success":
            output_dir = self.done_dir
            self._tasks_completed += 1
        else:
            output_dir = self.failed_dir
            self._tasks_failed += 1
        
        output_file = output_dir / f"{task_id}.result.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
    
    def worker_loop(self):
        """Main worker execution loop"""
        while self._running:
            try:
                # Get next task
                task_file = self.get_next_task()
                
                if not task_file:
                    # No tasks available, sleep and retry
                    time.sleep(5)
                    continue
                
                # Parse and execute task
                task = self.parse_task(task_file)
                self._current_task = task["task_id"]
                self._agent_card.availability = "busy"
                
                print(f"[Worker {self.worker_id}] Processing task: {task['task_id']}")
                
                # Execute
                result = self.execute_task(task)
                
                # Save result
                self.save_result(result)
                
                # Remove original task file
                task_file.unlink()
                
                print(f"[Worker {self.worker_id}] Task {result['status']}: {task['task_id']}")
                
                # Update state
                self._current_task = None
                self._agent_card.availability = "ready"
                
            except Exception as e:
                print(f"[Worker {self.worker_id}] Error: {e}")
                time.sleep(10)
    
    def start(self):
        """Start the worker threads"""
        if self._running:
            return
        
        self._running = True
        
        # Start worker loop
        self._worker_thread = threading.Thread(target=self.worker_loop, daemon=True)
        self._worker_thread.start()
        
        # Start heartbeat
        self._heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()
        
        print(f"[Worker {self.worker_id}] Started")
    
    def stop(self):
        """Stop the worker gracefully"""
        self._running = False
        self._agent_card.availability = "offline"
        
        # Send final heartbeat
        self.send_heartbeat()
        
        print(f"[Worker {self.worker_id}] Stopped")
    
    def is_running(self) -> bool:
        """Check if worker is running"""
        return self._running
    
    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics"""
        return {
            "worker_id": self.worker_id,
            "running": self._running,
            "current_task": self._current_task,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "agent_card": self.get_agent_card()
        }
