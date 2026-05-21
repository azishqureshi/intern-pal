import re
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from models import Posting
from utils import location_is_canada, normalize_url, strip_html_tags

RAW_README_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md"
SUBROW_MARKER = "\u21b3"


def fetch_readme_raw(url: str = RAW_README_URL, timeout: int = 15) -> str:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def find_section_markdown(md: str, section_heading_keywords: List[str]) -> Optional[str]:
    lines = md.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        for kw in section_heading_keywords:
            if kw.lower() in line.lower():
                start_idx = i
                break
        if start_idx is not None:
            break
    if start_idx is None:
        return None
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("#"):
            end_idx = j
            break
    else:
        end_idx = len(lines)
    return "\n".join(lines[start_idx:end_idx])


def extract_first_markdown_table(section_md: str) -> Optional[List[str]]:
    lines = section_md.splitlines()
    table_lines = []
    in_table = False
    for line in lines:
        if line.strip().startswith("|"):
            in_table = True
            table_lines.append(line.rstrip())
        elif in_table:
            break
    return table_lines or None


def parse_markdown_table(table_lines: List[str]) -> List[Dict[str, str]]:
    cleaned = [ln.strip().strip("|").strip() for ln in table_lines if ln.strip()]
    if len(cleaned) < 2:
        return []
    header_row = cleaned[0]
    if re.match(r"^\s*-+\s*(\|\s*-+\s*)*$", cleaned[1]):
        data_rows = cleaned[2:]
    else:
        data_rows = cleaned[1:]
    headers = [h.strip() for h in header_row.split("|")]
    out = []
    for row in data_rows:
        cells = [c.strip() for c in row.split("|")]
        while len(cells) < len(headers):
            cells.append("")
        out.append({headers[i]: cells[i] for i in range(len(headers))})
    return out


def parse_html_table(html_fragment: str) -> Optional[List[Dict[str, str]]]:
    soup = BeautifulSoup(html_fragment, "lxml")
    table = soup.find("table")
    if not table:
        return None
    ths = table.find_all("th")
    if ths:
        headers = [th.get_text(strip=True) for th in ths]
    else:
        first_tr = table.find("tr")
        if not first_tr:
            return None
        headers = [cell.get_text(strip=True) for cell in first_tr.find_all(["td", "th"])]
    rows = []
    all_trs = table.find_all("tr")
    start_idx = 1 if all_trs and all_trs[0].find_all("th") else 0
    for tr in all_trs[start_idx:]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        cell_raw = [str(cell) for cell in cells]
        cell_text = [cell.get_text(strip=True) for cell in cells]
        while len(cell_raw) < len(headers):
            cell_raw.append("")
            cell_text.append("")
        rows.append({headers[i]: cell_raw[i].strip() for i in range(len(headers))})
    return rows


