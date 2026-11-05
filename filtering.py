"""Conservative, explainable evidence checks for corporate career boards.

Search results are discovery hints, never enough to approve a corporate job.
SimplifyJobs keeps its own existing eligibility rules.
"""
import re
import unicodedata
from dataclasses import dataclass

from bs4 import BeautifulSoup

from models import Posting


def text(value: str) -> str:
    value = BeautifulSoup(value or "", "lxml").get_text(" ", strip=True)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", value).lower().strip()


STUDENT = r"\b(intern(?:ship)?s?|co[- /]?op|coop|student|stagiaire|stage)\b"
TECH_ROLE = (
    r"\b(?:software|application|backend|back.end|frontend|front.end|full.stack|"
    r"machine learning|ai|data|cloud|security|infrastructure|embedded|systems?) "
    r"(?:engineer(?:ing)?|develop(?:er|ment))\b|\b(?:devops|sdet|cybersecurity|"
    r"test automation|software qa|embedded software|firmware|systems programming|programmer|developpeur)\b"
)
BUSINESS_ROLE = (
    r"\b(?:business (?:systems? )?analyst|investment banking|accounting|accountant|"
    r"marketing|human resources|recruiter|retail banking|customer service|"
    r"administrative|sales|financial analyst|finance analyst|wealth management|"
    r"project coordinator|business operations|technical writer|ux/?ui designer|ux designer|ui designer|product designer|business develop(?:er|ment))\b"
)
SKILLS = r"\b(?:python|java|javascript|typescript|c\+\+|c#|golang|rust|sql|linux|git|"
SKILLS += r"kubernetes|docker|terraform|aws|azure|react|pytorch|tensorflow|"
SKILLS += r"programming|algorithms|data structures|apis?|ci/cd|penetration testing)(?=\W|$)"
# Action + technical object in the same clause. Mentions of technology, a CS
# degree, Excel, or working *with* developers are not responsibility evidence.
DUTIES = [
    r"\b(?:develop\w*|build\w*|implement\w*|design\w*|maintain\w*)\b[^.;\n]{0,90}\b(?:software|applications?|apis?|microservices|web services|backend|frontend|firmware|data pipelines?|etl pipelines?|machine learning models?|algorithms?)\b",
    r"\b(?:writ\w*|debug\w*|review\w*|test\w*)\b[^.;\n]{0,60}\b(?:code|software|unit tests?|automated tests?)\b",
    r"\b(?:automat\w*|develop\w*|build\w*|implement\w*)\b[^.;\n]{0,70}\b(?:test suites?|test automation|automated tests?|ci/cd|deployment pipelines?)\b",
    r"\b(?:deploy\w*|configur\w*|provision\w*|manag\w*)\b[^.;\n]{0,70}\b(?:cloud infrastructure|kubernetes|containers?|linux servers?|infrastructure as code)\b",
    r"\b(?:perform\w*|conduct\w*|investigat\w*|implement\w*)\b[^.;\n]{0,70}\b(?:penetration tests?|penetration testing|vulnerability assessments?|security incidents?|threat detection|security controls)\b",
]


def canadian_location(location: str, description: str = "") -> bool:
    loc = text(location)
    if re.search(r"\b(?:canada|can)\b", loc):
        return True
    if re.search(r"\b(?:united states|usa|california)\b", loc):
        return False
    if re.search(r"\bca[-, ]+(?:on|bc|qc|ab|mb|nb|nl|ns|nt|nu|pe|sk|yt)\b", loc):
        return True
    if re.search(r"[, (]\s*(?:on|bc|qc|ab|mb|nb|nl|ns|nt|nu|pe|sk|yt)(?:\b|[,)])", loc):
        return True
    if re.search(r"\b(?:ontario|quebec|british columbia|alberta|manitoba|new brunswick|"
                 r"newfoundland|nova scotia|saskatchewan|yukon|nunavut|prince edward island|northwest territories)\b", loc):
        return True
    # A company address in Canada in the footer does not establish eligibility.
    return bool("remote" in loc and re.search(
        r"(?:remote (?:work )?(?:anywhere )?(?:in|within|from) canada|"
        r"(?:applicants|candidates) (?:based|located|residing) in canada)", text(description)))


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str


