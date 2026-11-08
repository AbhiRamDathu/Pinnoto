
import pytest
import httpx

from app.integrations.vultr_client import VultrClient


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("VULTR_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="VULTR_API_KEY"):
        VultrClient()


def test_get_account_uses_bearer_token(monkeypatch):
    monkeypatch.setenv("VULTR_API_KEY", "test-key")

    def handler(request):
        assert request.url.path == "/v2/account"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"account": {"name": "test"}})

    client = VultrClient()
    client._client.close()
    client._client = httpx.Client(
        base_url="https://api.vultr.com/v2",
        headers={
            "Authorization": "Bearer test-key",
            "Accept": "application/json",
        },
        transport=httpx.MockTransport(handler),
    )

    try:
        result = client.get_account()
        assert result["account"]["name"] == "test"
    finally:
        client.close()


def test_account_errors_are_raised(monkeypatch):
    monkeypatch.setenv("VULTR_API_KEY", "test-key")

    client = VultrClient()
    client._client.close()
    client._client = httpx.Client(
        base_url="https://api.vultr.com/v2",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401)
        ),
    )

    try:
        with pytest.raises(httpx.HTTPStatusError):
            client.get_account()
    finally:
        client.close()