def build_normalized_rows(raw_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized = []
    for r in raw_rows:
        row = {}
        for k, v in r.items():
            if isinstance(v, str) and ("<" in v and ">" in v and "href" in v):
                row[f"{k}_raw"] = v
                row[k] = strip_html_tags(v)
            else:
                row[k] = strip_html_tags(v)
                row[f"{k}_raw"] = v
        normalized.append(row)
    return normalized


def extract_link_from_cell(cell_text_or_html: str) -> Optional[str]:
    if not cell_text_or_html:
        return None

    try:
        bs = BeautifulSoup(cell_text_or_html, "lxml")
        anchors = bs.find_all("a", href=True)
        if anchors:
            for a in anchors:
                href = a.get("href", "").strip()
                if href and href.lower().startswith(("http://", "https://")) and "simplify.jobs/p/" not in href.lower():
                    return normalize_url(href)
            for a in anchors:
                href = a.get("href", "").strip()
                if href and href.lower().startswith(("http://", "https://")):
                    return normalize_url(href)
    except Exception:
        pass

    m = re.search(r"\[.*?\]\((https?://[^\s)]+)\)", cell_text_or_html)
    if m:
        return normalize_url(m.group(1))

    m = re.search(r"href=[\"\'](https?://[^\"\']+)[\"\']", cell_text_or_html)
    if m:
        return normalize_url(m.group(1))

    m = re.search(r"(https?://[^\s\)\]]+)", cell_text_or_html)
    if m:
        return normalize_url(m.group(1))

    return None


def fetch_postings() -> List[Posting]:
    md = fetch_readme_raw(RAW_README_URL)
    section = find_section_markdown(md, ["Software Engineering Internship Roles", "Software Engineering"])
    if not section:
        print("simplifyjobs: section not found")
        return []

    table_lines = extract_first_markdown_table(section)
    rows = []
    if table_lines:
        print(f"simplifyjobs: markdown table lines={len(table_lines)}")
        rows = parse_markdown_table(table_lines)
    else:
        html_rows = parse_html_table(section)
        if html_rows:
            print(f"simplifyjobs: html table rows={len(html_rows)}")
            rows = html_rows
        else:
            m = re.search(r"(<table[\s\S]*?</table>)", md, re.IGNORECASE)
            if m:
                parsed_any = parse_html_table(m.group(1))
                if parsed_any:
                    print(f"simplifyjobs: html table fallback rows={len(parsed_any)}")
                    rows = parsed_any

    if not rows:
        print("simplifyjobs: no rows parsed")
        return []

    normalized_rows = build_normalized_rows(rows)

    headers = list(normalized_rows[0].keys())
    human_headers = [h for h in headers if not h.endswith("_raw")]
    print(f"simplifyjobs: headers={human_headers}")

    application_header = next((h for h in human_headers if "apply" in h.lower() or "application" in h.lower()), None)
    location_header = next((h for h in human_headers if "location" in h.lower()), None)
    company_header = next((h for h in human_headers if "company" in h.lower()), human_headers[0] if human_headers else "Company")
    role_header = next((h for h in human_headers if "role" in h.lower() or "position" in h.lower()), human_headers[1] if len(human_headers) > 1 else "Role")
    age_header = next((h for h in human_headers if "age" in h.lower()), None)

    postings: List[Posting] = []
    last_valid_link = None
    previous_company = None
    total_rows = 0
    canada_rows = 0
    sample_non_canada = []
    sample_ages = []

    for item in normalized_rows:
        total_rows += 1
        location = item.get(location_header, "")
        age = item.get(age_header, "")

        if not location_is_canada(location):
            if len(sample_non_canada) < 3:
                sample_non_canada.append(strip_html_tags(location))
            continue
        canada_rows += 1
        if len(sample_ages) < 3:
            sample_ages.append(strip_html_tags(age))

        app_raw_key = (application_header + "_raw") if application_header else None
        app_raw_val = item.get(app_raw_key or "", "") if app_raw_key else ""
        current_link = extract_link_from_cell(app_raw_val) or extract_link_from_cell(item.get(application_header or "", ""))

        company_text_raw = item.get(company_header, "")
        company_text_stripped = strip_html_tags(company_text_raw).strip() if company_text_raw else ""

        if company_text_stripped and company_text_stripped != SUBROW_MARKER:
            previous_company = company_text_stripped

        if company_text_stripped and company_text_stripped != SUBROW_MARKER and current_link:
            last_valid_link = current_link

        link = current_link or last_valid_link

        company_display = previous_company if company_text_stripped == SUBROW_MARKER and previous_company else company_text_stripped
        role_display = strip_html_tags(item.get(role_header, ""))
        loc_display = strip_html_tags(location)

        postings.append(
            Posting(
                source="simplifyjobs",
                company=company_display or "Unknown",
                title=role_display or "Unknown",
                location=loc_display or "Unknown",
                age=age or None,
                url=link,
                job_id=None,
                posted_at=None,
            )
        )

    print(f"simplifyjobs: matched postings={len(postings)}")
    print(f"simplifyjobs: total rows={total_rows} canada rows={canada_rows}")
    if sample_non_canada:
        print(f"simplifyjobs: sample non-canada locations={sample_non_canada}")
    if sample_ages:
        print(f"simplifyjobs: sample ages={sample_ages}")
    return postings
