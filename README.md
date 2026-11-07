# Intern Pal

A small Python job-discovery bot that sends Canadian internship notifications to Discord. No database or web interface is required. The workflow supports hourly external dispatch, with native GitHub cron as a best-effort backup; see [scheduling setup](docs/scheduling.md).

## Run

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Only one repository secret is used:

- `DISCORD_WEBHOOK_GENERAL`: destination for every source, including CIBC and AMD.

The old `DISCORD_WEBHOOK_CIBC` and `DISCORD_WEBHOOK_AMD` secrets are ignored, even if they remain configured. You can remove them, but it is not required. Previously announced jobs in those channels remain recognized and are not reposted to general.

A unique opportunity is sent to **the general channel once**, even if several sources discover it. No channels are created. The existing embed fields remain, with a term added when known. `MAX_AGE_DAYS_GENERAL` still defaults to `0` for listings with an age, preserving SimplifyJobs' existing rule. Corporate listings use full posting details and have no age restriction, as the existing corporate watchers did.

To inspect live sources without Discord calls or state writes:

```sh
.venv/bin/python scripts/check_sources.py cibc rbc bmo td scotiabank shopify google amazon canadianlist
```

To preview the complete notification pipeline, including deduplication against existing history:

```sh
DRY_RUN=1 .venv/bin/python notify_canada_interns.py
```

For normal operation, set `DISCORD_WEBHOOK_GENERAL` and run `python notify_canada_interns.py`, or use the existing workflow. The first normal scan can announce currently open, previously unseen corporate jobs. Verification during development did not send live Discord messages or change either historical JSON file.

## Sources and scope

