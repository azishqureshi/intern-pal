from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Posting:
    source: str
    company: str
    title: str
    location: str
    age: Optional[str]
    url: Optional[str]
    job_id: Optional[str]
    posted_at: Optional[str]
