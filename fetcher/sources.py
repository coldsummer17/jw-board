"""One function per job source. Each returns a list of raw job dicts:

    {title, company, location, url, posted_at, description, workplace, employment, is_remote, source}

Only title and url are required. Add a new source by writing a function and
registering it in SOURCES at the bottom (the key must match config.json -> sources).
"""
from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List
from urllib.parse import urljoin

from util import clean_text, get, http, now_utc, parse_date

Job = Dict[str, Any]


def _rss_items(xml_text: str):
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    for item in root.iter("item"):
        d: Dict[str, str] = {}
        for child in item:
            tag = child.tag.split("}")[-1]
            d[tag] = (child.text or "").strip()
        yield d


def _txt(node, selector: str) -> str:
    el = node.select_one(selector)
    return clean_text(el.get_text(" ")) if el else ""


# ------------------------------------------------------------------ boards

def productionhub(cfg: Dict, ctx: Dict) -> List[Job]:
    r = get("https://www.productionhub.com/jobs/rss")
    out = []
    for it in _rss_items(r.text):
        out.append({
            "title": it.get("title"), "url": it.get("link") or it.get("guid"),
            "company": "", "location": "",
            "posted_at": parse_date(it.get("updated") or it.get("pubDate")),
            "description": f"{it.get('category', '')}. {it.get('description', '')}",
        })
    return out


def journalismjobs(cfg: Dict, ctx: Dict) -> List[Job]:
    from bs4 import BeautifulSoup

    out, seen = [], set()
    for kw in cfg.get("searches", JOURNALISMJOBS_KEYWORDS):
        r = get("https://www.journalismjobs.com/job-listings", params={"keywords": kw})
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.job-item"):
            href = a.get("href") or ""
            if not href or href in seen:
                continue
            seen.add(href)
            loc = emp = ""
            posted = None
            for li in a.select("ul.job-item-details li"):
                icon = li.find("i")
                cls = " ".join(icon.get("class", [])) if icon else ""
                txt = clean_text(li.get_text(" "))
                if "map-marker" in cls:
                    loc = txt
                elif "clock" in cls:
                    emp = txt
                elif "calendar" in cls:
                    posted = _month_day(txt.replace("Posted", "").strip())
            title_el = a.select_one(".job-item-title")
            out.append({
                "title": clean_text(title_el.get_text(" ") if title_el else ""),
                "company": _txt(a, ".job-item-company"),
                "location": loc, "employment": emp, "posted_at": posted,
                "url": urljoin("https://www.journalismjobs.com/", href),
                "description": _txt(a, ".job-item-description"),
            })
        time.sleep(1)
    return out


def _month_day(s: str):
    """'November 19' -> datetime in the most recent past occurrence."""
    now = now_utc()
    for fmt in ("%B %d", "%b %d"):
        try:
            d = datetime.strptime(s, fmt).replace(year=now.year, tzinfo=timezone.utc)
            if d > now + timedelta(days=2):
                d = d.replace(year=now.year - 1)
            return d
        except ValueError:
            continue
    return parse_date(s)


def remotive(cfg: Dict, ctx: Dict) -> List[Job]:
    out = []
    for kw in cfg.get("searches", ["video", "documentary", "producer", "mandarin"]):
        r = get("https://remotive.com/api/remote-jobs", params={"search": kw, "limit": 100})
        for j in r.json().get("jobs", []):
            out.append({
                "title": j.get("title"), "company": j.get("company_name"),
                "location": j.get("candidate_required_location") or "Remote",
                "url": j.get("url"), "posted_at": parse_date(j.get("publication_date")),
                "employment": j.get("job_type"), "workplace": "Remote", "is_remote": True,
                "description": j.get("description"),
            })
        time.sleep(2)
    return out


