from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum

from bv.runtime._guard import require_bv_run


class LogLevel(Enum):
    """Log level enumeration for structured logging."""
    TRACE = "TRACE"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


def log_message(message: str, level: LogLevel) -> None:
    """Send a log message to Orchestrator (Runner mode) or print to console (dev mode).
    
    Args:
        message: The log message to send
        level: The log level (LogLevel enum value)
    
    Behavior:
        - Runner mode (BV_JOB_EXECUTION_ID set): Sends log to Orchestrator
        - Dev mode (no BV_JOB_EXECUTION_ID): Prints to console with [LEVEL] prefix
    """
    require_bv_run()
    
    if not isinstance(message, str):
        message = str(message)
    
    level_str = level.value if isinstance(level, LogLevel) else str(level).upper()
    
    execution_id = os.environ.get("BV_JOB_EXECUTION_ID")
    
    if execution_id:
        # Runner mode: Send to Orchestrator
        _send_to_orchestrator(execution_id, message, level_str)
    else:
        # Dev mode: Print to console
        print(f"[{level_str}] {message}")


def _send_to_orchestrator(execution_id: str, message: str, level: str) -> None:
    """Send log message to Orchestrator job execution logs endpoint."""
    try:
        from bv.orchestrator.client import OrchestratorClient
        
        client = OrchestratorClient()
        timestamp = datetime.now(timezone.utc).isoformat()
        
        payload = {
            "timestamp": timestamp,
            "level": level,
            "message": message,
        }
        
        # Best-effort: don't raise exceptions, just log errors
        try:
            client.request("POST", f"/api/job-executions/{execution_id}/logs", json=payload)
        except Exception:
            # In Runner mode, if sending fails, fall back to console
            # This prevents automation failures due to logging issues
            print(f"[{level}] {message} (failed to send to Orchestrator)")
    except Exception:
        # If we can't even initialize the client, just print
        print(f"[{level}] {message} (Orchestrator unavailable)")

