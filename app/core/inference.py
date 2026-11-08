
import httpx

from app.core.config import (
    VULTR_INFERENCE_API_KEY,
    VULTR_INFERENCE_BASE_URL,
    VULTR_INFERENCE_MODEL,
)


class InferenceError(Exception):
    """Safe, user-facing inference failure."""


def generate_response(prompt: str) -> str:
    """Generate a response using Vultr Serverless Inference."""

    if not isinstance(prompt, str) or not prompt.strip():
        raise InferenceError("A non-empty prompt is required.")

    if not VULTR_INFERENCE_API_KEY:
        raise InferenceError("Vultr inference is not configured.")

    if not VULTR_INFERENCE_MODEL:
        raise InferenceError("Vultr inference model is not configured.")

    try:
        response = httpx.post(
            f"{VULTR_INFERENCE_BASE_URL.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {VULTR_INFERENCE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": VULTR_INFERENCE_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are ProofRun, an execution-planning assistant. "
                            "Propose safe, bounded plans. Never claim code ran "
                            "or succeeded unless execution evidence confirms it."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 1024,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise InferenceError("Inference returned an empty response.")

        return content.strip()

    except InferenceError:
        raise
    except httpx.TimeoutException as exc:
        raise InferenceError("Vultr inference timed out.") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code

        if status in (401, 403):
            message = "Vultr inference authentication failed."
        elif status == 429:
            message = "Vultr inference rate limit reached."
        else:
            message = "Vultr inference request failed."

        raise InferenceError(message) from exc
    except (
        httpx.RequestError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        raise InferenceError(
            "Vultr inference returned an unusable response."
        ) from exc
