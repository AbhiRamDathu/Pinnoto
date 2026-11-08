
import httpx
import pytest
from unittest.mock import patch

from app.core.inference import InferenceError, generate_response


@patch("app.core.inference.VULTR_INFERENCE_API_KEY", "test-key")
@patch("app.core.inference.VULTR_INFERENCE_MODEL", "test-model")
@patch("app.core.inference.httpx.post")
def test_generate_response_uses_vultr(mock_post):
    mock_post.return_value = httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": "Plan generated."}}
            ]
        },
        request=httpx.Request("POST", "https://example.test"),
    )

    result = generate_response("Plan a safe CSV analysis.")

    assert result == "Plan generated."
    args, kwargs = mock_post.call_args
    assert args[0].endswith("/chat/completions")
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["json"]["model"] == "test-model"
    assert kwargs["timeout"] == 20.0


@patch("app.core.inference.VULTR_INFERENCE_API_KEY", None)
def test_missing_api_key_fails_safely():
    with pytest.raises(InferenceError, match="not configured"):
        generate_response("Test prompt")


@patch("app.core.inference.VULTR_INFERENCE_API_KEY", "test-key")
@patch("app.core.inference.VULTR_INFERENCE_MODEL", "test-model")
@patch("app.core.inference.httpx.post")
def test_timeout_is_handled(mock_post):
    mock_post.side_effect = httpx.TimeoutException("internal detail")

    with pytest.raises(InferenceError, match="timed out"):
        generate_response("Test prompt")


@patch("app.core.inference.VULTR_INFERENCE_API_KEY", "test-key")
@patch("app.core.inference.VULTR_INFERENCE_MODEL", "test-model")
@patch("app.core.inference.httpx.post")
def test_authentication_error_does_not_leak_details(mock_post):
    request = httpx.Request("POST", "https://example.test")
    mock_post.return_value = httpx.Response(
        401,
        text="PRIVATE_UPSTREAM_DETAIL",
        request=request,
    )

    with pytest.raises(InferenceError) as error:
        generate_response("Test prompt")

    assert "PRIVATE_UPSTREAM_DETAIL" not in str(error.value)


def test_empty_prompt_is_rejected():
    with pytest.raises(InferenceError, match="non-empty prompt"):
        generate_response("   ")
