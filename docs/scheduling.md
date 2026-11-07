# Scheduling recovery and verification

## Decision

Use one external HTTP schedule as the primary: cron-job.org calls GitHub's
`workflow_dispatch` endpoint at minute 7 of every hour (UTC). No server,
Worker, second repository, or Discord credentials are needed outside GitHub.
Keep native cron at minute 17 as a best-effort backup and recovery probe.
Both paths use the existing workflow, concurrency group, and notification ledger.
This intentionally permits extra scans; it does not promise exactly one scan/hour.
If native scheduling later recovers, either disable the external job or remove
native `schedule` after a measured observation period.

**Status: prepared locally, not deployed or verified automatically.** Creating a
successful dispatch manually is only an integration check. The external account,
token and scheduled job must still be configured by the repository owner.

## Independently retrieved evidence (November 7, 2026)

Public REST API and a fresh clone showed:

- Repository ID 1161285744; public, not archived, default branch `main`.
- HEAD `80fe065583e3c1775663fd6f249dcc9718b81c5b`, commit `updating cron`.
  Its YAML uses `*/5 * * * *` and `workflow_dispatch`.
- Workflow ID 235956082, state `active`.
- Latest 100 runs: 97 schedule, 3 workflow_dispatch, all successful.
  Scheduled-run creation times span October 19 04:58:39 to November 7 15:47:51 UTC.
  Median consecutive creation gap: 284.225 minutes (4h44m14s),
  minimum 106.55 minutes, maximum 609.183 minutes.
- All 97 scheduled runs have equal `created_at` and `run_started_at` timestamps.
  These are run timestamps, not proof that each job instantly obtained a runner.
  Sample run 42388107818 was created 15:47:51 UTC; its notify job started
  15:47:54 and finished 15:49:18. No queued or in-progress runs were returned.
- Toronto-date counts: August 24 = 31, August 25 = 33, August 26 = 18,
  August 27 = 3, August 28 = 2. Query covered 04:00 UTC August 24 through
  03:59:59 UTC August 29; all 87 records fit on one page.
- Commit `dd0e458d5cfe3d442279439d06429907c7e5323c` occurs on both sides
  of the decline. Workflow-file git history has no changes between May 22
  and November 5.
- Manual run 42406314476 on the five-minute commit succeeded; the retrieved
  page has no scheduled run on that commit. This snapshot does NOT establish
  whether the five-minute change improved delivery. Do not infer elapsed time
  from this static report or a six-minute observation.

Run evidence: https://github.com/azishqureshi/intern-pal/actions/workflows/main.yml

## What the evidence supports

The leading hypothesis is degraded generation/delivery of native scheduled
events, upstream of ordinary execution. Multi-month gaps with successful short
runs and a sharp decline without a workflow change are not explained by a typo,
missing write permission, notification failures, or normal runner duration.
There is no evidence here of a stuck concurrency backlog; keep the lock.

GitHub's August 26 incident describes saturation of the database processing
Actions triggers and a concurrency-related recovery issue. GitHub marked it
resolved. Similar community reports persisted afterward, including reports that
cron edits, renames and disable/enable did not help. These are correlations and
user reports, not confirmation of a lingering bug or its implementation.
Only GitHub can establish a backend root cause.

Other checks and limits:

- Inactivity auto-disable is inconsistent with active state and ongoing runs.
- Schedule-actor suspension/deprovisioning is a documented cause. Public evidence
  does not verify account status; intermittent successful schedule delivery makes
  complete actor failure less likely. A cron edit by an active writer is the
  documented recovery for that particular condition, not a universal repair.
- `[skip ci]` applies to push/PR, not schedule. State writes are not the trigger problem.
- Node deprecation warnings are not evidence of missing schedule events.
- Actions policy/admin permissions and complete manual logs were supplied by the
  owner, not independently fetched with privileged access during this check.
- Cron off the hour reduces one documented contention risk but cannot be claimed
  to repair this sustained degradation. Renaming or disabling an active workflow
  would disturb evidence without an established benefit; this patch does neither.

Sources:
- https://www.githubstatus.com/incidents/y1t7p9fzrlj2
- https://github.com/orgs/community/discussions/207346
- https://docs.github.com/en/actions/how-tos/troubleshoot-workflows
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

## Deployment and exact account setup

1. Merge this change to `main` first. Confirm the default-branch workflow has
   `trigger_source` and the production cron `17 * * * *`.
2. In GitHub Settings → Developer settings → Personal access tokens →
   Fine-grained tokens, create a dedicated token for resource owner
   `azishqureshi`, **only** repository `intern-pal`, repository permission
   **Actions: Read and write** (Metadata read is implicit). Do not grant Contents
   write. Choose an expiry and set a renewal reminder. Store it in a password
   manager. The existing workflow's GITHUB_TOKEN still handles state commits.