def remoteok(cfg: Dict, ctx: Dict) -> List[Job]:
    r = get("https://remoteok.com/api")
    out = []
    for j in r.json():
        if not isinstance(j, dict) or "position" not in j:
            continue
        out.append({
            "title": j.get("position"), "company": j.get("company"),
            "location": j.get("location") or "Remote", "url": j.get("url"),
            "posted_at": parse_date(j.get("date") or j.get("epoch")),
            "workplace": "Remote", "is_remote": True,
            "description": f"{' '.join(j.get('tags') or [])}. {j.get('description', '')}",
        })
    return out


def himalayas(cfg: Dict, ctx: Dict) -> List[Job]:
    out = []
    for kw in cfg.get("searches", ["video producer", "documentary", "videographer", "video editor", "mandarin"]):
        r = get("https://himalayas.app/jobs/api/search", params={"q": kw})
        for j in r.json().get("jobs", []):
            locs = j.get("locationRestrictions") or []
            loc = ", ".join(x if isinstance(x, str) else str(x.get("name", "")) for x in locs) or "Remote (anywhere)"
            slug = j.get("companySlug")
            url = j.get("applicationLink") or j.get("guid") or (f"https://himalayas.app/companies/{slug}/jobs" if slug else None)
            out.append({
                "title": j.get("title"), "company": j.get("companyName"), "location": loc,
                "url": url, "posted_at": parse_date(j.get("pubDate") or j.get("updatedAt")),
                "employment": j.get("employmentType"), "workplace": "Remote", "is_remote": True,
                "description": j.get("excerpt") or j.get("description"),
            })
        time.sleep(1)
    return out


def weworkremotely(cfg: Dict, ctx: Dict) -> List[Job]:
    r = get("https://weworkremotely.com/remote-jobs.rss")
    out = []
    for it in _rss_items(r.text):
        title = it.get("title", "")
        company, _, role = title.partition(":")
        out.append({
            "title": role.strip() or title, "company": company.strip() if role else "",
            "location": it.get("region") or it.get("country") or "Remote",
            "url": it.get("link"), "posted_at": parse_date(it.get("pubDate")),
            "employment": it.get("type"), "workplace": "Remote", "is_remote": True,
            "description": f"{it.get('category', '')}. {it.get('skills', '')}. {it.get('description', '')}",
        })
    return out


