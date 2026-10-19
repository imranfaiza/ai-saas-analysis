"""Download XBRL financials and gross-margin filing text from SEC EDGAR.

Usage:
    python fetch_sec.py --email you@uw.edu [--tickers CRM,ADBE] [--refresh]

Outputs (under data/):
    companies.csv        one row per company: CIK, name, fiscal year end
    facts.csv            long table of XBRL facts for the tags in xbrl_tag_map.csv
    component_facts.csv  dimensional cost-of-revenue lines (cost_of_revenue_components.csv)
                         read from each filing's inline XBRL; the companyfacts API omits these
    tag_inventory.csv    every financial tag each company used (for tag-mapping review)
    filings.csv          the 10-K / 10-Q text documents we extracted from
    filing_text/*.txt    gross-margin and AI-cost paragraphs from each filing
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).parent
SEEDS = ROOT / "warehouse" / "seeds"
DATA = ROOT / "data"
RAW = DATA / "raw"
TEXT_DIR = DATA / "filing_text"

FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A"}
MIN_PERIOD_END = "2020-01-01"
TEXT_CHAR_CAP = 40_000

MARGIN_RE = re.compile(
    r"gross (margin|profit)|costs? of (revenue|revenues|sales|subscription|services|platform|professional)",
    re.I,
)
AI_RE = re.compile(
    r"\bAI\b|artificial intelligence|generative|\bGPUs?\b|machine learning|"
    r"large language|\bLLMs?\b|\binference\b|agentic|\bagents?\b",
    re.I,
)
COST_RE = re.compile(r"\bcosts?\b|margin|expenses?\b|hosting|compute|infrastructure", re.I)
SENTENCE_RE = re.compile(r"(?<=[.;])\s+")
ITEM_RE = re.compile(r"^[\s|]*item\s+\d+[a-z]?\b", re.I)
SKIP_SECTION_RE = re.compile(r"cybersecurity|legal proceedings|controls and procedures|exhibits|unregistered", re.I)


def mentions_ai_cost(para: str) -> bool:
    return any(AI_RE.search(s) and COST_RE.search(s) for s in SENTENCE_RE.split(para))


def section_weight(section: str) -> int:
    s = section.lower()
    if "management" in s:
        return 3
    if "risk factors" in s:
        return 1
    return 0


class SecClient:
    def __init__(self, email: str):
        self.headers = {
            "User-Agent": f"ai-saas-margins-analysis {email}",
            "Accept-Encoding": "gzip, deflate",
        }
        self._last = 0.0

    def get(self, url: str) -> bytes:
        for attempt in range(4):
            wait = 0.12 - (time.monotonic() - self._last)  # SEC limit: 10 requests/second
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(url, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 3:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise
        raise RuntimeError(f"unreachable: {url}")

    def get_json(self, url: str, cache: Path, refresh: bool) -> dict:
        if cache.exists() and not refresh:
            return json.loads(cache.read_text(encoding="utf-8"))
        data = json.loads(self.get(url))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
        return data


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- XBRL facts

def flatten_facts(ticker: str, cik: str, facts: dict, wanted: set[tuple[str, str]]) -> list[dict]:
    rows = []
    for taxonomy, tags in facts.get("facts", {}).items():
        for tag, body in tags.items():
            if (taxonomy, tag) not in wanted:
                continue
            for unit, points in body.get("units", {}).items():
                for p in points:
                    if p.get("form") not in FORMS or p.get("end", "") < MIN_PERIOD_END:
                        continue
                    rows.append({
                        "ticker": ticker,
                        "cik": cik,
                        "taxonomy": taxonomy,
                        "tag": tag,
                        "unit": unit,
                        "period_start": p.get("start", ""),
                        "period_end": p["end"],
                        "value": p["val"],
                        "fiscal_year": p.get("fy", ""),
                        "fiscal_period": p.get("fp", ""),
                        "form": p["form"],
                        "filed": p.get("filed", ""),
                        "accession": p.get("accn", ""),
                        "frame": p.get("frame", ""),
                    })
    return rows


def tag_inventory(ticker: str, facts: dict) -> list[dict]:
    rows = []
    for taxonomy in ("us-gaap", "ifrs-full"):
        for tag, body in facts.get("facts", {}).get(taxonomy, {}).items():
            points = [
                p for units in body.get("units", {}).values() for p in units
                if p.get("form") in FORMS and p.get("end", "") >= MIN_PERIOD_END
            ]
            if points:
                rows.append({
                    "ticker": ticker,
                    "taxonomy": taxonomy,
                    "tag": tag,
                    "label": body.get("label") or "",
                    "n_facts": len(points),
                    "latest_period_end": max(p["end"] for p in points),
                })
    return rows


# ---------------------------------------------------------------- filing text

class TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"}
    SKIP = {"script", "style", "ix:header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def paragraphs(self) -> list[str]:
        text = "".join(self.parts).replace("\xa0", " ")
        out = []
        for chunk in re.split(r"\n\s*\n|\n", text):
            chunk = re.sub(r"\s+", " ", chunk).strip()
            if chunk:
                out.append(chunk)
        return out


def extract_margin_text(html: str) -> tuple[str, int]:
    parser = TextExtractor()
    parser.feed(html)
    section = ""
    candidates = []
    for i, para in enumerate(parser.paragraphs()):
        if len(para) < 150 and ITEM_RE.match(para):
            section = para.strip(" |")[:100]
            continue
        if len(para) < 200 or " | " in para or SKIP_SECTION_RE.search(section):
            continue
        margin_hit = bool(MARGIN_RE.search(para))
        ai_hit = mentions_ai_cost(para)
        if not (margin_hit or ai_hit):
            continue
        score = 2 * margin_hit + ai_hit + section_weight(section)
        candidates.append((score, i, section, para))

    chosen, total = [], 0
    for score, i, section, para in sorted(candidates, key=lambda c: (-c[0], c[1])):
        if total + len(para) > TEXT_CHAR_CAP:
            continue
        chosen.append((i, section, para))
        total += len(para)
    chosen.sort()

    blocks, last_section = [], None
    for _, section, para in chosen:
        if section != last_section:
            blocks.append(f"\n## {section or 'Unlabeled section'}\n")
            last_section = section
        blocks.append(para)
    return "\n\n".join(blocks).strip(), len(chosen)


def decode_html(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def latest_filings(submissions: dict) -> list[dict]:
    recent = submissions["filings"]["recent"]
    found = {}
    for i, form in enumerate(recent["form"]):
        key = "annual" if form in ("10-K", "20-F") else "quarterly" if form == "10-Q" else None
        if key and key not in found:
            found[key] = {
                "form": form,
                "accession": recent["accessionNumber"][i],
                "primary_document": recent["primaryDocument"][i],
                "report_date": recent["reportDate"][i],
                "filed": recent["filingDate"][i],
            }
    return list(found.values())


# ---------------------------------------------------------------- inline XBRL components

CONTEXT_RE = re.compile(r'<(?:xbrli:)?context\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</(?:xbrli:)?context>', re.S)
MEMBER_RE = re.compile(r'<xbrldi:explicitMember[^>]*dimension="([^"]+)"[^>]*>\s*([^<\s]+)\s*<', re.S)
NONFRACTION_RE = re.compile(r"<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>", re.S)
ATTR_RE = re.compile(r'([\w:.-]+)="([^"]*)"')


def parse_contexts(html: str) -> dict[str, dict]:
    contexts = {}
    for cid, body in CONTEXT_RE.findall(html):
        start = re.search(r"<(?:xbrli:)?startDate>([^<]+)<", body)
        end = re.search(r"<(?:xbrli:)?endDate>([^<]+)<", body)
        if not (start and end) or "typedMember" in body:
            continue
        contexts[cid] = {
            "start": start.group(1).strip(),
            "end": end.group(1).strip(),
            "dims": frozenset(MEMBER_RE.findall(body)),
        }
    return contexts


def parse_ix_value(attrs: dict, inner: str) -> float:
    text = re.sub(r"<[^>]+>", "", inner).strip()
    if "fixed-zero" in attrs.get("format", "") or text in ("", "-", "—", "–"):
        return 0.0
    value = float(re.sub(r"[^\d.]", "", text)) * 10 ** int(attrs.get("scale", "0"))
    return -value if attrs.get("sign") == "-" else value


def extract_component_facts(html: str, wanted: list[dict]) -> list[dict]:
    targets = {}
    for w in wanted:
        dims = frozenset({(w["axis"], w["member"])}) if w["axis"] else frozenset()
        targets[(w["xbrl_tag"], dims)] = w
    contexts = parse_contexts(html)
    found = {}
    for raw_attrs, inner in NONFRACTION_RE.findall(html):
        attrs = dict(ATTR_RE.findall(raw_attrs))
        ctx = contexts.get(attrs.get("contextRef", ""))
        if not ctx:
            continue
        w = targets.get((attrs.get("name", ""), ctx["dims"]))
        if not w:
            continue
        key = (w["xbrl_tag"], w["axis"], w["member"], ctx["start"], ctx["end"])
        found[key] = parse_ix_value(attrs, inner)
    return [
        {"xbrl_tag": k[0], "axis": k[1], "member": k[2], "period_start": k[3], "period_end": k[4], "value": v}
        for k, v in found.items()
    ]


def fetch_component_facts(client, ticker, cik, subs, wanted, refresh, problems) -> tuple[list[dict], int]:
    recent = subs["filings"]["recent"]
    rows, n_filings = [], 0
    for i, form in enumerate(recent["form"]):
        if form not in ("10-K", "10-Q") or recent["reportDate"][i] < MIN_PERIOD_END:
            continue
        accession = recent["accessionNumber"][i]
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
               f"{accession.replace('-', '')}/{recent['primaryDocument'][i]}")
        cache = RAW / "filings_xbrl" / f"{ticker}_{accession}.htm"
        if cache.exists() and not refresh:
            raw_html = cache.read_bytes()
        else:
            try:
                raw_html = client.get(url)
            except urllib.error.HTTPError as e:
                problems.append(f"{ticker}: HTTP {e.code} fetching {form} {accession} for cost components")
                continue
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(raw_html)
        facts = extract_component_facts(decode_html(raw_html), wanted)
        if not facts:
            problems.append(f"{ticker}: no cost-of-revenue component facts in {form} {accession}")
        n_filings += 1
        for f in facts:
            rows.append({"ticker": ticker, "cik": cik, **f, "form": form,
                         "filed": recent["filingDate"][i], "accession": accession})
    return rows, n_filings


# ---------------------------------------------------------------- summary

def latest_quarter_revenue(rows: list[dict], priorities: dict) -> tuple[str, float | None, str]:
    best = None
    for r in rows:
        prio = priorities.get((r["taxonomy"], r["tag"]))
        if prio is None or not r["period_start"] or r["unit"] != "USD":
            continue
        days = (date.fromisoformat(r["period_end"]) - date.fromisoformat(r["period_start"])).days
        if not 80 <= days <= 100:
            continue
        key = (r["period_end"], -prio, r["filed"])
        if best is None or key > best[0]:
            best = (key, r)
    if not best:
        return "", None, ""
    r = best[1]
    return r["period_end"], float(r["value"]), r["tag"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True, help="contact email; the SEC requires it in the User-Agent")
    ap.add_argument("--tickers", help="comma-separated subset, e.g. CRM,ADBE")
    ap.add_argument("--refresh", action="store_true", help="re-download cached files")
    args = ap.parse_args()

    client = SecClient(args.email)
    companies = read_csv(SEEDS / "companies.csv")
    if args.tickers:
        keep = {t.strip().upper() for t in args.tickers.split(",")}
        companies = [c for c in companies if c["ticker"] in keep]

    tag_map = read_csv(SEEDS / "xbrl_tag_map.csv")
    wanted = {tuple(t["xbrl_tag"].split(":", 1)) for t in tag_map}
    revenue_priority = {
        tuple(t["xbrl_tag"].split(":", 1)): int(t["priority"])
        for t in tag_map if t["standard_name"] == "revenue" and t["company"] == "default"
    }
    components = read_csv(SEEDS / "cost_of_revenue_components.csv")

    tickers = client.get_json(
        "https://www.sec.gov/files/company_tickers.json", RAW / "company_tickers.json", args.refresh
    )
    cik_by_ticker = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in tickers.values()}

    company_rows, fact_rows, inventory_rows, filing_rows, summary, problems = [], [], [], [], [], []
    component_rows = []

    for c in companies:
        ticker = c["ticker"]
        cik = cik_by_ticker.get(ticker)
        if not cik:
            problems.append(f"{ticker}: ticker not found in SEC company list")
            continue
        print(f"[{ticker}] CIK {cik}", flush=True)
        try:
            subs = client.get_json(
                f"https://data.sec.gov/submissions/CIK{cik}.json", RAW / "submissions" / f"{ticker}.json", args.refresh
            )
            facts = client.get_json(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                RAW / "companyfacts" / f"{ticker}.json",
                args.refresh,
            )
        except urllib.error.HTTPError as e:
            problems.append(f"{ticker}: HTTP {e.code} fetching SEC JSON")
            continue

        company_rows.append({
            "ticker": ticker,
            "cik": cik,
            "sec_name": subs.get("name", ""),
            "fiscal_year_end": subs.get("fiscalYearEnd", ""),
            "sic": subs.get("sic", ""),
            "sic_description": subs.get("sicDescription", ""),
        })
        rows = flatten_facts(ticker, cik, facts, wanted)
        fact_rows.extend(rows)
        inventory_rows.extend(tag_inventory(ticker, facts))

        for f in latest_filings(subs):
            accn = f["accession"].replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{f['primary_document']}"
            stem = f"{ticker}_{f['form'].replace('/', '')}_{f['report_date']}"
            html_cache = RAW / "filings" / f"{stem}.htm"
            if html_cache.exists() and not args.refresh:
                raw_html = html_cache.read_bytes()
            else:
                try:
                    raw_html = client.get(url)
                except urllib.error.HTTPError as e:
                    problems.append(f"{ticker}: HTTP {e.code} fetching {f['form']} document")
                    continue
                html_cache.parent.mkdir(parents=True, exist_ok=True)
                html_cache.write_bytes(raw_html)
            text, n_paras = extract_margin_text(decode_html(raw_html))
            header = f"# {ticker} {f['form']} period ending {f['report_date']} (filed {f['filed']})\n# {url}\n"
            out = TEXT_DIR / f"{stem}.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(header + "\n" + text, encoding="utf-8")
            if len(text) < 500:
                problems.append(f"{ticker}: {f['form']} text extraction is very short ({len(text)} chars)")
            filing_rows.append({
                "ticker": ticker, **f, "url": url, "text_file": out.relative_to(ROOT).as_posix(),
                "n_paragraphs": n_paras, "n_chars": len(text),
            })

        wanted_components = [x for x in components if x["company"] == ticker]
        if wanted_components:
            got, n_filings = fetch_component_facts(client, ticker, cik, subs, wanted_components, args.refresh, problems)
            component_rows.extend(got)
            print(f"  cost-of-revenue components: {len(got)} facts from {n_filings} filings", flush=True)

        q_end, q_rev, q_tag = latest_quarter_revenue(rows, revenue_priority)
        if q_rev is None:
            problems.append(f"{ticker}: no quarterly revenue found in XBRL")
        summary.append((ticker, q_end, q_rev, q_tag, len(rows)))

    write_csv(DATA / "companies.csv", company_rows, list(company_rows[0]) if company_rows else ["ticker"])
    write_csv(DATA / "facts.csv", fact_rows, [
        "ticker", "cik", "taxonomy", "tag", "unit", "period_start", "period_end", "value",
        "fiscal_year", "fiscal_period", "form", "filed", "accession", "frame",
    ])
    write_csv(DATA / "component_facts.csv", component_rows, [
        "ticker", "cik", "xbrl_tag", "axis", "member", "period_start", "period_end", "value",
        "form", "filed", "accession",
    ])
    write_csv(DATA / "tag_inventory.csv", inventory_rows,
              ["ticker", "taxonomy", "tag", "label", "n_facts", "latest_period_end"])
    write_csv(DATA / "filings.csv", filing_rows, [
        "ticker", "form", "accession", "primary_document", "report_date", "filed",
        "url", "text_file", "n_paragraphs", "n_chars",
    ])

    print("\nLatest quarterly revenue (spot-check against investor relations):")
    print(f"{'ticker':<7}{'quarter end':<13}{'revenue ($M)':>14}  {'facts':>6}  tag")
    for ticker, q_end, q_rev, q_tag, n in summary:
        rev = f"{q_rev / 1e6:,.1f}" if q_rev is not None else "-"
        print(f"{ticker:<7}{q_end:<13}{rev:>14}  {n:>6}  {q_tag}")

    print(f"\n{len(company_rows)} companies, {len(fact_rows):,} facts, {len(filing_rows)} filing texts")
    if problems:
        print("\nProblems:")
        for p in problems:
            print(f"  - {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