| Source | Official board and retrieval method |
| --- | --- |
| SimplifyJobs | Existing Summer2026 repository URL, section, Canada filter and age behavior retained. Only two confirmed parsing bugs changed: missing links no longer inherit another role's URL, and company inheritance is resolved before location filtering. |
| Canadian Internship List | [Bobwillrule/Canadian-Internship-List](https://github.com/Bobwillrule/Canadian-Internship-List): the complete public README table, across all terms and disciplines, with no posting-age cutoff. Closed/missing links and unverified Canadian locations are skipped. Known shortened application links are resolved before duplicate matching. Like SimplifyJobs, this source trusts list curation rather than applying the corporate full-description classifier. |
| AMD | Existing watcher retained; notifications go to general and participate in shared deduplication. Its existing extraction/filtering behavior is unchanged. |
| CIBC | [Campus](https://cibc.wd3.myworkdayjobs.com/campus): paginated Workday CXS search, Canadian country facet, then full job details. |
| RBC | [Early Talent](https://rbc.wd3.myworkdayjobs.com/RBCEARLYTALENT1): same Workday adapter; all pages, then full details. |
| BMO | [Campus](https://bmo.wd3.myworkdayjobs.com/Campus): same adapter, with BMO's `Country` facet. |
| TD | [Careers](https://td.wd3.myworkdayjobs.com/TD_Bank_Careers): same adapter, Canadian country and official Campus job-family facets. This deliberately covers the Campus category, not every job in TD's large general board. |
| Scotiabank | [Student & New Grad](https://jobs.scotiabank.com/go/Student-&-New-Grad-Jobs/2298417/): paginated public HTML and job-detail microdata. URL posting IDs and requisition IDs are kept distinct. |
| Shopify | [Jobs](https://www.shopify.com/careers/jobs) and [internship programme](https://internships.shopify.com/): public rendered links and role descriptions. Expired links are skipped. “Remote — Americas” alone does not establish Canadian eligibility. |
| Google | [Canadian internships](https://www.google.com/about/careers/applications/jobs/results/?location=Canada&employment_type=INTERN): public rendered search pages and semantic job-detail headings. Missing qualifications, responsibilities, application links or pagination counts fail closed. |
| Amazon / AWS | [Public search feed](https://www.amazon.jobs/en/search.json?normalized_country_code%5B%5D=CAN): paginated Canadian results containing descriptions and qualifications. Country filtering is checked locally. |

No paid APIs, browser automation, LLM service, or additional Python runtime dependencies were introduced. Sources run independently. Requests have timeouts; detail requests are paced. Malformed/truncated/repeated pagination is reported as a failure rather than an empty board. Individual unavailable details are logged as incomplete and never approved using search summaries. Failed scans do not delete jobs or reset history.

Live checks on November 5, 2026 found 3 accepted CIBC roles, 6 RBC roles, and 4 Amazon roles. BMO, Scotiabank, Shopify, Google, and TD returned no accepted roles in the checked scope. A TD commercial-banking detail request was unavailable, so that scan was incomplete; no inference about that job was made. Shopify's programme link was expired (HTTP 410). Google had student research/graduate listings but no postings meeting the conservative undergraduate CS checks. These are dated observations, not assertions that those companies never have internships.

## Corporate filtering

`filtering.py` evaluates explicit Canadian location/remote eligibility, placement evidence, employment type, title, available category, and description. Full-time hours do not imply permanent employment. Permanent, senior, graduate-only and unrelated primary roles are rejected. A “technology” title or CS degree requirement is insufficient.

Technical duties require action/object evidence (for example, building software or data pipelines, writing code/tests, provisioning cloud infrastructure, or performing security assessments) with technical skill corroboration. Unconventional titles need stronger responsibility evidence. Developer innovation programmes can qualify when they explicitly require delivering a functional prototype plus programming and software-development skills. Each decision has a reason.

This is a deterministic evidence filter, not a general natural-language classifier. Ambiguous postings and unsupported wording can be missed; positive and negative fixtures should accompany any future rule changes. SimplifyJobs and AMD keep their previous source-specific eligibility behavior.

The Canadian Internship List is intentionally broader: it includes winter, summer,
fall, hardware, product, and graduate placements present in that list. Its posting
date is informational and is not subject to SimplifyJobs' `0d` rule. Existing
notification history suppresses recognized duplicates. The first successful scan
records the list's current entries as `seen` without announcing the backlog; future
additions are eligible for notification. The one-time baseline is saved atomically
in the shared ledger before any messages are sent, and persists across restarts.
Existing `sent` and `pending` records retain their status. Do not reset the baseline
or history to retry a fetch. An application link in a curated list is not a guarantee
that the employer still has the role open.

## Shared history and delivery

`tracking.py` adds a versioned `_jobs` ledger to `state.json` on the first normal run. It imports both existing per-channel records and the older `notified.json`; existing channel arrays are retained unchanged. The historical files in this change are untouched. Invalid history fails closed instead of silently becoming an empty set.

Matching uses normalized company aliases, company-scoped requisition IDs (including known official URL formats), canonical URLs without tracking parameters, and conservative company/role/location/term signatures. Conflicting requisition IDs never merge. Team, location, duration and term differences remain significant. Missing terms and ambiguous multiple matches do not cause speculative merges. Exact IDs/URLs take precedence over metadata matches. Verified corporate URLs are preferred when equivalent sources occur in the same scan; prior Discord messages are never edited or deleted.

Discovered and delivered identities persist across scans. Every delivery is reserved as `pending` with an atomic, flushed state write before contacting Discord, then marked `sent` on success. Explicit HTTP rejection can retry on a later scan. Timeouts, ambiguous server failures, and crashes after reservation retain `pending` and are **not automatically retried**, preventing a possibly accepted message from being sent twice. This prioritizes avoiding duplicates over guaranteed delivery. Discord webhooks cannot provide a transactional exactly-once guarantee with a local JSON file.

Local processes use a file lock. GitHub Actions serializes runs, checks out the latest default branch, runs tests before notification, commits state even after a failed notifier step, and uploads a seven-day recovery copy. Scheduled and manual notification runs operate only on the default branch to avoid independent branch histories. Do not run another deployment with a separate copy of state against the same webhooks. A lost runner or an unrecoverable state push can still lose uncommitted history; restore the workflow's state artifact before rerunning in that situation.

If a delivery remains `pending`, inspect that record's channel and application URL in Discord. Leave it pending (or mark it sent) if a message may already exist. Only change it back to `discovered` after confirming no message was delivered. Do not clear the ledger to retry a source.

## Verification

The offline unittest suite covers the requested filter cases, technical disciplines, same-scan and later-source duplicates, distinct requisitions/teams/locations/terms, legacy migration, restarts, ambiguous delivery, retryable rejection, state-write failures, source isolation, adapter pagination, expired jobs, official URL extraction, HTML/schema changes, and SimplifyJobs regressions. Fixtures use synthetic descriptions plus small sanitized samples of verified official page structures; no test sends Discord messages.