def arbeitnow(cfg: Dict, ctx: Dict) -> List[Job]:
    out = []
    for page in range(1, int(cfg.get("pages", 3)) + 1):
        r = get("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
        data = r.json().get("data", [])
        for j in data:
            out.append({
                "title": j.get("title"), "company": j.get("company_name"), "location": j.get("location"),
                "url": j.get("url"), "posted_at": parse_date(j.get("created_at")),
                "employment": j.get("job_types"), "is_remote": bool(j.get("remote")),
                "workplace": "Remote" if j.get("remote") else None,
                "description": f"{' '.join(j.get('tags') or [])}. {j.get('description', '')}",
            })
        if not data:
            break
        time.sleep(1)
    return out


SMARTSHANGHAI_CATEGORIES = ("tv-film-video", "media-pr-events", "arts-design-music")


def smartshanghai(cfg: Dict, ctx: Dict) -> List[Job]:
    from bs4 import BeautifulSoup

    cats = cfg.get("categories", SMARTSHANGHAI_CATEGORIES)
    r = get("https://www.smartshanghai.com/jobs/")
    soup = BeautifulSoup(r.text, "html.parser")
    out, seen = [], set()
    for a in soup.select("a.job-card-horizontal__link"):
        href = a.get("href") or ""
        m = re.search(r"/jobs/([a-z-]+)/(\d+)", href)
        if not m or href in seen or m.group(1) not in cats:
            continue
        seen.add(href)
        t = a.select_one(".job-card-horizontal__title")
        c = a.select_one(".job-card-horizontal__company-name")
        out.append({
            "title": clean_text(t.get_text(" ") if t else ""), "company": clean_text(c.get_text(" ") if c else ""),
            "location": "Shanghai, China", "url": href, "posted_at": None,
            "description": f"SmartShanghai category: {m.group(1).replace('-', ' ')}",
        })
    return out


# EntertainmentCareers: its robots.txt blocks search pages, so we read the public
# "new jobs" sitemap (500 latest postings), pre-select by words in each job's web
# address, then open only those job pages and read their structured JobPosting data.
EC_SLUG_WORDS = (
    "producer", "video", "editor", "documentar", "docu", "camera", "cinemat", "photograph", "director-of-photography",
    "shooter", "multimedia", "journalist", "post-production", "film", "fixer", "china", "chinese", "mandarin",
    "asia", "apac", "correspondent", "story", "content-creator", "production-coordinator", "production-manager",
)


def entertainmentcareers(cfg: Dict, ctx: Dict) -> List[Job]:
    days = int(cfg.get("days", 4))
    max_pages = int(cfg.get("max_job_pages", 60))
    words = tuple(cfg.get("slug_words", EC_SLUG_WORDS))
    r = get("https://www.entertainmentcareers.net/sitemaps/job_sitemap_newjobs.asp")
    root = ET.fromstring(r.content)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    cutoff = now_utc() - timedelta(days=days)
    candidates = []
    for u in root.iter(f"{ns}url"):
        loc = (u.findtext(f"{ns}loc") or "").strip()
        lastmod = parse_date(u.findtext(f"{ns}lastmod"))
        m = re.search(r"entertainmentcareers\.net/([^/]+)/([^/]+)/job/(\d+)", loc)
        if not m or (lastmod and lastmod < cutoff):
            continue
        slug = m.group(2).lower()
        if any(w in slug for w in words):
            candidates.append(loc)
    out = []
    for loc in candidates[:max_pages]:
        try:
            posting = _jsonld_jobposting(get(loc).text)
        except Exception:
            posting = None
        time.sleep(1)
        if not posting:
            continue
        out.append(_from_jsonld(posting, loc))
    if len(candidates) > max_pages:
        ctx.setdefault("warnings", []).append(f"{len(candidates)} possible matches, opened the newest {max_pages}")
    return out


def _jsonld_jobposting(html_text: str):
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html_text, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for d in (data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []):
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                return d
    return None


def _from_jsonld(d: Dict[str, Any], url: str) -> Job:
    locs = d.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    places = []
    for p in locs:
        a = (p or {}).get("address") or {}
        if isinstance(a, dict):
            places.append(", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry")) if x and isinstance(x, str)))
    remote = str(d.get("jobLocationType", "")).upper() == "TELECOMMUTE"
    org = d.get("hiringOrganization") or {}
    salary = ""
    bs = (d.get("baseSalary") or {}).get("value") if isinstance(d.get("baseSalary"), dict) else None
    if isinstance(bs, dict) and (bs.get("minValue") or bs.get("value")):
        lo, hi = bs.get("minValue") or bs.get("value"), bs.get("maxValue")
        salary = f"{d['baseSalary'].get('currency', '')} {lo}{'–' + str(hi) if hi else ''} / {str(bs.get('unitText', '')).lower()}".strip()
    return {
        "title": d.get("title"), "company": org.get("name", "") if isinstance(org, dict) else str(org),
        "location": "; ".join(p for p in places if p) or ("Remote" if remote else ""),
        "url": d.get("url") or url, "posted_at": parse_date(d.get("datePosted")),
        "employment": d.get("employmentType"), "is_remote": remote or None,
        "workplace": "Remote" if remote else None,
        "description": d.get("description", ""), "salary": salary,
    }


# ------------------------------------------------------------------ employer watchlist

