# Intern Pal

A bot that tracks Canadian internships and co-ops and posts new listings to Discord.

Intern List alerts require a valid source posting timestamp within the last
48 hours (`INTERNLIST_MAX_AGE_HOURS`). After the initial silent scan, recent
jobs that were baselined but never sent can alert once. Delivered jobs and
pending deliveries remain suppressed even when the board refreshes their dates.
Old baseline jobs remain silent until they qualify for the freshness window.

| Source | Listings |
| --- | --- |
| [SimplifyJobs](https://github.com/SimplifyJobs/Summer2027-Internships) | Canadian roles in the software engineering internship list |
| [Canadian Internship List](https://github.com/Bobwillrule/Canadian-Internship-List) | Canadian tech internships and co-ops across all terms |
| [Intern List](https://www.intern-list.com/) | Canadian software engineering internships |
| [AMD](https://careers.amd.com/jobs?categories=Student%20%2F%20Intern%20%2F%20Temp&country=Canada) | Canadian student and internship roles |
| [CIBC](https://cibc.wd3.myworkdayjobs.com/campus) | Campus internships and co-ops |
| [RBC](https://rbc.wd3.myworkdayjobs.com/RBCEARLYTALENT1) | Early talent internships and co-ops |
| [BMO](https://bmo.wd3.myworkdayjobs.com/Campus) | Campus internships and co-ops |
| [TD](https://td.wd3.myworkdayjobs.com/TD_Bank_Careers) | Roles in the Campus category |
| [Scotiabank](https://jobs.scotiabank.com/go/Student-&-New-Grad-Jobs/2298417/) | Student internships and co-ops |
| [Shopify](https://www.shopify.com/careers/jobs) | Internship listings and program openings |
| [Google](https://www.google.com/about/careers/applications/jobs/results/?location=Canada&employment_type=INTERN) | Canadian internships |
| [Amazon / AWS](https://www.amazon.jobs/en/search.json?normalized_country_code%5B%5D=CAN) | Canadian technical internships |
