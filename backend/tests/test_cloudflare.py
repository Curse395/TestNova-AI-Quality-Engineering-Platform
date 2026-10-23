
import os
import requests
from dotenv import load_dotenv

load_dotenv()

account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
api_token = os.getenv("CLOUDFLARE_API_TOKEN")

if not account_id or not api_token:
    raise RuntimeError(
        "Cloudflare credentials missing. Check your backend .env file."
    )

url = (
    f"https://api.cloudflare.com/client/v4/accounts/"
    f"{account_id}/ai/run/@cf/meta/llama-3.1-8b-instruct"
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

if response.ok:
    data = response.json()
    if data.get("success"):
        print("SUCCESS: Cloudflare Workers AI is connected.")
        print("Model response:", data.get("result", {}).get("response"))
    else:
        print("API returned an error:", data.get("errors"))
else:
    print("HTTP status:", response.status_code)
    print("API error:", response.text[:1000])
