# LLM benchmark quality review

> Preliminary assistant analysis only. No human review has been performed. Automated lexical/citation signals are not proof of semantic correctness.

## Scope and provenance

- Dataset: synthetic test-case generation v1.0.0; source: `../../evaluation_datasets/test_case_generation_v1.json`.
- Providers: Gemini `gemini-3.5-flash-lite` and Groq `openai/gpt-oss-20b`; five examples each.
- Original raw outputs remain unchanged in the referenced benchmark JSON files. This review stores output hashes and parsed cases for traceability.
- Benchmark metrics are example-level automated heuristics. Case assessments are preliminary assistant observations, not human findings.

## Review summary

| Provider | Generated cases | Needs evidence/product clarification | Status |
|---|---:|---|---|
| gemini | 5 | Yes | Pending human review |
| groq | 9 | Yes | Pending human review |

## Case-by-case assessment

### gemini:SYN-AUTH-POS-001:case-01 - Registered user successfully signs in with correct credentials

- Source: [`../gemini-real-run/gemini-real-20261113.json`](../gemini-real-run/gemini-real-20261113.json) - example `SYN-AUTH-POS-001`, raw SHA-256 `60e5643851d0f8a2b1e6449373d0da0d9cc2ed66f0b61d0de4583cab0ee34e36`.
- Cited evidence: [71001] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `supported`; requirement coverage `complete`; action clarity `clear_but_high_level`; expected result `specific`; redundancy `not_redundant`; usefulness `useful_with_setup`.
- Unsupported assumptions / concerns: []
- Notes: The expected sign-in and dashboard outcome are in evidence 71001. The abbreviated action and precondition may need environment-specific setup.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "Registered user successfully signs in with correct credentials",
  "description": "Verify that a registered user submitting the correct email address and password is signed in and redirected to the project dashboard.",
  "test_type": "functional",
  "category": "positive",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "User is registered",
  "steps": [
    {
      "action": "Submit correct email address and password",
      "expected_result": "User is signed in and taken to the project dashboard"
    }
  ],
  "expected_result": "User is signed in and taken to the project dashboard",
  "evidence_chunk_ids": [
    71001
  ],
  "requirement_keys": [
    "SYN-AUTH-1"
  ]
}
```

### gemini:SYN-AUTH-NEG-002:case-01 - Sign-in with empty email address

- Source: [`../gemini-real-run/gemini-real-20261113.json`](../gemini-real-run/gemini-real-20261113.json) - example `SYN-AUTH-NEG-002`, raw SHA-256 `a8b0bb5f35c1e13e055953027bf38cb94a36d7fc06acaae75fbfc3b5e546e574`.
- Cited evidence: [71011] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `supported`; requirement coverage `complete`; action clarity `clear`; expected result `specific`; redundancy `not_redundant`; usefulness `useful`.
- Unsupported assumptions / concerns: []
- Notes: The empty-email rejection and exact message are explicitly stated in evidence 71011.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "Sign-in with empty email address",
  "description": "Verify that submitting the sign-in form with an empty email address is rejected and displays the appropriate error message.",
  "test_type": "functional",
  "category": "negative",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "",
  "steps": [
    {
      "action": "Submit the sign-in form with an empty email address.",
      "expected_result": "The submission is rejected and displays the message Email is required."
    }
  ],
  "expected_result": "The form submission is rejected with the message Email is required.",
  "evidence_chunk_ids": [
    71011
  ],
  "requirement_keys": [
    "SYN-AUTH-2"
  ]
}
```

### gemini:SYN-CART-BOUNDARY-003:case-01 - Checkout with six item lines exceeds upper limit

- Source: [`../gemini-real-run/gemini-real-20261113.json`](../gemini-real-run/gemini-real-20261113.json) - example `SYN-CART-BOUNDARY-003`, raw SHA-256 `225aaa48faad9c575d1a339b608a05f4cc5ecd17b4c6f4d620e7a7bd8cf8ac03`.
- Cited evidence: [71021] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `supported`; requirement coverage `complete`; action clarity `clear`; expected result `specific`; redundancy `not_redundant`; usefulness `useful`.
- Unsupported assumptions / concerns: []
- Notes: Six lines exceed the documented five-line maximum and rejection-before-payment behavior is explicit in 71021.
- Human decision: pending; comments/rating: blank.

```json
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
}
```

