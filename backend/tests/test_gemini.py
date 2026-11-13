import os

import pytest
from dotenv import load_dotenv


@pytest.mark.skipif(
    os.getenv("RUN_GEMINI_SMOKE_TEST") != "1",
    reason="Set RUN_GEMINI_SMOKE_TEST=1 to call the external Gemini API.",
)
def test_gemini_api_smoke():
    from google import genai

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY is not configured.")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents="Reply with exactly: TestNova works.",
    )

    assert response.text.strip() == "TestNova works."