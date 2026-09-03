TestNova Sample Documents
=========================

Use these sample files to manually test the dashboard's dynamic Release
Confidence. Upload them in the Upload Center, process them, and (optionally)
generate embeddings, then watch Release Confidence, overall coverage, and the
recommendation change on the Dashboard.

Files in this folder
--------------------
1. checkout-flow.txt        - Plain text describing an e-commerce checkout flow.
2. auth-suite.csv           - CSV describing authentication test scenarios.
3. search-api.json          - JSON spec for a search API request/response model.
4. release-notes.txt        - Longer release notes (creates several chunks).
-------------------------------------------------------------------------------
HOW TO REPRODUCE EACH SCENARIO
------------------------------

Baseline (Release Confidence = high)
  a. Create a project (Projects page) and upload + process + embed one of the
     sample documents.
  b. Check Dashboard -> Release Confidence should be high (e.g. 100).

Scenario A - Add a project with NO documents
  a. Create a second project but upload nothing to it.
  b. Dashboard: total_projects goes up, healthy % drops, Release Confidence drops.

Scenario B - Upload a document but do NOT generate embeddings
  a. In the second project, upload checkout-flow.txt and click "Process"
     (this creates chunks) but DO NOT generate embeddings.
  b. Dashboard: overall coverage drops, knowledge health drops,
     Release Confidence drops further.

Scenario C - Generate embeddings
  a. Generate embeddings for that document.
  b. Dashboard: coverage returns to 100%, knowledge health recovers,
     Release Confidence rises again.

Recommended: Projects page -> Upload Center (per project).
The exact upload/process/embed buttons are provided by the TestNova UI.
