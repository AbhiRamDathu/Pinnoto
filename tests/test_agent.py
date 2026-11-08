
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.inference import InferenceError


client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})


@patch(
    "app.api.agent.generate_response",
    return_value='{"summary":"Run smoke test","actions":["smoke_test"]}',
)
def test_agent_plan_returns_proposed_plan(mock_generate):
    response = client.post(
        "/api/agent/plan",
        json={"task": "Check whether the sandbox works"},
    )

    assert response.json()["proposed_plan"] == {
        "summary": "Run smoke test",
        "actions": ["smoke_test"],
    }
    assert response.json()["execution_started"] is False
    mock_generate.assert_called_once()

    assert set(response.json().keys()) == {
        "proposed_plan",
        "execution_started",
        "approval_id",
        "plan_hash",
        "approval_expires_in_seconds",
    }


def test_agent_plan_rejects_extra_fields():
    response = client.post(
        "/api/agent/plan",
        json={
            "task": "Check sandbox",
            "execute_now": True,
        },
    )

    assert response.status_code == 422


def test_agent_plan_rejects_empty_task():
    response = client.post(
        "/api/agent/plan",
        json={"task": ""},
    )

    assert response.status_code == 422

@patch(
    "app.api.agent.generate_response",
    side_effect=InferenceError("Vultr inference is not configured."),
)
def test_agent_plan_handles_inference_failure(mock_generate):
    response = client.post(
        "/api/agent/plan",
        json={"task": "Check sandbox"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "The planning service is unavailable."
    )
    mock_generate.assert_called_once()


@patch(
    "app.api.agent.generate_response",
    return_value='{"summary":"Run test","actions":["delete_everything"]}',
)
def test_agent_rejects_unsupported_action(mock_generate):
    response = client.post(
        "/api/agent/plan",
        json={"task": "Do something unsafe"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Inference returned an invalid plan."


@patch(
    "app.api.agent.generate_response",
    return_value='{"summary":"Run test","actions":["smoke_test"],"admin":true}',
)
def test_agent_rejects_extra_model_fields(mock_generate):
    response = client.post(
        "/api/agent/plan",
        json={"task": "Check sandbox"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Inference returned an invalid plan."


@patch(
    "app.api.agent.generate_response",
    return_value="not valid JSON",
)
def test_agent_rejects_malformed_model_json(mock_generate):
    response = client.post(
        "/api/agent/plan",
        json={"task": "Check sandbox"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Inference returned an invalid plan."

@patch(
    "app.api.agent.generate_response",
    return_value='{"summary":"Nothing to do","actions":[]}',
)
def test_agent_rejects_empty_action_list(mock_generate):
    response = client.post(
        "/api/agent/plan",
        json={"task": "Check sandbox"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Inference returned an invalid plan."
    )

def test_agent_plan_rejects_whitespace_only_task():
    response = client.post(
        "/api/agent/plan",
        json={"task": "   "},
    )

    assert response.status_code == 422



def test_agent_plan_response_defaults_execution_started_to_false():
    from app.core.agent_schemas import AgentPlanResponse

    response = AgentPlanResponse(
        proposed_plan={
            "summary": "Run smoke test",
            "actions": ["smoke_test"],
        },
        approval_id="test-approval-id",
        plan_hash="a" * 64,
        approval_expires_in_seconds=300,
    )

    assert response.execution_started is False
    assert response.proposed_plan.actions == ["smoke_test"]
    assert response.approval_id == "test-approval-id"
    assert response.plan_hash == "a" * 64
    assert response.approval_expires_in_seconds == 300

@patch(
    "app.api.agent.generate_response",
    return_value='{"summary":"Run smoke test","actions":["smoke_test"]}',
)
def test_agent_plan_returns_typed_response(mock_generate):
    response = client.post(
        "/api/agent/plan",
        json={"task": "Check whether the sandbox works"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["proposed_plan"]["summary"] == "Run smoke test"
    assert data["proposed_plan"]["actions"] == ["smoke_test"]
    assert data["execution_started"] is False
    mock_generate.assert_called_once()


@patch(
    "app.api.agent.generate_response",
    return_value='{"summary":"Run smoke test","actions":["smoke_test"]}',
)
@patch("app.api.execution.DockerRunner.run_smoke_test")
def test_agent_planning_does_not_execute_docker(
    mock_run_smoke_test,
    mock_generate,
):
    response = client.post(
        "/api/agent/plan",
        json={"task": "Check whether the sandbox works"},
    )

    assert response.status_code == 200
    assert response.json()["execution_started"] is False
    mock_run_smoke_test.assert_not_called()

@patch(
    "app.api.agent.generate_response",
    return_value='{"summary":"Run smoke test","actions":["smoke_test"]}',
)

@patch("app.api.agent.run_verified_smoke_test")
def test_agent_execute_runs_verified_smoke_test(
    mock_execute,
    mock_generate,
):
    mock_execute.return_value = {
        "success": True,
        "output": "PROOFRUN_SMOKE_OK\n",
        "evidence": {"verified": True},
    }

    plan_response = client.post(
        "/api/agent/plan",
        json={"task": "Check whether the sandbox works"},
    )
    assert plan_response.status_code == 200, plan_response.text

    approval = plan_response.json()

    response = client.post(
        "/api/agent/execute",
        json={
            "approval_id": approval["approval_id"],
            "plan_hash": approval["plan_hash"],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["execution_started"] is True
    assert data["plan"]["actions"] == ["smoke_test"]
    assert data["results"][0]["success"] is True
    mock_generate.assert_called_once()
    mock_execute.assert_called_once()


@patch(
    "app.api.agent.generate_response",
    return_value="not valid JSON",
)
@patch("app.api.agent.run_verified_smoke_test")
def test_agent_execute_rejects_invalid_model_output(
    mock_execute,
    mock_generate,
):
    response = client.post(
        "/api/agent/plan",
        json={"task": "Check sandbox"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Inference returned an invalid plan."
    )
    mock_generate.assert_called_once()
    mock_execute.assert_not_called()

@patch(
    "app.api.agent.generate_response",
    return_value=(
        '{"summary":"Unsafe",'
        '"actions":["delete_everything"]}'
    ),
)
@patch("app.api.agent.run_verified_smoke_test")
def test_agent_execute_rejects_unsupported_action(
    mock_execute,
    mock_generate,
):
    response = client.post(
        "/api/agent/plan",
        json={"task": "Do something unsafe"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Inference returned an invalid plan."
    )
    mock_generate.assert_called_once()
    mock_execute.assert_not_called()
from app.core.execution_service import ExecutionServiceError


@patch(
    "app.api.agent.generate_response",
    return_value='{"summary":"Run smoke test","actions":["smoke_test"]}',
)
@patch("app.api.agent.run_verified_smoke_test")
def test_agent_execute_handles_execution_failure(
    mock_execute,
    mock_generate,
):
    mock_execute.side_effect = ExecutionServiceError(
        "Sandbox execution failed.",
        status_code=500,
    )


    plan_response = client.post(
        "/api/agent/plan",
        json={"task": "Check sandbox"},
    )
    assert plan_response.status_code == 200, plan_response.text

    approval = plan_response.json()

    response = client.post(
        "/api/agent/execute",
        json={
            "approval_id": approval["approval_id"],
            "plan_hash": approval["plan_hash"],
        },
    )


    assert response.status_code == 500
    assert response.json()["detail"] == "Sandbox execution failed."
    mock_execute.assert_called_once()

@patch(
    "app.api.agent.generate_response",
    side_effect=InferenceError("Vultr inference is not configured."),
)
@patch("app.api.agent.run_verified_smoke_test")
def test_agent_execute_handles_inference_failure(
    mock_execute,
    mock_generate,
):

    plan_response = client.post(
        "/api/agent/plan",
        json={"task": "Check sandbox"},
    )
    assert plan_response.status_code == 503
    assert plan_response.json()["detail"] == (
        "The planning service is unavailable."
    )
    mock_generate.assert_called_once()
    mock_execute.assert_not_called()
    return


    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Vultr inference is not configured."
    )
    mock_execute.assert_not_called()


@patch(
    "app.api.agent.generate_response",
    return_value=(
        '{"summary":"Run smoke test",'
        '"actions":["smoke_test"]}'
    ),
)
@patch("app.api.agent.run_verified_smoke_test")
def test_agent_execute_runs_at_most_one_action(
    mock_execute,
    mock_generate,
):
    mock_execute.return_value = {
        "success": True,
        "output": "PROOFRUN_SMOKE_OK\n",
        "evidence": {"verified": True},
    }

    plan_response = client.post(
        "/api/agent/plan",
        json={"task": "Check sandbox"},
    )

    assert plan_response.status_code == 200, (
        plan_response.text
    )
    approval = plan_response.json()

    response = client.post(
        "/api/agent/execute",
        json={
            "approval_id": approval["approval_id"],
            "plan_hash": approval["plan_hash"],
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["execution_started"] is True
    assert len(data["results"]) == 1
    assert data["plan"]["actions"] == ["smoke_test"]

    mock_generate.assert_called_once()
    mock_execute.assert_called_once()

@patch(
    "app.api.agent.generate_response",
    return_value='{"summary":"Run smoke test","actions":["smoke_test"]}',
)
def test_agent_plan_strips_task_whitespace(mock_generate):
    response = client.post(
        "/api/agent/plan",
        json={"task": "   Check sandbox   "},
    )

    assert response.status_code == 200
    assert response.json()["execution_started"] is False
    assert "Check sandbox" in mock_generate.call_args.args[0]
    assert "   Check sandbox   " not in mock_generate.call_args.args[0]

def test_agent_plan_rejects_oversized_task():
    response = client.post(
        "/api/agent/plan",
        json={"task": "A" * 2001},
    )

    assert response.status_code == 422


import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch


def _create_test_approval():
    with patch(
        "app.api.agent.generate_response",
        return_value='{"summary":"Run smoke test","actions":["smoke_test"]}',
    ):
        response = client.post(
            "/api/agent/plan",
            json={"task": "Check whether the sandbox works"},
        )
    assert response.status_code == 200, response.text
    return response.json()


def test_agent_rejects_replayed_approval():
    approval = _create_test_approval()
    payload = {
        "approval_id": approval["approval_id"],
        "plan_hash": approval["plan_hash"],
    }
    success = {
        "success": True,
        "output": "PROOFRUN_SMOKE_OK\n",
        "evidence": {"verified": True},
    }

    with patch("app.api.agent.run_verified_smoke_test", return_value=success) as run:
        first = client.post("/api/agent/execute", json=payload)
        second = client.post("/api/agent/execute", json=payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    run.assert_called_once()



def test_agent_rejects_expired_approval():
    approval = _create_test_approval()

    payload = {
        "approval_id": approval["approval_id"],
        "plan_hash": approval["plan_hash"],
    }

    # Use a finite future timestamp to avoid interfering
    # with TestClient and Python's global time functions.
    future_timestamp = 4_102_444_800.0

    with patch(
        "app.api.agent._now_epoch_seconds",
        return_value=future_timestamp,
    ):
        response = client.post(
            "/api/agent/execute",
            json=payload,
        )

    assert response.status_code == 409
def test_agent_rejects_wrong_plan_hash_without_consuming_approval():
    approval = _create_test_approval()
    payload = {
        "approval_id": approval["approval_id"],
        "plan_hash": "0" * 64,
    }

    wrong_hash = client.post("/api/agent/execute", json=payload)
    assert wrong_hash.status_code == 409

    payload["plan_hash"] = approval["plan_hash"]
    success = {
        "success": True,
        "output": "PROOFRUN_SMOKE_OK\n",
        "evidence": {"verified": True},
    }

    with patch("app.api.agent.run_verified_smoke_test", return_value=success) as run:
        correct_hash = client.post("/api/agent/execute", json=payload)

    assert correct_hash.status_code == 200, correct_hash.text
    run.assert_called_once()


def test_agent_concurrent_approval_use_executes_once():
    approval = _create_test_approval()
    payload = {
        "approval_id": approval["approval_id"],
        "plan_hash": approval["plan_hash"],
    }
    barrier = threading.Barrier(2)
    success = {
        "success": True,
        "output": "PROOFRUN_SMOKE_OK\n",
        "evidence": {"verified": True},
    }

    def execute():
        barrier.wait(timeout=5)
        return client.post("/api/agent/execute", json=payload)

    with patch("app.api.agent.run_verified_smoke_test", return_value=success) as run:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(execute) for _ in range(2)]
            responses = [future.result(timeout=15) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 409]
    run.assert_called_once()
