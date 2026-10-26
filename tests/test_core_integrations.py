"""
POC test for the two backend integrations powering Phase 2/3:
1. OpenRouter (LLM) — generate a structured daily routine
2. Emailit (transactional email) — send a test email

If either of these fails, Phase 2 cannot be built. So we prove them in isolation first.

Run:
    cd /app && python tests/test_core_integrations.py
"""
import json
import os
import sys
import time
from typing import Any, Dict

import requests

# Keys come from the environment (backend/.env); never hard-code them here.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
EMAILIT_API_KEY = os.environ.get("EMAILIT_API_KEY", "")


def divider(label: str) -> None:
    print(f"\n{'=' * 70}\n>>> {label}\n{'=' * 70}")


def test_openrouter() -> bool:
    divider("TEST 1 — OpenRouter chat.completions (routine generation)")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://bybloomlabs.com",
        "X-Title": "Bloom Labs Admin Dashboard",
    }
    body = {
        "model": "anthropic/claude-sonnet-4.5",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an executive assistant generating a 1-day work plan "
                    "for the founder of Bloom Labs (an AI-native web-app dev agency). "
                    "Output ONLY valid JSON matching the schema requested."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Generate today's routine. Return JSON with keys: "
                    "date (YYYY-MM-DD), blocks (array of {start, end, type, title, "
                    "checklist (array of strings)}). "
                    "Pattern: 10-11 OUTREACH, 11-12 CONTENT, 12-1 LUNCH, "
                    "1-2 CALLS, 2-3 OUTREACH, 3-4 CONTENT, 4-5 CLIENT_MGMT. "
                    "Each task must be specific and actionable for a $90K-revenue goal."
                ),
            },
        ],
        "temperature": 0.7,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
    }

    try:
        t0 = time.time()
        r = requests.post(url, headers=headers, json=body, timeout=60)
        elapsed = time.time() - t0
        print(f"HTTP {r.status_code} in {elapsed:.1f}s")

        if r.status_code != 200:
            print("RESPONSE:", r.text[:1500])
            return False

        data = r.json()
        if "choices" not in data:
            print("Bad response shape:", data)
            return False

        content = data["choices"][0]["message"]["content"]
        print(f"\nRaw content (first 500 chars):\n{content[:500]}\n...")

        # Strip markdown code fences if model wraps JSON
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]  # drop ```json or ```
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()

        # Verify it's valid JSON
        parsed: Dict[str, Any] = json.loads(cleaned)
        if "blocks" not in parsed:
            print("Missing 'blocks' key in routine")
            return False
        print(f"\n✓ Parsed {len(parsed['blocks'])} blocks. First block:")
        print(json.dumps(parsed["blocks"][0], indent=2))

        usage = data.get("usage", {})
        print(f"\nUsage: prompt={usage.get('prompt_tokens')} "
              f"completion={usage.get('completion_tokens')} total={usage.get('total_tokens')}")
        return True
    except Exception as e:
        print(f"FAIL: {e!r}")
        return False


def test_emailit() -> bool:
    divider("TEST 2 — Emailit POST /v1/emails")

    # Try v1 endpoint first as that's the most common Emailit base
    base_urls = [
        "https://api.emailit.com/v1/emails",
        "https://api.emailit.com/v2/emails",
    ]

    headers = {
        "Authorization": f"Bearer {EMAILIT_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "from": "hello@bybloomlabs.com",
        "to": "founder@thesalvador.group",
        "subject": "[Bloom Labs] Emailit POC test",
        "html": (
            "<h2>Emailit integration test</h2>"
            "<p>This is an automated POC email confirming that Emailit + the "
            "provided API key are wired correctly.</p>"
            "<p>If you are seeing this, the integration works.</p>"
        ),
        "text": "Bloom Labs Emailit POC. If you got this, the integration works.",
    }

    for url in base_urls:
        print(f"\n>> Trying: {url}")
        try:
            t0 = time.time()
            r = requests.post(url, headers=headers, json=body, timeout=30)
            elapsed = time.time() - t0
            print(f"HTTP {r.status_code} in {elapsed:.1f}s")
            print(f"Response (first 800 chars):\n{r.text[:800]}")
            if r.status_code in (200, 201, 202):
                print("✓ Email accepted by Emailit.")
                return True
            # 401/403 usually means key works but sender/domain unverified
            if r.status_code in (401, 403):
                print("Auth or domain issue — key reaches API but request rejected.")
        except Exception as e:
            print(f"Error: {e!r}")
    return False


if __name__ == "__main__":
    print("Bloom Labs — Phase 2 Pre-flight POC")
    print(f"Python: {sys.version.split()[0]}")
    print(f"CWD:    {os.getcwd()}")

    or_ok = test_openrouter()
    em_ok = test_emailit()

    divider("RESULTS")
    print(f"OpenRouter:  {'PASS ✓' if or_ok else 'FAIL ✗'}")
    print(f"Emailit:     {'PASS ✓' if em_ok else 'FAIL ✗'}")

    sys.exit(0 if (or_ok and em_ok) else 1)