### gemini:SYN-CART-BOUNDARY-003:case-02 - Checkout with zero item lines is below lower limit

- Source: [`../gemini-real-run/gemini-real-20261113.json`](../gemini-real-run/gemini-real-20261113.json) - example `SYN-CART-BOUNDARY-003`, raw SHA-256 `225aaa48faad9c575d1a339b608a05f4cc5ecd17b4c6f4d620e7a7bd8cf8ac03`.
- Cited evidence: [71021] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `inconclusive`; requirement coverage `complete`; action clarity `clear`; expected result `specific_but_unsubstantiated`; redundancy `not_redundant`; usefulness `hold_pending_evidence`.
- Unsupported assumptions / concerns: ['Rejecting a zero-line order is not explicitly documented.']
- Notes: Evidence says accepted orders contain one through five lines, but does not state the behavior of a zero-line order.
- Human decision: pending; comments/rating: blank.

```json
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
```

### gemini:SYN-RESET-EDGE-004:case-01 - Password reset code rejection after expiration

- Source: [`../gemini-real-run/gemini-real-20261113.json`](../gemini-real-run/gemini-real-20261113.json) - example `SYN-RESET-EDGE-004`, raw SHA-256 `c31b602cc00e94c0cfd883426f4e03ffe94880b95083b9b912cd75fa7a5c9609`.
- Cited evidence: [71031] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `partially_supported`; requirement coverage `complete`; action clarity `clear`; expected result `specific`; redundancy `not_redundant`; usefulness `useful_after_revision`.
- Unsupported assumptions / concerns: ['Scenario behavior is supported, but category positive conflicts with expected edge coverage; negative/edge classification should be reviewed.']
- Notes: Rejection after expiry is explicit in 71031; the dataset asks for edge coverage, but the output labels this as positive.
- Human decision: pending; comments/rating: blank.

```json
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
```

### gemini:SYN-EXPORT-INSUFFICIENT-005 - no generated cases

- Source: [`../gemini-real-run/gemini-real-20261113.json`](../gemini-real-run/gemini-real-20261113.json) - raw SHA-256 `f31dd121041d129ad7ba6f39e88d146e34adc65bc6bbc652228d9c2e3523ffdd`.
- Preliminary finding: empty output is consistent with the insufficient-evidence guidance.
- Human decision: pending; comments/rating: blank.

### groq:SYN-AUTH-POS-001:case-01 - SYN-AUTH-POS-001: Successful login with correct credentials

- Source: [`../groq-real-run/groq-real-20261113.json`](../groq-real-run/groq-real-20261113.json) - example `SYN-AUTH-POS-001`, raw SHA-256 `07002743342b1a511a1d9fc050e1921f970145c71163c510758c302408a3d105`.
- Cited evidence: [71001] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `partially_supported`; requirement coverage `complete`; action clarity `clear`; expected result `specific_but_contaminated_by_assumptions`; redundancy `not_redundant`; usefulness `revise_before_use`.
- Unsupported assumptions / concerns: ['Invented example email/password, page/navigation control names, field-acceptance behavior, and sign-in button label.']
- Notes: Final sign-in and dashboard outcome are supported. Specific credentials and intermediate UI behaviors are absent from evidence 71001.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "SYN-AUTH-POS-001: Successful login with correct credentials",
  "description": "Verify that a registered user can sign in using a valid email address and password and is redirected to the project dashboard.",
  "test_type": "functional",
  "category": "positive",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "A user account exists with email 'user@example.com' and password 'Password123'.",
  "steps": [
    {
      "action": "Navigate to the login page",
      "expected_result": "Login page is displayed"
    },
    {
      "action": "Enter email 'user@example.com'",
      "expected_result": "Email field accepts input"
    },
    {
      "action": "Enter password 'Password123'",
      "expected_result": "Password field accepts input"
    },
    {
      "action": "Click the 'Sign In' button",
      "expected_result": "User is authenticated and redirected to the project dashboard"
    }
  ],
  "expected_result": "User is signed in and taken to the project dashboard",
  "evidence_chunk_ids": [
    71001
  ],
  "requirement_keys": [
    "SYN-AUTH-1"
  ]
}
```

### groq:SYN-AUTH-NEG-002:case-01 - SYN-AUTH-2: Empty Email Address Rejection

- Source: [`../groq-real-run/groq-real-20261113.json`](../groq-real-run/groq-real-20261113.json) - example `SYN-AUTH-NEG-002`, raw SHA-256 `15e72f35f80d317973abc63bddbeb18438e9600438b3a4b58dd8fa4503e53797`.
- Cited evidence: [71011] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `supported`; requirement coverage `complete`; action clarity `clear`; expected result `specific`; redundancy `not_redundant`; usefulness `useful_with_possible_step_split`.
- Unsupported assumptions / concerns: ['Punctuation in the rendered error text may differ; verify exact message formatting.']
- Notes: Empty email rejection and ?Email is required? are explicit in 71011.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "SYN-AUTH-2: Empty Email Address Rejection",
  "description": "Verify that submitting the sign-in form with an empty email address is rejected and displays the appropriate error message.",
  "test_type": "functional",
  "category": "negative",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "",
  "steps": [
    {
      "action": "Enter an empty string into the email address field and click the submit button",
      "expected_result": "The form submission is rejected and the message \"Email is required.\" is displayed"
    }
  ],
  "expected_result": "The form submission is rejected and the message \"Email is required.\" is displayed",
  "evidence_chunk_ids": [
    71011
  ],
  "requirement_keys": [
    "SYN-AUTH-2"
  ]
}
```

