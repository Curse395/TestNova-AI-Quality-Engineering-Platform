# LLM Benchmark Comparison

- Dataset versions: TestNova synthetic evidence-grounded test-case generation@1.0.0
- Winner: not declared

| Run | Provider/model | Completed/total | Structure valid | Evidence proxy | Usefulness proxy | Average request latency | Estimated cost |
|---|---|---:|---:|---:|---:|---:|---:|
| gemini-real-20261113 | gemini/gemini-3.5-flash-lite | 5/5 | 100.00% | 0.8181 | 0.8936 | 1579.6362 ms | n/a |
| groq-real-20261113 | groq/openai/gpt-oss-20b | 5/5 | 100.00% | 0.6926 | 0.8540 | 1229.7860 ms | n/a |

No winner is declared automatically. Ensure runs use the same dataset version and compare only adequately covered, non-mocked measurements.

## Metric detail

| Metric | gemini / gemini-3.5-flash-lite | groq / openai/gpt-oss-20b |
|---|---:|---:|
| Structured-output validity (schema + evidence refs) | 100.00% | 100.00% |
| Evidence accuracy proxy | 0.8181 | 0.6926 |
| Unsupported-claim phrase-match rate | 0.00% | 0.00% |
| Requirement coverage proxy | 100.00% | 100.00% |
| Deterministic usefulness proxy (not human-reviewed) | 0.8936 | 0.8540 |
| Attempt latency average / median | 1579.50 ms / 1311.01 ms | 1229.66 ms / 1349.77 ms |
| Overall request latency average / median | 1579.64 ms / 1311.13 ms | 1229.79 ms / 1349.89 ms |
| Completed / failed / skipped examples | 5 / 0 / 0 of 5 | 5 / 0 / 0 of 5 |
| Input tokens total (coverage) | 1602 (100% coverage) | 1981 (100% coverage) |
| Output tokens total (coverage) | 892 (100% coverage) | 3177 (100% coverage) |
| Total tokens (coverage) | 2494 (100% coverage) | 5158 (100% coverage) |
| Estimated cost (coverage) | n/a (pricing not configured; unknown, not $0) | n/a (pricing not configured; unknown, not $0) |

Latency and tokens are measured from live provider calls. Evidence, unsupported-claim, coverage, and usefulness values are automated proxies; usefulness needs human review. Cost is unavailable because pricing was not configured. This five-example sample is too small to declare a winner.


## Generated outputs for human review
These are retained raw provider outputs. They have not been human-reviewed; automated scores are proxies only.

### gemini / gemini-3.5-flash-lite / SYN-AUTH-POS-001
Status: completed; human review: pending.

```json
{"test_cases":[{"title":"Registered user successfully signs in with correct credentials","description":"Verify that a registered user submitting the correct email address and password is signed in and redirected to the project dashboard.","test_type":"functional","category":"positive","priority":"medium","severity":"medium","preconditions":"User is registered","steps":[{"action":"Submit correct email address and password","expected_result":"User is signed in and taken to the project dashboard"}],"expected_result":"User is signed in and taken to the project dashboard","evidence_chunk_ids":[71001],"requirement_keys":["SYN-AUTH-1"]}]}
```

### gemini / gemini-3.5-flash-lite / SYN-AUTH-NEG-002
Status: completed; human review: pending.

```json
{"test_cases":[{"title":"Sign-in with empty email address","description":"Verify that submitting the sign-in form with an empty email address is rejected and displays the appropriate error message.","test_type":"functional","category":"negative","priority":"medium","severity":"medium","preconditions":"","steps":[{"action":"Submit the sign-in form with an empty email address.","expected_result":"The submission is rejected and displays the message Email is required."}],"expected_result":"The form submission is rejected with the message Email is required.","evidence_chunk_ids":[71011],"requirement_keys":["SYN-AUTH-2"]}]}
```

### gemini / gemini-3.5-flash-lite / SYN-CART-BOUNDARY-003
Status: completed; human review: pending.

