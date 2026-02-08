"""Contract parity tests for bv-sdk-cli runtime vs bv-runtime.

These tests enforce the invariant:
    Runtime semantics MUST be identical in dev mode (SDK-CLI) and
    production (bv-runtime / Runner).

Any test failure here means a divergence has been introduced between
the two implementations and MUST be fixed before merge.

Tested dimensions:
1. Guard behavior (STOP/KILL blocking)
2. Context API surface (same functions, same return types)
3. HTTP payload shapes (identical request bodies)
4. Queue status validation (same enum rules)
5. Return type parity (SecretHandle, CredentialHandle, QueueItem)
6. Logging payload parity
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import fields as dataclass_fields


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_sdk_context(**overrides):
    """Initialize SDK-CLI runtime context with defaults."""
    from bv.runtime import context as ctx
    ctx._runtime_context = ctx.RuntimeContextData()
    defaults = dict(
        base_url="https://test.example.com/tenant/orchestrator_",
        robot_token="",
        execution_id="",
        robot_name="local-dev",
        machine_name="dev-machine",
        project_type="rpa",
    )
    defaults.update(overrides)
    ctx.set_runtime_context(**defaults)
    return ctx


def _reset_sdk_context():
    """Reset SDK-CLI runtime context to uninitialized state."""
    from bv.runtime import context as ctx
    ctx._runtime_context = ctx.RuntimeContextData()


# ---------------------------------------------------------------------------
# PART 1 — Guard Behavior Parity
# ---------------------------------------------------------------------------

class TestGuardParity:
    """Verify guard semantics match production exactly."""

    def setup_method(self):
        _reset_sdk_context()

    def test_require_bv_run_blocks_when_uninitialized(self):
        """Same as bv-runtime: raises RuntimeError when context not initialized."""
        from bv.runtime._guard import require_bv_run
        with pytest.raises(RuntimeError, match="bv.runtime is only available"):
            require_bv_run()

    def test_require_execution_active_blocks_when_uninitialized(self):
        """Same as bv-runtime: raises RuntimeError when context not initialized."""
        from bv.runtime._guard import require_execution_active
        with pytest.raises(RuntimeError, match="bv.runtime is only available"):
            require_execution_active()

    def test_require_execution_active_blocks_after_expiry(self):
        """Same as bv-runtime: after mark_execution_expired, all API calls blocked."""
        ctx = _init_sdk_context()
        from bv.runtime._guard import require_execution_active

        # Should pass before expiry
        require_execution_active()

        # Mark expired (simulates STOP/KILL signal)
        ctx.mark_execution_expired("Job is no longer running (received SIGTERM)")

        # Should now block
        with pytest.raises(RuntimeError, match="Job is no longer running"):
            require_execution_active()

    def test_require_bv_run_with_logging_logs_api_call(self):
        """Same as bv-runtime: logs execution_id, tenant_id, folder_id on every call."""
        _init_sdk_context(
            execution_id="exec-001",
            tenant_id="tenant-123",
            folder_id="folder-456",
        )
        from bv.runtime._guard import require_bv_run_with_logging

        with patch("bv.runtime._guard.logger") as mock_logger:
            require_bv_run_with_logging("test.operation")

            mock_logger.debug.assert_called_once()
            call_args = mock_logger.debug.call_args
            extra = call_args.kwargs.get("extra", {})
            assert extra["execution_id"] == "exec-001"
            assert extra["tenant_id"] == "tenant-123"
            assert extra["folder_id"] == "folder-456"
            assert extra["operation"] == "test.operation"

    def test_stop_signal_blocks_assets_api(self):
        """Same as bv-runtime: assets.get_asset blocked after STOP signal."""
        ctx = _init_sdk_context(execution_id="exec-001")
        from bv.runtime import assets

        ctx.mark_execution_expired("Job is no longer running (received SIGTERM)")

        with pytest.raises(RuntimeError, match="Job is no longer running"):
            assets.get_asset("test-asset")

    def test_stop_signal_blocks_queue_api(self):
        """Same as bv-runtime: queue.add blocked after STOP signal."""
        ctx = _init_sdk_context(execution_id="exec-001")
        from bv.runtime import queue

        ctx.mark_execution_expired("Job is no longer running")

        with pytest.raises(RuntimeError, match="Job is no longer running"):
            queue.add("test-queue", {"data": "value"})

    def test_stop_signal_blocks_logging_api(self):
        """Same as bv-runtime: log_message blocked after STOP signal."""
        ctx = _init_sdk_context(execution_id="exec-001")
        from bv.runtime.logging import log_message, LogLevel

        ctx.mark_execution_expired("Job is no longer running")

        with pytest.raises(RuntimeError, match="Job is no longer running"):
            log_message("test message", LogLevel.INFO)

    def test_stop_signal_blocks_secret_value(self):
        """Same as bv-runtime: SecretHandle.value() blocked after STOP signal."""
        ctx = _init_sdk_context(execution_id="exec-001")
        from bv.runtime.secret import SecretHandle

        handle = SecretHandle("my-secret")
        ctx.mark_execution_expired("Job is no longer running")

        with pytest.raises(RuntimeError, match="Job is no longer running"):
            handle.value()


# ---------------------------------------------------------------------------
# PART 2 — Context API Surface Parity
# ---------------------------------------------------------------------------

class TestContextApiParity:
    """Verify context module exposes the same API surface as bv-runtime."""

    def setup_method(self):
        _reset_sdk_context()

    def test_execution_context_dataclass_fields(self):
        """ExecutionContext has the same fields as production."""
        from bv.runtime.context import ExecutionContext

        field_names = {f.name for f in dataclass_fields(ExecutionContext)}
        expected = {
            "execution_id",
            "robot_name",
            "machine_name",
            "orchestrator_url",
            "tenant_id",
            "folder_id",
            "is_runner_mode",
            "project_type",
        }
        assert field_names == expected

    def test_execution_context_is_frozen(self):
        """ExecutionContext is immutable (frozen=True), same as production."""
        from bv.runtime.context import ExecutionContext

        ctx = ExecutionContext(
            execution_id="exec-001",
            robot_name="test-robot",
            machine_name="test-machine",
            orchestrator_url="https://test.example.com",
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            ctx.execution_id = "changed"

    def test_runtime_context_data_has_expiry_fields(self):
        """RuntimeContextData has execution_expired and expiry_reason, same as production."""
        from bv.runtime.context import RuntimeContextData

        data = RuntimeContextData()
        assert hasattr(data, "execution_expired")
        assert hasattr(data, "expiry_reason")
        assert data.execution_expired is False
        assert data.expiry_reason is None

    def test_get_execution_context_returns_correct_type(self):
        """get_execution_context() returns ExecutionContext, same as production."""
        _init_sdk_context(
            execution_id="exec-001",
            robot_name="test-robot",
            machine_name="test-machine",
        )
        from bv.runtime.context import get_execution_context, ExecutionContext

        ctx = get_execution_context()
        assert isinstance(ctx, ExecutionContext)
        assert ctx.execution_id == "exec-001"
        assert ctx.robot_name == "test-robot"

    def test_is_runner_mode_false_in_dev(self):
        """is_runner_mode() returns False when robot_token is empty (dev mode)."""
        _init_sdk_context(robot_token="")
        from bv.runtime.context import is_runner_mode

        assert is_runner_mode() is False

    def test_is_runner_mode_true_with_token(self):
        """is_runner_mode() returns True when robot_token is set."""
        _init_sdk_context(robot_token="test-token-12345678")
        from bv.runtime.context import is_runner_mode

        assert is_runner_mode() is True

    def test_get_job_id_aliases_execution_id(self):
        """get_job_id() is an alias for get_execution_id(), same as production."""
        _init_sdk_context(execution_id="exec-001")
        from bv.runtime.context import get_job_id, get_execution_id

        assert get_job_id() == get_execution_id() == "exec-001"

    def test_is_agent_execution(self):
        """is_agent_execution() checks project_type, same as production."""
        from bv.runtime.context import is_agent_execution

        _init_sdk_context(project_type="rpa")
        assert is_agent_execution() is False

        _init_sdk_context(project_type="agent")
        assert is_agent_execution() is True

    def test_all_context_getters_present(self):
        """All context getter functions from bv-runtime are available."""
        from bv.runtime import context

        required_functions = [
            "set_runtime_context",
            "is_runtime_initialized",
            "is_execution_valid",
            "get_expiry_reason",
            "mark_execution_expired",
            "get_base_url",
            "get_robot_token",
            "get_execution_context",
            "get_execution_id",
            "get_job_id",
            "get_robot_name",
            "get_machine_name",
            "get_tenant_id",
            "get_folder_id",
            "is_runner_mode",
            "is_agent_execution",
        ]
        for fn_name in required_functions:
            assert hasattr(context, fn_name), f"Missing: context.{fn_name}"
            assert callable(getattr(context, fn_name)), f"Not callable: context.{fn_name}"


# ---------------------------------------------------------------------------
# PART 3 — HTTP Payload Parity (same request bodies)
# ---------------------------------------------------------------------------

class TestHttpPayloadParity:
    """Verify that identical API calls produce identical HTTP payloads."""

    def setup_method(self):
        _init_sdk_context(execution_id="exec-001")

    def _capture_request(self, module_call, *args, **kwargs):
        """Intercept OrchestratorClient.request and capture (method, path, kwargs)."""
        captured = {}

        def fake_request(self_, method, path, **req_kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["kwargs"] = req_kwargs
            # Return a minimal valid response
            return MagicMock(data={"id": "abc12345-def6-7890-abcd-ef1234567890", "value": "test"})

        with patch("bv.orchestrator.client.OrchestratorClient.request", fake_request):
            try:
                module_call(*args, **kwargs)
            except Exception:
                pass  # Some calls may fail after request (e.g., GUID validation)

        return captured

    # --- Assets ---

    def test_get_asset_payload(self):
        """GET /assets/name/{name} — same as production."""
        from bv.runtime import assets
        cap = self._capture_request(assets.get_asset, "my-asset")
        assert cap["method"] == "GET"
        assert cap["path"] == "/assets/name/my-asset"

    def test_set_asset_payload(self):
        """PUT /assets/name/{name} with {"value": ...} — same as production."""
        from bv.runtime import assets
        cap = self._capture_request(assets.set_asset, "my-asset", "new-value")
        assert cap["method"] == "PUT"
        assert cap["path"] == "/assets/name/my-asset"
        assert cap["kwargs"]["json"] == {"value": "new-value"}

    def test_set_secret_payload(self):
        """PUT /assets/secret/{name} with {"value": ...} — same as production."""
        from bv.runtime import assets
        cap = self._capture_request(assets.set_secret, "my-secret", "encrypted-data")
        assert cap["method"] == "PUT"
        assert cap["path"] == "/assets/secret/my-secret"
        assert cap["kwargs"]["json"] == {"value": "encrypted-data"}

    def test_set_credential_payload(self):
        """PUT /assets/credential/{name} with {username, password} — same as production."""
        from bv.runtime import assets
        cap = self._capture_request(
            assets.set_credential, "my-cred", "admin", "enc-password"
        )
        assert cap["method"] == "PUT"
        assert cap["path"] == "/assets/credential/my-cred"
        assert cap["kwargs"]["json"] == {
            "username": "admin",
            "password": "enc-password",
        }

    def test_get_credential_endpoint(self):
        """GET /runtime/credentials/{name} — same as production."""
        from bv.runtime import assets
        cap = self._capture_request(assets.get_credential, "my-cred")
        assert cap["method"] == "GET"
        assert cap["path"] == "/runtime/credentials/my-cred"

    def test_secret_handle_resolve_endpoint(self):
        """POST /runtime/secrets/resolve with {"name": ...} — same as production."""
        from bv.runtime.secret import SecretHandle
        handle = SecretHandle("my-secret")
        cap = self._capture_request(handle.value)
        assert cap["method"] == "POST"
        assert cap["path"] == "/runtime/secrets/resolve"
        assert cap["kwargs"]["json"] == {"name": "my-secret"}

    # --- Queue ---

    def test_queue_add_payload(self):
        """POST /queue-items/add with {queue_name, payload, reference, priority}."""
        from bv.runtime.queue import add, Priority
        cap = self._capture_request(
            add, "my-queue", {"key": "value"}, reference="ref-001", priority=Priority.HIGH
        )
        assert cap["method"] == "POST"
        assert cap["path"] == "/queue-items/add"
        assert cap["kwargs"]["json"] == {
            "queue_name": "my-queue",
            "payload": {"key": "value"},
            "reference": "ref-001",
            "priority": 3,  # HIGH = 3
        }

    def test_queue_get_payload(self):
        """GET /queue-items/next?queue_name=... — same as production."""
        from bv.runtime.queue import get
        cap = self._capture_request(get, "my-queue")
        assert cap["method"] == "GET"
        assert cap["path"] == "/queue-items/next"
        assert cap["kwargs"]["params"] == {"queue_name": "my-queue"}

    def test_queue_set_status_done_payload(self):
        """PUT /queue-items/{id}/status — DONE payload matches production."""
        from bv.runtime.queue import set_status, Status
        cap = self._capture_request(
            set_status, "abc12345-def6", Status.DONE, output={"result": "ok"}
        )
        assert cap["method"] == "PUT"
        assert cap["path"] == "/queue-items/abc12345-def6/status"
        assert cap["kwargs"]["json"] == {
            "status": "DONE",
            "result": {"result": "ok"},
            "error_message": None,
        }

    def test_queue_set_status_failed_payload(self):
        """PUT /queue-items/{id}/status — FAILED payload matches production."""
        from bv.runtime.queue import set_status, Status, ErrorType
        cap = self._capture_request(
            set_status,
            "abc12345-def6",
            Status.FAILED,
            error_type=ErrorType.APPLICATION,
            error_reason="Something went wrong",
        )
        assert cap["method"] == "PUT"
        assert cap["path"] == "/queue-items/abc12345-def6/status"
        body = cap["kwargs"]["json"]
        assert body["status"] == "FAILED"
        assert body["error_type"] == "APPLICATION"
        assert body["error_message"] == "Something went wrong"
        assert body["result"] is None

    def test_queue_set_status_failed_business_terminal_payload(self):
        """PUT /queue-items/{id}/status — BUSINESS error sets terminal=True."""
        from bv.runtime.queue import set_status, Status, ErrorType
        cap = self._capture_request(
            set_status,
            "abc12345-def6",
            Status.FAILED,
            error_type=ErrorType.BUSINESS,
            error_reason="Business rule violation",
        )
        body = cap["kwargs"]["json"]
        assert body["error_type"] == "BUSINESS"
        assert body["terminal"] is True

    # --- Logging ---

    def test_log_message_payload(self):
        """POST /job-executions/{id}/logs with {timestamp, level, message}."""
        _init_sdk_context(execution_id="exec-guid-001")
        from bv.runtime.logging import log_message, LogLevel

        captured = {}

        def fake_request(self_, method, path, **kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["json"] = kwargs.get("json")
            return MagicMock(data={})

        with patch("bv.orchestrator.client.OrchestratorClient.request", fake_request):
            log_message("Test message", LogLevel.INFO)

        assert captured["method"] == "POST"
        assert captured["path"] == "/job-executions/exec-guid-001/logs"
        assert captured["json"]["level"] == "INFO"
        assert captured["json"]["message"] == "Test message"
        assert "timestamp" in captured["json"]


# ---------------------------------------------------------------------------
# PART 4 — Queue Status Validation Parity
# ---------------------------------------------------------------------------

class TestQueueValidationParity:
    """Verify queue validation rules match production exactly."""

    def setup_method(self):
        _init_sdk_context(execution_id="exec-001")

    def test_done_cannot_have_error_type(self):
        """DONE status cannot include error_type — same as production."""
        from bv.runtime.queue import set_status, Status, ErrorType
        with pytest.raises(ValueError, match="DONE status cannot include error_type"):
            set_status(
                "abc12345-def6", Status.DONE, error_type=ErrorType.APPLICATION
            )

    def test_done_cannot_have_error_reason(self):
        """DONE status cannot include error_reason — same as production."""
        from bv.runtime.queue import set_status, Status
        with pytest.raises(ValueError, match="DONE status cannot include error_reason"):
            set_status("abc12345-def6", Status.DONE, error_reason="oops")

    def test_failed_requires_error_type(self):
        """FAILED status requires error_type — same as production."""
        from bv.runtime.queue import set_status, Status
        with pytest.raises(ValueError, match="FAILED status requires error_type"):
            set_status(
                "abc12345-def6", Status.FAILED, error_reason="Something went wrong"
            )

    def test_failed_requires_error_reason(self):
        """FAILED status requires error_reason — same as production."""
        from bv.runtime.queue import set_status, Status, ErrorType
        with pytest.raises(ValueError, match="FAILED status requires error_reason"):
            set_status(
                "abc12345-def6", Status.FAILED, error_type=ErrorType.APPLICATION
            )

    def test_abandoned_requires_error_reason(self):
        """ABANDONED status requires error_reason — same as production."""
        from bv.runtime.queue import set_status, Status
        with pytest.raises(ValueError, match="ABANDONED status requires error_reason"):
            set_status("abc12345-def6", Status.ABANDONED)

    def test_numeric_item_id_rejected(self):
        """Numeric item IDs are rejected — same as production."""
        from bv.runtime.queue import set_status, Status
        with pytest.raises(ValueError, match="numeric IDs not allowed"):
            set_status("12345", Status.DONE)

    def test_invalid_guid_rejected(self):
        """Invalid GUID format rejected — same as production."""
        from bv.runtime.queue import set_status, Status
        with pytest.raises(ValueError, match="external GUID"):
            set_status("not-a-guid!", Status.DONE)

    def test_priority_must_be_enum(self):
        """Priority must be Priority enum — same as production."""
        from bv.runtime.queue import add
        with pytest.raises(TypeError, match="Priority enum"):
            add("test-queue", {"data": "value"}, priority=5)  # type: ignore


# ---------------------------------------------------------------------------
# PART 5 — Return Type Parity
# ---------------------------------------------------------------------------

class TestReturnTypeParity:
    """Verify return types match production exactly."""

    def setup_method(self):
        _init_sdk_context(execution_id="exec-001")

    def test_get_secret_returns_secret_handle(self):
        """get_secret() returns SecretHandle, same as production."""
        from bv.runtime import assets
        from bv.runtime.secret import SecretHandle

        handle = assets.get_secret("my-secret")
        assert isinstance(handle, SecretHandle)
        assert handle.name == "my-secret"

    def test_secret_handle_str_is_masked(self):
        """str(SecretHandle) returns '***', same as production."""
        from bv.runtime.secret import SecretHandle
        handle = SecretHandle("test")
        assert str(handle) == "***"

    def test_secret_handle_bool_raises(self):
        """bool(SecretHandle) raises TypeError, same as production."""
        from bv.runtime.secret import SecretHandle
        handle = SecretHandle("test")
        with pytest.raises(TypeError, match="boolean context"):
            bool(handle)

    def test_get_credential_returns_credential_handle(self):
        """get_credential() returns CredentialHandle, same as production."""
        from bv.runtime import assets
        from bv.runtime.credential import CredentialHandle

        def fake_request(self_, method, path, **kwargs):
            return MagicMock(data={"username": "admin"})

        with patch("bv.orchestrator.client.OrchestratorClient.request", fake_request):
            handle = assets.get_credential("my-cred")

        assert isinstance(handle, CredentialHandle)
        assert handle.name == "my-cred"
        assert handle.username == "admin"

    def test_credential_handle_password_is_secret_handle(self):
        """CredentialHandle.password is a SecretHandle, same as production."""
        from bv.runtime import assets
        from bv.runtime.secret import SecretHandle

        def fake_request(self_, method, path, **kwargs):
            return MagicMock(data={"username": "admin"})

        with patch("bv.orchestrator.client.OrchestratorClient.request", fake_request):
            handle = assets.get_credential("my-cred")

        assert isinstance(handle.password, SecretHandle)
        assert handle.password.name == "my-cred.password"

    def test_credential_handle_dict_access_blocked(self):
        """CredentialHandle does not support item access, same as production."""
        from bv.runtime.credential import CredentialHandle
        from bv.runtime.secret import SecretHandle

        handle = CredentialHandle("test", "admin", SecretHandle("test.password"))
        with pytest.raises(TypeError, match="does not support item access"):
            handle["username"]  # type: ignore

    def test_queue_add_returns_queue_item(self):
        """queue.add() returns QueueItem, same as production."""
        from bv.runtime.queue import add, Priority
        from bv.runtime.queue_item import QueueItem

        def fake_request(self_, method, path, **kwargs):
            return MagicMock(data={"id": "abc12345-def6-7890-abcd-ef1234567890"})

        with patch("bv.orchestrator.client.OrchestratorClient.request", fake_request):
            item = add("test-queue", {"data": "value"}, priority=Priority.NORMAL)

        assert isinstance(item, QueueItem)
        assert item.queue_name == "test-queue"
        assert item.attempt == 1

    def test_queue_item_is_immutable(self):
        """QueueItem is immutable (frozen), same as production."""
        from bv.runtime.queue_item import QueueItem

        item = QueueItem(
            item_id="abc12345-def6",
            queue_name="test",
            reference=None,
            priority=1,
            retries=0,
            content={},
        )
        with pytest.raises(TypeError, match="immutable"):
            item.queue_name = "changed"  # type: ignore

    def test_queue_item_dict_access_blocked(self):
        """QueueItem does not support item access, same as production."""
        from bv.runtime.queue_item import QueueItem

        item = QueueItem(
            item_id="abc12345-def6",
            queue_name="test",
            reference=None,
            priority=1,
            retries=0,
            content={},
        )
        with pytest.raises(TypeError, match="does not support item access"):
            item["queue_name"]  # type: ignore

    def test_queue_get_returns_queue_item(self):
        """queue.get() returns QueueItem when data available, same as production."""
        from bv.runtime.queue import get
        from bv.runtime.queue_item import QueueItem

        def fake_request(self_, method, path, **kwargs):
            return MagicMock(data={
                "id": "abc12345-def6-7890-abcd-ef1234567890",
                "queue_name": "test-queue",
                "reference": "ref-001",
                "priority": 1,
                "retries": 2,
                "payload": {"key": "value"},
            })

        with patch("bv.orchestrator.client.OrchestratorClient.request", fake_request):
            item = get("test-queue")

        assert isinstance(item, QueueItem)
        assert item.retries == 2
        assert item.attempt == 3  # retries + 1

    def test_queue_get_returns_none_when_empty(self):
        """queue.get() returns None when queue is empty, same as production."""
        from bv.runtime.queue import get

        def fake_request(self_, method, path, **kwargs):
            return MagicMock(data=None)

        with patch("bv.orchestrator.client.OrchestratorClient.request", fake_request):
            item = get("test-queue")

        assert item is None


# ---------------------------------------------------------------------------
# PART 6 — Enum Parity
# ---------------------------------------------------------------------------

class TestEnumParity:
    """Verify enum definitions match production exactly."""

    def test_status_enum_values(self):
        """Status enum has same values as production."""
        from bv.runtime.queue import Status
        assert Status.DONE.value == "DONE"
        assert Status.FAILED.value == "FAILED"
        assert Status.ABANDONED.value == "ABANDONED"
        assert len(Status) == 3

    def test_error_type_enum_values(self):
        """ErrorType enum has same values as production."""
        from bv.runtime.queue import ErrorType
        assert ErrorType.APPLICATION.value == "APPLICATION"
        assert ErrorType.BUSINESS.value == "BUSINESS"
        assert len(ErrorType) == 2

    def test_priority_enum_values(self):
        """Priority enum has same values as production."""
        from bv.runtime.queue import Priority
        assert Priority.LOW == 0
        assert Priority.NORMAL == 1
        assert Priority.MEDIUM == 2
        assert Priority.HIGH == 3
        assert len(Priority) == 4

    def test_log_level_enum_values(self):
        """LogLevel enum has same values as production."""
        from bv.runtime.logging import LogLevel
        assert LogLevel.TRACE.value == "TRACE"
        assert LogLevel.INFO.value == "INFO"
        assert LogLevel.WARN.value == "WARN"
        assert LogLevel.ERROR.value == "ERROR"
        assert len(LogLevel) == 4


# ---------------------------------------------------------------------------
# PART 7 — Module Export Parity
# ---------------------------------------------------------------------------

class TestModuleExportParity:
    """Verify public API surface matches production (minus traces)."""

    def test_init_exports(self):
        """__init__.py exports match production (minus traces)."""
        import bv.runtime as rt

        # Modules
        assert hasattr(rt, "assets")
        assert hasattr(rt, "queue")
        assert hasattr(rt, "context")

        # Logging
        assert hasattr(rt, "log_message")
        assert hasattr(rt, "LogLevel")

        # Context re-exports
        assert hasattr(rt, "get_execution_context")
        assert hasattr(rt, "get_execution_id")
        assert hasattr(rt, "get_job_id")
        assert hasattr(rt, "get_robot_name")
        assert hasattr(rt, "get_machine_name")
        assert hasattr(rt, "get_tenant_id")
        assert hasattr(rt, "get_folder_id")
        assert hasattr(rt, "is_runner_mode")
        assert hasattr(rt, "ExecutionContext")

    def test_queues_plural_is_deprecated(self):
        """Importing bv.runtime.queues raises AttributeError, same as production."""
        from bv.runtime import queues

        with pytest.raises(AttributeError, match="plural.*removed"):
            queues.add  # type: ignore


# ---------------------------------------------------------------------------
# PART 8 — Logging Behavior Parity
# ---------------------------------------------------------------------------

class TestLoggingBehaviorParity:
    """Verify logging behavior matches production exactly."""

    def setup_method(self):
        _reset_sdk_context()

    def test_dev_mode_prints_to_console(self, capsys):
        """In dev mode (no execution_id), log_message prints to console."""
        _init_sdk_context(execution_id="")  # No execution ID = dev mode
        from bv.runtime.logging import log_message, LogLevel

        log_message("Hello from dev", LogLevel.INFO)

        captured = capsys.readouterr()
        assert "[INFO] Hello from dev" in captured.out

    def test_runner_mode_sends_to_orchestrator(self):
        """In runner mode (has execution_id), log_message sends HTTP request."""
        _init_sdk_context(execution_id="exec-guid-001")
        from bv.runtime.logging import log_message, LogLevel

        captured = {}

        def fake_request(self_, method, path, **kwargs):
            captured["sent"] = True
            captured["path"] = path
            return MagicMock(data={})

        with patch("bv.orchestrator.client.OrchestratorClient.request", fake_request):
            log_message("Hello from runner", LogLevel.INFO)

        assert captured.get("sent") is True
        assert "exec-guid-001" in captured["path"]

    def test_logging_never_raises(self, capsys):
        """Logging is best-effort; failures fall back to console, never raise."""
        _init_sdk_context(execution_id="exec-guid-001")
        from bv.runtime.logging import log_message, LogLevel

        def failing_request(self_, method, path, **kwargs):
            raise ConnectionError("Orchestrator down")

        with patch("bv.orchestrator.client.OrchestratorClient.request", failing_request):
            # Should NOT raise
            log_message("Test message", LogLevel.ERROR)

        captured = capsys.readouterr()
        assert "[ERROR] Test message" in captured.out
        assert "failed to send" in captured.out