### groq:SYN-CART-BOUNDARY-003:case-01 - SYN-CART-BOUNDARY-001: Checkout with minimum item lines (1)

- Source: [`../groq-real-run/groq-real-20261113.json`](../groq-real-run/groq-real-20261113.json) - example `SYN-CART-BOUNDARY-003`, raw SHA-256 `574c8651633bfa5663372a7242d4f8aa2038a88f8b6dc188882e8a9f4cae2db2`.
- Cited evidence: [71021, 71022] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `partially_supported`; requirement coverage `complete`; action clarity `clear`; expected result `specific_but_ui_outcome_inferred`; redundancy `not_redundant`; usefulness `useful_pending_oracle_confirmation`.
- Unsupported assumptions / concerns: ['?Checkout proceeds to payment? is a concrete UI transition not stated verbatim; acceptance is documented.']
- Notes: One item line is within the accepted range. Evidence 71022 constrains item lines versus per-line quantity but does not specify a payment-page transition.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "SYN-CART-BOUNDARY-001: Checkout with minimum item lines (1)",
  "description": "Verify checkout accepts an order containing exactly one item line.",
  "test_type": "functional",
  "category": "boundary",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "",
  "steps": [
    {
      "action": "Add 1 item line to the cart",
      "expected_result": "Checkout proceeds to payment"
    }
  ],
  "expected_result": "Checkout proceeds to payment",
  "evidence_chunk_ids": [
    71021,
    71022
  ],
  "requirement_keys": [
    "SYN-CART-1"
  ]
}
```

### groq:SYN-CART-BOUNDARY-003:case-02 - SYN-CART-BOUNDARY-002: Checkout with maximum item lines (5)

- Source: [`../groq-real-run/groq-real-20261113.json`](../groq-real-run/groq-real-20261113.json) - example `SYN-CART-BOUNDARY-003`, raw SHA-256 `574c8651633bfa5663372a7242d4f8aa2038a88f8b6dc188882e8a9f4cae2db2`.
- Cited evidence: [71021, 71022] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `partially_supported`; requirement coverage `complete`; action clarity `clear`; expected result `specific_but_ui_outcome_inferred`; redundancy `not_redundant`; usefulness `useful_pending_oracle_confirmation`.
- Unsupported assumptions / concerns: ['?Checkout proceeds to payment? is a concrete UI transition not stated verbatim; acceptance is documented.']
- Notes: Five item lines are within the accepted range; the exact next screen is not stated by 71021.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "SYN-CART-BOUNDARY-002: Checkout with maximum item lines (5)",
  "description": "Verify checkout accepts an order containing exactly five item lines.",
  "test_type": "functional",
  "category": "boundary",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "",
  "steps": [
    {
      "action": "Add 5 item lines to the cart",
      "expected_result": "Checkout proceeds to payment"
    }
  ],
  "expected_result": "Checkout proceeds to payment",
  "evidence_chunk_ids": [
    71021,
    71022
  ],
  "requirement_keys": [
    "SYN-CART-1"
  ]
}
```