```json
{
  "test_cases": [
    {
      "title": "Checkout with six item lines exceeds upper limit",
      "description": "Verify that an order containing more than five item lines is rejected before payment.",
      "test_type": "functional",
      "category": "boundary",
      "priority": "high",
      "severity": "high",
      "preconditions": "User has items in the cart.",
      "steps": [
        {
          "action": "Attempt to checkout an order containing six item lines.",
          "expected_result": "The order is rejected before payment."
        }
      ],
      "expected_result": "Order with six item lines is rejected before payment.",
      "evidence_chunk_ids": [
        71021
      ],
      "requirement_keys": [
        "SYN-CART-1"
      ]
    },
    {
      "title": "Checkout with zero item lines is below lower limit",
      "description": "Verify that an order containing fewer than one item line (zero item lines) is rejected before payment.",
      "test_type": "functional",
      "category": "boundary",
      "priority": "medium",
      "severity": "medium",
      "preconditions": "User has an empty cart.",
      "steps": [
        {
          "action": "Attempt to checkout an order containing zero item lines.",
          "expected_result": "The order is rejected before payment."
        }
      ],
      "expected_result": "Order with zero item lines is rejected before payment.",
      "evidence_chunk_ids": [
        71021
      ],
      "requirement_keys": [
        "SYN-CART-1"
      ]
    }
  ]
}
```

### gemini / gemini-3.5-flash-lite / SYN-RESET-EDGE-004
Status: completed; human review: pending.

```json
{
  "test_cases": [
    {
      "title": "Password reset code rejection after expiration",
      "description": "Verify that a password reset code is rejected when used after fifteen minutes from issuance.",
      "test_type": "functional",
      "category": "positive",
      "priority": "medium",
      "severity": "medium",
      "preconditions": "A password reset code has been issued and more than fifteen minutes have elapsed.",
      "steps": [
        {
          "action": "Attempt to use the expired password reset code.",
          "expected_result": "The password reset code is rejected."
        }
      ],
      "expected_result": "The code used after expiration is rejected.",
      "evidence_chunk_ids": [
        71031
      ],
      "requirement_keys": [
        "SYN-RESET-1"
      ]
    }
  ]
}
```

### gemini / gemini-3.5-flash-lite / SYN-EXPORT-INSUFFICIENT-005
Status: completed; human review: pending.

```json
{"test_cases":[]}
```

### groq / openai/gpt-oss-20b / SYN-AUTH-POS-001
Status: completed; human review: pending.

```json
{"test_cases":[{"title":"SYN-AUTH-POS-001: Successful login with correct credentials","description":"Verify that a registered user can sign in using a valid email address and password and is redirected to the project dashboard.","test_type":"functional","category":"positive","priority":"medium","severity":"medium","preconditions":"A user account exists with email 'user@example.com' and password 'Password123'.","steps":[{"action":"Navigate to the login page","expected_result":"Login page is displayed"},{"action":"Enter email 'user@example.com'","expected_result":"Email field accepts input"},{"action":"Enter password 'Password123'","expected_result":"Password field accepts input"},{"action":"Click the 'Sign In' button","expected_result":"User is authenticated and redirected to the project dashboard"}],"expected_result":"User is signed in and taken to the project dashboard","evidence_chunk_ids":[71001],"requirement_keys":["SYN-AUTH-1"]}]}
```

### groq / openai/gpt-oss-20b / SYN-AUTH-NEG-002
Status: completed; human review: pending.

```json
{"test_cases":[{"title":"SYN-AUTH-2: Empty Email Address Rejection","description":"Verify that submitting the sign-in form with an empty email address is rejected and displays the appropriate error message.","test_type":"functional","category":"negative","priority":"medium","severity":"medium","preconditions":"","steps":[{"action":"Enter an empty string into the email address field and click the submit button","expected_result":"The form submission is rejected and the message \"Email is required.\" is displayed"}],"expected_result":"The form submission is rejected and the message \"Email is required.\" is displayed","evidence_chunk_ids":[71011],"requirement_keys":["SYN-AUTH-2"]}]}
```

### groq / openai/gpt-oss-20b / SYN-CART-BOUNDARY-003
Status: completed; human review: pending.