def watchlist(cfg: Dict, ctx: Dict) -> List[Job]:
    out: List[Job] = []
    errors = []
    for emp in cfg.get("employers", []):
        name, ats, slug = emp.get("name"), emp.get("ats", "greenhouse"), emp.get("slug")
        try:
            if ats == "greenhouse":
                data = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"}).json()
                for j in data.get("jobs", []):
                    out.append({
                        "title": j.get("title"), "company": name, "location": (j.get("location") or {}).get("name", ""),
                        "url": j.get("absolute_url"), "posted_at": parse_date(j.get("first_published") or j.get("updated_at")),
                        "description": clean_text(j.get("content"), 3000), "source": f"Career page · {name}",
                    })
            elif ats == "lever":
                data = get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}).json()
                for j in data:
                    cats = j.get("categories") or {}
                    out.append({
                        "title": j.get("text"), "company": name, "location": cats.get("location", ""),
                        "url": j.get("hostedUrl"), "posted_at": parse_date(j.get("createdAt")),
                        "employment": cats.get("commitment"), "workplace": j.get("workplaceType"),
                        "description": j.get("descriptionPlain", ""), "source": f"Career page · {name}",
                    })
            elif ats == "ashby":
                data = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").json()
                for j in data.get("jobs", []):
                    out.append({
                        "title": j.get("title"), "company": name, "location": j.get("location", ""),
                        "url": j.get("jobUrl"), "posted_at": parse_date(j.get("publishedAt")),
                        "employment": j.get("employmentType"), "workplace": j.get("workplaceType"),
                        "is_remote": j.get("isRemote"), "description": j.get("descriptionPlain", ""),
                        "source": f"Career page · {name}",
                    })
            else:
                errors.append(f"{name}: unknown ats '{ats}'")
        except Exception as e:  # one employer failing shouldn't stop the others
            errors.append(f"{name}: {type(e).__name__}")
    if errors:
        ctx.setdefault("warnings", []).extend(errors)
    return out


# ------------------------------------------------------------------ optional key-based APIs

def adzuna(cfg: Dict, ctx: Dict) -> List[Job]:
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise SkipSource("no ADZUNA_APP_ID / ADZUNA_APP_KEY secret")
    out = []
    for country in cfg.get("countries", ["us", "gb"]):
        for kw in cfg.get("searches", ["documentary", "video producer", "fixer", "mandarin video"]):
            r = get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params={
                "app_id": app_id, "app_key": app_key, "what": kw, "results_per_page": 50,
                "max_days_old": 7, "content-type": "application/json",
            })
            for j in r.json().get("results", []):
                out.append({
                    "title": j.get("title"), "company": (j.get("company") or {}).get("display_name", ""),
                    "location": (j.get("location") or {}).get("display_name", ""), "url": j.get("redirect_url"),
                    "posted_at": parse_date(j.get("created")),
                    "employment": [j.get("contract_time"), j.get("contract_type")], "description": j.get("description"),
                })
            time.sleep(1)
    return out


def jooble(cfg: Dict, ctx: Dict) -> List[Job]:
    key = os.environ.get("JOOBLE_KEY")
    if not key:
        raise SkipSource("no JOOBLE_KEY secret")
    out = []
    for kw in cfg.get("searches", ["documentary producer", "video producer mandarin", "fixer china", "videographer chinese"]):
        r = http().post(f"https://jooble.org/api/{key}", json={"keywords": kw, "location": "", "page": "1"}, timeout=30)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            out.append({
                "title": j.get("title"), "company": j.get("company"), "location": j.get("location"),
                "url": j.get("link"), "posted_at": parse_date(j.get("updated")),
                "employment": j.get("type"), "description": j.get("snippet"),
            })
        time.sleep(1)
    return out


# ------------------------------------------------------------------ JobSpy (LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google)

JOBSPY_LABELS = {
    "linkedin": "LinkedIn", "indeed": "Indeed", "glassdoor": "Glassdoor",
    "zip_recruiter": "ZipRecruiter", "google": "Google Jobs",
}