### groq:SYN-CART-BOUNDARY-003:case-03 - SYN-CART-NEGATIVE-001: Checkout with zero item lines

- Source: [`../groq-real-run/groq-real-20261113.json`](../groq-real-run/groq-real-20261113.json) - example `SYN-CART-BOUNDARY-003`, raw SHA-256 `574c8651633bfa5663372a7242d4f8aa2038a88f8b6dc188882e8a9f4cae2db2`.
- Cited evidence: [71021, 71022] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `inconclusive`; requirement coverage `complete`; action clarity `clear`; expected result `specific_but_unsubstantiated`; redundancy `not_redundant`; usefulness `hold_pending_evidence`.
- Unsupported assumptions / concerns: ['Rejecting an empty cart is not explicitly documented.']
- Notes: The documented accepted range starts at one, but no zero-line rejection behavior is specified.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "SYN-CART-NEGATIVE-001: Checkout with zero item lines",
  "description": "Verify checkout rejects an order with no item lines before payment.",
  "test_type": "functional",
  "category": "negative",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "",
  "steps": [
    {
      "action": "Attempt to checkout with an empty cart",
      "expected_result": "Checkout is rejected before payment"
    }
  ],
  "expected_result": "Checkout is rejected before payment",
  "evidence_chunk_ids": [
    71021,
    71022
  ],
  "requirement_keys": [
    "SYN-CART-1"
  ]
}
```

### groq:SYN-CART-BOUNDARY-003:case-04 - SYN-CART-NEGATIVE-002: Checkout with more than maximum item lines (6)

- Source: [`../groq-real-run/groq-real-20261113.json`](../groq-real-run/groq-real-20261113.json) - example `SYN-CART-BOUNDARY-003`, raw SHA-256 `574c8651633bfa5663372a7242d4f8aa2038a88f8b6dc188882e8a9f4cae2db2`.
- Cited evidence: [71021, 71022] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `supported`; requirement coverage `complete`; action clarity `clear`; expected result `specific`; redundancy `not_redundant`; usefulness `useful`.
- Unsupported assumptions / concerns: []
- Notes: More than five item lines are explicitly rejected before payment in 71021.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "SYN-CART-NEGATIVE-002: Checkout with more than maximum item lines (6)",
  "description": "Verify checkout rejects an order containing more than five item lines before payment.",
  "test_type": "functional",
  "category": "negative",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "",
  "steps": [
    {
      "action": "Add 6 item lines to the cart",
      "expected_result": "Checkout is rejected before payment"
    }
  ],
  "expected_result": "Checkout is rejected before payment",
  "evidence_chunk_ids": [
    71021,
    71022
  ],
  "requirement_keys": [
    "SYN-CART-1"
  ]
}
```

### groq:SYN-RESET-EDGE-004:case-01 - Password reset code accepted within 15 minutes