```json
{"test_cases":[{"title":"SYN-CART-BOUNDARY-001: Checkout with minimum item lines (1)","description":"Verify checkout accepts an order containing exactly one item line.","test_type":"functional","category":"boundary","priority":"medium","severity":"medium","preconditions":"","steps":[{"action":"Add 1 item line to the cart","expected_result":"Checkout proceeds to payment"}],"expected_result":"Checkout proceeds to payment","evidence_chunk_ids":[71021,71022],"requirement_keys":["SYN-CART-1"]},{"title":"SYN-CART-BOUNDARY-002: Checkout with maximum item lines (5)","description":"Verify checkout accepts an order containing exactly five item lines.","test_type":"functional","category":"boundary","priority":"medium","severity":"medium","preconditions":"","steps":[{"action":"Add 5 item lines to the cart","expected_result":"Checkout proceeds to payment"}],"expected_result":"Checkout proceeds to payment","evidence_chunk_ids":[71021,71022],"requirement_keys":["SYN-CART-1"]},{"title":"SYN-CART-NEGATIVE-001: Checkout with zero item lines","description":"Verify checkout rejects an order with no item lines before payment.","test_type":"functional","category":"negative","priority":"medium","severity":"medium","preconditions":"","steps":[{"action":"Attempt to checkout with an empty cart","expected_result":"Checkout is rejected before payment"}],"expected_result":"Checkout is rejected before payment","evidence_chunk_ids":[71021,71022],"requirement_keys":["SYN-CART-1"]},{"title":"SYN-CART-NEGATIVE-002: Checkout with more than maximum item lines (6)","description":"Verify checkout rejects an order containing more than five item lines before payment.","test_type":"functional","category":"negative","priority":"medium","severity":"medium","preconditions":"","steps":[{"action":"Add 6 item lines to the cart","expected_result":"Checkout is rejected before payment"}],"expected_result":"Checkout is rejected before payment","evidence_chunk_ids":[71021,71022],"requirement_keys":["SYN-CART-1"]}]}
```

### groq / openai/gpt-oss-20b / SYN-RESET-EDGE-004
Status: completed; human review: pending.

```json
{"test_cases":[{"title":"Password reset code accepted within 15 minutes","description":"Verify that a password reset code is accepted when used before the 15-minute expiry period.","test_type":"functional","category":"positive","priority":"medium","severity":"medium","preconditions":"","steps":[{"action":"Issue a password reset code to the user","expected_result":"Reset code is generated and sent to the user"},{"action":"Wait 10 minutes","expected_result":"Time elapsed is less than 15 minutes"},{"action":"Submit the reset code to the password reset endpoint","expected_result":"Password reset is successful and user is prompted to set a new password"}],"expected_result":"Password reset succeeds within the 15-minute window","evidence_chunk_ids":[71031],"requirement_keys":["SYN-RESET-1"]},{"title":"Password reset code rejected after 15 minutes","description":"Verify that a password reset code is rejected when used after the 15-minute expiry period.","test_type":"functional","category":"negative","priority":"medium","severity":"medium","preconditions":"","steps":[{"action":"Issue a password reset code to the user","expected_result":"Reset code is generated and sent to the user"},{"action":"Wait 16 minutes","expected_result":"Time elapsed exceeds 15 minutes"},{"action":"Submit the reset code to the password reset endpoint","expected_result":"Password reset is rejected with an error indicating the code has expired"}],"expected_result":"Password reset fails due to expired code","evidence_chunk_ids":[71031],"requirement_keys":["SYN-RESET-1"]}]}
```

### groq / openai/gpt-oss-20b / SYN-EXPORT-INSUFFICIENT-005
Status: completed; human review: pending.

```json
{"test_cases":[{"title":"Verify export feature availability","description":"Ensure that the product provides an export feature as specified.","test_type":"functional","category":"positive","priority":"medium","severity":"medium","preconditions":"","steps":[{"action":"Navigate to the export functionality","expected_result":"Export option is displayed and accessible"}],"expected_result":"Export feature is available for use","evidence_chunk_ids":[71041],"requirement_keys":[]}]}
```
