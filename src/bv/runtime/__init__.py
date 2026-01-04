from __future__ import annotations

# Backward compatibility: Use local implementation
# When bv-runtime package is installed, it will provide bv.runtime modules
# This local implementation ensures backward compatibility for projects that don't have bv-runtime installed
from bv.runtime import assets, queues
from bv.runtime.logging import log_message, LogLevel

__all__ = ["assets", "queues", "log_message", "LogLevel"]
