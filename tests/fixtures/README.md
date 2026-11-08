# Fixture provenance

Captured from public employer pages on November 5, 2026. These are small excerpts to exercise parser structure; they are not a current job feed.

- `rbc_amplify.json`: Workday detail fields for requisition R-0000191193, [Developer, RBC Amplify 2027, Toronto](https://rbc.wd3.myworkdayjobs.com/RBCEARLYTALENT1/job/TORONTO-Ontario-Canada/Developer--RBC-Amplify-2027--Toronto_R-0000191193-1). Description limited to prototype, skills, enrollment and student-job-type evidence. The separated job-type label/value is joined as plain text.
- `scotiabank.html`: title and location microdata plus a short description excerpt from [Trade Floor Technology Consultant Internship/Co-op](https://jobs.scotiabank.com/job/Toronto-GBM-Trade-Floor-Technology-Consultant-InternshipCo-op-Summer-2027-ON/605897917/), requisition 273053. Expiry is excluded so the parser test does not depend on today's date.
- `shopify.html`: header and description structure from [Staff Software Engineer — Internal Tools](https://www.shopify.com/careers/staff-software-engineer-internal-tools_12490bc5-00b1-4baf-9caa-8f01b4be4dbf). This is a negative eligibility fixture. The empty application section is simplified to its ID.

Other integration fixtures are deliberately synthetic and live in `test_integrations.py`, matching verified public schemas. This makes positive internship cases available even when a company's current openings contain no qualifying roles.

`internlist.json` contains the first ten Canadian SWE feed rows and the reported
Revvity/CIBC rows, captured from the public Jobright mini-sites API on November
7, 2026. Tests freeze time and cover source category noise and stale additions.