- Source: [`../groq-real-run/groq-real-20261113.json`](../groq-real-run/groq-real-20261113.json) - example `SYN-RESET-EDGE-004`, raw SHA-256 `d33d1dcd63b9bbeb62fd6bc67fbe7cfd6acab0ef6f74cf1ce011834f3008eb9e`.
- Cited evidence: [71031] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `inconclusive`; requirement coverage `complete`; action clarity `clear`; expected result `specific_but_unsubstantiated`; redundancy `not_redundant`; usefulness `hold_pending_evidence`.
- Unsupported assumptions / concerns: ['Acceptance before expiry, reset-code delivery, endpoint, successful reset, and prompting for a new password are not documented.']
- Notes: Available evidence documents expiry and rejection after expiry, not successful use before expiry.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "Password reset code accepted within 15 minutes",
  "description": "Verify that a password reset code is accepted when used before the 15-minute expiry period.",
  "test_type": "functional",
  "category": "positive",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "",
  "steps": [
    {
      "action": "Issue a password reset code to the user",
      "expected_result": "Reset code is generated and sent to the user"
    },
    {
      "action": "Wait 10 minutes",
      "expected_result": "Time elapsed is less than 15 minutes"
    },
    {
      "action": "Submit the reset code to the password reset endpoint",
      "expected_result": "Password reset is successful and user is prompted to set a new password"
    }
  ],
  "expected_result": "Password reset succeeds within the 15-minute window",
  "evidence_chunk_ids": [
    71031
  ],
  "requirement_keys": [
    "SYN-RESET-1"
  ]
}
```

### groq:SYN-RESET-EDGE-004:case-02 - Password reset code rejected after 15 minutes

- Source: [`../groq-real-run/groq-real-20261113.json`](../groq-real-run/groq-real-20261113.json) - example `SYN-RESET-EDGE-004`, raw SHA-256 `d33d1dcd63b9bbeb62fd6bc67fbe7cfd6acab0ef6f74cf1ce011834f3008eb9e`.
- Cited evidence: [71031] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `partially_supported`; requirement coverage `complete`; action clarity `clear`; expected result `specific_but_partly_unsubstantiated`; redundancy `not_redundant`; usefulness `useful_after_revision`.
- Unsupported assumptions / concerns: ['Specific expired-code error text is not documented; setup and delivery details are assumptions.']
- Notes: Rejection after 15 minutes is documented; 16 minutes is beyond the threshold, but the exact error text is not.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "Password reset code rejected after 15 minutes",
  "description": "Verify that a password reset code is rejected when used after the 15-minute expiry period.",
  "test_type": "functional",
  "category": "negative",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "",
  "steps": [
    {
      "action": "Issue a password reset code to the user",
      "expected_result": "Reset code is generated and sent to the user"
    },
    {
      "action": "Wait 16 minutes",
      "expected_result": "Time elapsed exceeds 15 minutes"
    },
    {
      "action": "Submit the reset code to the password reset endpoint",
      "expected_result": "Password reset is rejected with an error indicating the code has expired"
    }
  ],
  "expected_result": "Password reset fails due to expired code",
  "evidence_chunk_ids": [
    71031
  ],
  "requirement_keys": [
    "SYN-RESET-1"
  ]
}
```

### groq:SYN-EXPORT-INSUFFICIENT-005:case-01 - Verify export feature availability

- Source: [`../groq-real-run/groq-real-20261113.json`](../groq-real-run/groq-real-20261113.json) - example `SYN-EXPORT-INSUFFICIENT-005`, raw SHA-256 `049fcafdf2dc6d5267dafb9b1d6bc1a995edfa6b167a660cd0e56036e9282265`.
- Cited evidence: [71041] (IDs valid: True; semantic support: not established).
- Preliminary findings: correctness `inconclusive`; requirement coverage `not_applicable`; action clarity `partial`; expected result `specific_but_unsubstantiated`; redundancy `not_redundant`; usefulness `hold_pending_evidence`.
- Unsupported assumptions / concerns: ['Navigation path, visible/accessibility state, and usability are not supported by the statement that an export feature exists.']
- Notes: Evidence 71041 confirms only that an export feature exists and supplies no user-observable behavior.
- Human decision: pending; comments/rating: blank.

```json
{
  "title": "Verify export feature availability",
  "description": "Ensure that the product provides an export feature as specified.",
  "test_type": "functional",
  "category": "positive",
  "priority": "medium",
  "severity": "medium",
  "preconditions": "",
  "steps": [
    {
      "action": "Navigate to the export functionality",
      "expected_result": "Export option is displayed and accessible"
    }
  ],
  "expected_result": "Export feature is available for use",
  "evidence_chunk_ids": [
    71041
  ],
  "requirement_keys": []
}
```

## Human-review template

Complete for each case. Use `inconclusive` when the supplied evidence cannot settle a point. Valid citation IDs and lexical overlap do not prove semantic entailment.

```text
Case review ID:
Reviewer name/role:
Reviewer decision: accept / revise / reject / inconclusive
Reviewer comments:
Evidence traceability (1-5 or inconclusive):
Requirement coverage (1-5 or inconclusive):
Scenario correctness (1-5 or inconclusive):
Action clarity (1-5 or inconclusive):
Expected-result specificity (1-5 or inconclusive):
Unsupported assumptions (none / list / inconclusive):
Redundancy (none / possible / confirmed / inconclusive):
Practical usefulness (1-5 or inconclusive):
Final rating: accept / revise / reject / inconclusive
Review date:
```

## Limitations

- All assessments here are assistant-generated preliminary observations. Every human-review field is intentionally blank/pending.
- Benchmark scores are example-level deterministic proxies, not per-case semantic proof. The raw provider outputs in source files are unchanged.
- Cross-provider cases are not considered redundant solely because they address the same dataset requirement; redundancy comparisons are within each provider/example output.