def run_jobspy(jcfg: Dict, ctx: Dict) -> Dict[str, Dict[str, Any]]:
    """Returns {site: {"jobs": [...], "error": str|None, "seconds": float, "calls": int, "failed_calls": int}}."""
    from jobspy import scrape_jobs  # imported lazily so the rest works without it

    enabled_sites = [s for s, on in (jcfg.get("sites") or {}).items() if on]
    results: Dict[str, Dict[str, Any]] = {s: {"jobs": [], "error": None, "seconds": 0.0, "calls": 0, "failed_calls": 0} for s in enabled_sites}
    budget = float(jcfg.get("time_budget_minutes", 25)) * 60
    started = time.time()
    terms = jcfg.get("search_terms", [])

    for search in jcfg.get("searches", []):
        for site in search.get("sites", []):
            if site not in results:
                continue
            for term in terms:
                if time.time() - started > budget:
                    results[site]["error"] = results[site]["error"] or "stopped: time budget reached"
                    continue
                kw: Dict[str, Any] = {
                    "site_name": [site], "search_term": term,
                    "results_wanted": int(jcfg.get("results_per_search", 25)),
                    "hours_old": int(jcfg.get("hours_old", 72)),
                    "description_format": "markdown", "verbose": 0,
                }
                if search.get("location"):
                    kw["location"] = search["location"]
                if search.get("country"):
                    kw["country_indeed"] = search["country"]
                if site == "google":
                    kw["google_search_term"] = f"{term} {search.get('google_suffix', '')}".strip()
                t0 = time.time()
                results[site]["calls"] += 1
                try:
                    df = scrape_jobs(**kw)
                    for row in df.to_dict("records"):
                        results[site]["jobs"].append(_jobspy_row(row, site))
                except Exception as e:
                    results[site]["failed_calls"] += 1
                    results[site]["error"] = f"{type(e).__name__}: {str(e)[:160]}"
                results[site]["seconds"] += time.time() - t0
                time.sleep(1.5)
    return results


def _nan(v):
    try:
        if v != v:  # NaN
            return None
    except Exception:
        pass
    return v


def _jobspy_row(row: Dict[str, Any], site: str) -> Job:
    g = lambda k: _nan(row.get(k))
    loc = g("location") or ""
    if isinstance(loc, dict):
        loc = ", ".join(str(v) for v in loc.values() if v)
    salary = ""
    if g("min_amount") or g("max_amount"):
        lo, hi = g("min_amount"), g("max_amount")
        rng = f"{int(lo):,}–{int(hi):,}" if lo and hi else f"{int(lo or hi):,}"
        salary = f"{g('currency') or ''} {rng} / {g('interval') or ''}".strip()
    return {
        "title": g("title"), "company": g("company") or "", "location": str(loc),
        "url": g("job_url") or g("job_url_direct"),
        "posted_at": parse_date(g("date_posted")),
        "employment": g("job_type"), "is_remote": bool(g("is_remote")) if g("is_remote") is not None else None,
        "description": g("description") or "", "salary": salary,
        "source": JOBSPY_LABELS.get(site, site),
    }


# ------------------------------------------------------------------ registry

class SkipSource(Exception):
    """Raised when a source is intentionally skipped (e.g. no API key)."""


SOURCES: Dict[str, Callable[[Dict, Dict], List[Job]]] = {
    "productionhub": productionhub,
    "journalismjobs": journalismjobs,
    "remotive": remotive,
    "remoteok": remoteok,
    "himalayas": himalayas,
    "weworkremotely": weworkremotely,
    "arbeitnow": arbeitnow,
    "smartshanghai": smartshanghai,
    "entertainmentcareers": entertainmentcareers,
    "watchlist": watchlist,
    "adzuna": adzuna,
    "jooble": jooble,
}

# Search keywords for JournalismJobs are a subset — the board has few listings per query.
JOURNALISMJOBS_KEYWORDS = ["video", "documentary", "producer", "videographer", "China", "Mandarin", "multimedia"]