def classify(posting: Posting) -> Decision:
    title, desc = text(posting.title), text(posting.description)
    kind, category = text(posting.employment_type), text(posting.category)
    if not posting.url or not posting.url.startswith("https://"):
        return Decision(False, "missing application URL")
    if re.search(r"\b(?:talent (?:pool|community)|expression of interest|job alerts?|internship notifications|future opportunities)\b", title) or re.search(r"(?:applications are (?:currently )?closed|not an (?:open|active) (?:job|position|vacancy))", desc):
        return Decision(False, "not an active opportunity")
    if not canadian_location(posting.location, posting.description):
        return Decision(False, "Canadian eligibility unverified")
    if re.search(r"\b(?:senior|sr\.?|staff|principal|director|manager|lead)\b", title):
        return Decision(False, "experienced role")
    if re.search(r"\b(?:permanent|regular)\b", kind) or "permanent" in title:
        return Decision(False, "permanent role")
    if re.search(r"\b(?:phd|ph d|doctoral|mba|master'?s)\b", title):
        return Decision(False, "graduate-only role")
    if re.search(r"(?:enrolled in|pursuing|must have)[^.;]{0,50}(?:phd|ph d|doctoral|master'?s)", desc) and not re.search(r"\b(?:bachelor|undergraduate|post.secondary)\b", desc):
        return Decision(False, "undergraduate eligibility unverified")
    placement_title = re.search(r"\b(?:intern(?:ship)?s?|co[- /]?op|coop|stagiaire)\b", title)
    student_title = re.search(r"\bstudent\b", title) and re.search(r"(?:enrolled|returning to (?:school|studies)|undergraduate)", desc)
    student = placement_title or student_title or re.search(STUDENT, kind) or re.search(
        r"(?:this (?:is an? |role is an? )?(?:internship|student|co.op)|"
        r"as (?:an? |a co.op/)?intern(?:ship)?(?: student)?\b|"
        r"(?:currently |must be )?enrolled in[^.;]{0,100}(?:returning|co.op)|"
        r"job type\s*:?\s*student|role type\s*:?\s*internship)", desc)
    if not student:
        return Decision(False, "student placement unverified")
    if not desc:
        return Decision(False, "missing description")
    technical_title = bool(re.search(TECH_ROLE, title))
    if re.search(BUSINESS_ROLE, title) and not technical_title:
        return Decision(False, "non-CS primary role")
    if re.search(r"\b(?:marketing|human resources|retail banking|investment banking)\b", category) and not technical_title:
        return Decision(False, "non-CS category")
    duties = sum(bool(re.search(pattern, desc)) for pattern in DUTIES)
    skills = bool(re.search(SKILLS, desc))
    # Innovation programmes sometimes name the deliverable a prototype rather
    # than software. Require a developer role AND concrete software skill areas.
    prototype_developer = (
        bool(re.search(r"\b(?:developer|developpeur)\b", title))
        and bool(re.search(r"(?:design|create|deliver)[^.;]{0,80}functional prototype", desc))
        and "programming languages" in desc
        and bool(re.search(r"\b(?:api development|web technologies|full.stack|mobile application development)\b", desc))
    )
    if skills and (duties >= (1 if technical_title else 2) or prototype_developer):
        return Decision(True, "student placement with technical responsibilities in Canada")
    return Decision(False, "insufficient CS responsibility evidence")


def extract_term(value: str) -> str:
    cleaned = text(value)
    pairs = re.findall(r"\b(winter|spring|summer|fall|autumn)\s*[,/-]?\s*(20\d{2})\b", cleaned)
    pairs += [(season, year) for year, season in re.findall(
        r"\b(20\d{2})\s*[,/-]?\s*(winter|spring|summer|fall|autumn)\b", cleaned)]
    return ";".join(sorted({f"{year}-{season.replace('autumn', 'fall')}" for season, year in pairs}))
