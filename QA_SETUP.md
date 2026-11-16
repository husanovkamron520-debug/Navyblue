# SupplyChain14 QA from Navyblue

Navyblue can launch the SupplyChain14 competition QA workflow from a private Telegram chat. At this stage the commands are restricted to the configured bot owner (OWNER_CHAT_ID).

## One-time setup

1. Open GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens.
2. Create a token for resource owner husanovkamron520-debug.
3. Restrict repository access to only Navyblue.
4. Grant Actions: Read and write. Keep Metadata read-only (the default).
5. Copy the token once. Do not send it in Telegram or commit it to the repository.
6. Open Render → the existing Navyblue service → Environment and add:
   - QA_GITHUB_TOKEN = the fine-grained token
   - OWNER_CHAT_ID = your Telegram private chat ID (if it is not already configured)
7. Save changes and allow Render to restart the service.

Optional:
- QA_GITHUB_REPO defaults to husanovkamron520-debug/Navyblue.
- QA_WORKFLOW_FILE defaults to competition-qa.yml.

## Telegram commands

- /qa — run all virtual roster scenarios (15, 16, 19 and 20 students).
- /qa 15, /qa 16, /qa 19, /qa 20 — run one roster scenario.
- /qa_status — check the latest run.

Navyblue sends the result to the owner chat when the workflow finishes.

## Safety boundaries

- The workflow checks out SupplyChain14 and starts a fresh local Supabase stack inside a GitHub Actions runner.
- It applies the checked-in competition SQL in the documented order.
- Virtual accounts, classrooms, teams and memberships are created only in that temporary database; the SQL test ends with ROLLBACK.
- No production Supabase URL, anon key, service-role key, or production database credentials are used.
- The bot token is only used to dispatch and read workflow runs in the Navyblue repository.
- The workflow is serialized so two competition QA runs cannot modify the same runner at once.

## Current automated coverage

- 15 students → 3 balanced teams of 5.
- 16 students → 3 balanced teams of 6/5/5.
- 19 students → 3 balanced teams of 7/6/6.
- 20 students → 4 balanced teams of 5.
- Every team covers procurement, supplier, manufacturer, warehouse and transport.
- A 14-student roster is rejected for 3 teams.
- Anonymous execution of the protected team-assignment and task-grading RPCs is denied.

This first integration automates roster, role-coverage and permission QA. It does not yet replace the deeper task-submission, grading, decision-scoring and finalization lifecycle test; that can be added to the same isolated workflow after the first run is verified.