3. Sign up at https://console.cron-job.org/ and create one job with the following
   configuration. Enter the token directly in that service's header field;
   never commit it or paste it into a chat. The scheduler must be trusted with
   this repository-scoped token; Actions write allows more than dispatch alone.

   | Field | Value |
   | --- | --- |
   | Name | Intern Pal hourly |
   | URL | `https://api.github.com/repos/azishqureshi/intern-pal/actions/workflows/main.yml/dispatches` |
   | Method | `POST` |
   | Schedule | Custom: minute `7`, every hour/day/month/weekday |
   | Timezone | `UTC` |
   | Header `Accept` | `application/vnd.github+json` |
   | Header `Authorization` | `Bearer YOUR_FINE_GRAINED_TOKEN` |
   | Header `Content-Type` | `application/json` |
   | Header `X-GitHub-Api-Version` | `2022-11-28` |
   | Body | `{"ref":"main","inputs":{"trigger_source":"external-scheduler"}}` |

4. Enable failure/recovery and automatic-disable email notifications. Do not use
   the console's Basic authentication fields for this token. A normal dispatch
   response is HTTP 204 with no body; it acknowledges acceptance, not completion.
5. Use the console's test execution once and check the matching GitHub run and
   state-push step. Record that this was a test, then wait for actual scheduled
   executions. Turn off any other external dispatcher to avoid redundant calls.
6. On 401 check expiry/revocation; on 403 check repo access, Actions write and
   rate limits; on 404 verify owner/repo/path/access; on 422 check that the input
   exists on main and ref is main. Do not repeatedly dispatch on ambiguous network
   errors: a timed-out request may already have created a run.

This service currently offers free schedules, POST bodies, custom headers and
failure notifications. It does not guarantee exact punctuality and can disable
jobs after repeated failures. Its 30-second HTTP timeout is sufficient for
submitting a dispatch; it does not wait for the notifier to finish.

- https://cron-job.org/en/faq/
- https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event

## Notification history and concurrency

No changes to `state.json`, `notified.json`, notification code, or ledger format
are part of this patch. Both trigger paths use `internship-notifications` with
`cancel-in-progress: false`. Checkout explicitly fetches the current default
branch when a job gets the lock, so a later job reads the previous job's committed
history rather than the dispatch-time commit. The always-run commit/push and
recovery artifact steps remain intact. Existing pending/sent ledger handling
prevents normal repeated scans from re-sending the same jobs.

This is not an exactly-once guarantee across Discord and Git: if a runner dies
or cannot persist history after delivering a message, a later run can still
lack that reservation. A failed state push needs investigation and artifact
recovery before further dispatches; never delete/reset the ledger to repair cron.
GitHub concurrency also permits pending-run replacement; no FIFO promise is made.

## Automatic acceptance test

Record activation time in UTC. Exclude the manual console test. For a complete
24-hour window starting on an hourly slot boundary, compare all 24 expected
external slots against cron-job.org execution history AND GitHub run IDs:

- Each automatic HTTP call is accepted, with a corresponding new GitHub
  `workflow_dispatch` run titled `... | external-scheduler`.
- Each run is created within 5 minutes of its slot and completes within the
  existing 20-minute job timeout, including successful state persistence.
- No interval between automatic successful runs exceeds 75 minutes. A missing
  run, failed/canceled execution, or failed state push fails the acceptance test.
- Continue the same checks for 72 hours (72 slots). This demonstrates observed
  recovery over that window, not a future SLA. Scheduler HTTP success alone
  does not monitor notifier success; enable GitHub Actions failure notifications.
- Confirm normal state entries are retained and no duplicate notifications occur.
  A successful no-new-jobs run need not create a state commit.

Read-only evidence helper (replace times with the actual observation window):

```bash
python scripts/audit_schedule.py --source external \
  --since 2026-11-08T00:07:00Z --until 2026-11-09T00:07:00Z
python scripts/audit_schedule.py --source native \
  --since 2026-11-08T00:17:00Z --until 2026-11-09T00:17:00Z
```

The helper paginates, separates sources, excludes reruns, and measures edge
outages even when no runs exist. It deliberately does not pronounce recovery:
external labels can be manually selected, and GitHub does not store the nominal
cron slot in the run timestamps. Cross-check scheduler history. Use an optional
GH_TOKEN environment variable for higher read rate limits, never a CLI argument.

For a native-only trial, observe 72 hours of actual `event=schedule` runs against
minute-17 hourly slots with the same acceptance criteria. If multi-hour gaps persist,
retain the external primary. A manual success never counts toward this trial.

## Escalation and rollback

Submit the evidence above privately to GitHub Support (or the existing community
thread if support is unavailable), asking them to inspect scheduled-event
creation/delivery and actor eligibility for repository 1161285744 / workflow
235956082. Include run IDs, timestamp pairs, historical counts, and unchanged
commit across August 26; do not assert that the resolved incident is the cause.

Rollback: disable the external job first, revoke its dedicated token, and retain
native cron at minute 17. Removing the optional input/run-name is safe after external
calls stop. Do not restore five-minute testing cron or change notification history.
