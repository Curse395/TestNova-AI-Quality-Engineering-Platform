
import os

import pytest
import requests
from dotenv import load_dotenv


@pytest.mark.skipif(
    os.getenv("RUN_CLOUDFLARE_SMOKE_TEST") != "1",
    reason="Set RUN_CLOUDFLARE_SMOKE_TEST=1 to call the external Cloudflare API.",
)
def test_cloudflare_workers_ai_smoke():
    load_dotenv()
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not account_id or not api_token:
        pytest.skip("Cloudflare smoke-test credentials are not configured.")

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        "/ai/run/@cf/meta/llama-3.1-8b-instruct"
    )
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        json={
            "prompt": "You are a QA assistant. Reply with exactly: "
            "Cloudflare Workers AI connection successful."
        },
        timeout=60,
    )

    assert response.ok, f"Cloudflare API returned HTTP {response.status_code}."
    data = response.json()
    assert data.get("success") is True, f"Cloudflare API errors: {data.get('errors')}"
    assert data.get("result", {}).get("response")
