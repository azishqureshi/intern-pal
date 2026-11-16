# Source confirmation — November 16, 2026

Shopify's three live Summer 2027 internships were fetched successfully but
rejected by the classifier. Their header says `Remote - Americas`; their actual
internship requirements list Canadian offices. Even when the location was
corrected in memory, all three failed the narrow skills/responsibilities checks.

The repair extracts Canadian locations only from Shopify's mandatory intern
office section and recognizes the observed Ruby/Rails, ML, and data pipeline
responsibilities. Generic headquarters and compensation mentions remain
insufficient. Programme links support both shopify.com and www.shopify.com.
The shared classifier retains student, seniority, location, business-role,
closed-role, and graduate-only checks. Recorded descriptions exercise the full
parser, classifier, channel filter, source preference, and notification ledger.

Live confirmation: Shopify returned all three roles. Against a read-only copy
of production history, the SWE role remained sent and exactly two Shopify roles
were eligible (Applied ML Engineering and Data). No messages were sent during
these checks. Future scheduled scans can send the newly eligible roles.

Other sources were reviewed and all 12 configured watchers were exercised:

- Intern List repeatedly changed totals between 50-row pages, sometimes with
  overlapping IDs, causing complete scans to be discarded. Its API supports
  500-row requests; a single current-category snapshot returned 376 records,
  including 228 accepted roles. Pagination and strict consistency checks remain
  for larger categories. This reduces, but does not eliminate, moving-feed races.
- CIBC, RBC, BMO and TD were rate-limited in production run 43945205986.
  Local checks also encountered HTTP 429 responses; retries for CIBC/BMO/TD
  remained blocked. A 429 response inspected locally had no Retry-After header.
  External access is not repaired by changing eligibility rules. Fetch failures
  now fail the run *after* other sources are processed and their history saved.
  The workflow's always-run state persistence steps still apply.
- Google research placements remain subject to the existing responsibility
  evidence rules; no broad exception was introduced for vague research duties.
  PhD-only roles and foreign/nontechnical roles remain excluded.
- SimplifyJobs, Canadian Internship List, Amazon, Scotiabank and AMD completed
  their adapter calls. A successful zero-result response alone is not proof
  that a board has no relevant openings; this audit does not certify exhaustive
  coverage of every employer site.

Verification: 87 offline tests passed. Live Shopify and Intern List checks
passed. Tests confirm that the existing Shopify alert is not replayed, an
accepted official employer copy wins within the same scan, and failures in one
source do not erase successful deliveries from another.
