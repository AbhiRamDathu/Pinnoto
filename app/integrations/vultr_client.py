
import os

import httpx


class VultrClient:
    BASE_URL = "https://api.vultr.com/v2"

    def __init__(self):
        api_key = os.getenv("VULTR_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("VULTR_API_KEY is not configured")

        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )

    def get_account(self) -> dict:
        response = self._client.get("/account")
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._client.close()
