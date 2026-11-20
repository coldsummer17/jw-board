"""Fetch jobs from every enabled source, score them, merge with previous results,
and write the (encrypted) data file the dashboard reads.

Usage:  python fetcher/run.py            (reads SITE_PASSWORD from the environment)
        python fetcher/run.py --only productionhub,remotive   (quick test of some sources)
        python fetcher/run.py --no-jobspy
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sources import SOURCES, SkipSource, run_jobspy, JOBSPY_LABELS  # noqa: E402
from util import (  # noqa: E402
    clean_text, decrypt_json, encrypt_json, fit_score, infer_employment, infer_region,
    infer_workplace, iso, job_id, now_utc, parse_date,
)

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ENC_FILE = DOCS / "data.enc"
PLAIN_FILE = DOCS / "data.json"
META_FILE = DOCS / "meta.json"


def load_config() -> Dict[str, Any]:
    with open(ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)


def load_previous(password: str | None) -> Dict[str, Any]:
    try:
        if password and ENC_FILE.exists():
            return decrypt_json(json.loads(ENC_FILE.read_text()), password)
        if not password and PLAIN_FILE.exists():
            return json.loads(PLAIN_FILE.read_text())
    except Exception as e:
        print(f"! Could not read previous data ({type(e).__name__}); starting fresh.")
    return {"jobs": []}


def normalize(raw: Dict[str, Any], default_source: str, cfg: Dict[str, Any], run_ts: str) -> Dict[str, Any] | None:
    title = clean_text(raw.get("title"), 200)
    url = (raw.get("url") or "").strip()
    if not title or not url.startswith("http"):
        return None
    desc = clean_text(raw.get("description"), 6000)
    location = clean_text(raw.get("location"), 160)
    workplace = infer_workplace(raw.get("workplace"), location, desc, raw.get("is_remote"))
    employment = infer_employment(raw.get("employment"), f"{title}. {desc}")
    region = infer_region(location, workplace, cfg["regions"])
    if not location and region == "Other / Unknown":
        # Boards like ProductionHUB give no location field; look for a place name in the title/description.
        region = infer_region(f"{title} {desc[:400]}", "", cfg["regions"])
    fit = fit_score(title, f"{raw.get('company', '')} {location} {desc}", cfg["scoring"])
    posted = raw.get("posted_at")
    if posted is not None and not hasattr(posted, "year"):
        posted = parse_date(posted)
    if posted and posted > now_utc() + timedelta(days=1):
        posted = None
    return {
        "id": job_id(url),
        "title": title,
        "company": clean_text(raw.get("company"), 120),
        "location": location,
        "region": region,
        "workplace_type": workplace,
        "employment_type": employment,
        "posted_at": iso(posted),
        "first_seen": run_ts,
        "last_seen": run_ts,
        "url": url,
        "source": raw.get("source") or default_source,
        "also_on": [],
        "fit": fit["score"],
        "matched": fit["matched"],
        "salary": clean_text(raw.get("salary"), 80),
        "snippet": clean_text(desc, 1500),
        "_fit": fit,
    }


def is_relevant(job: Dict[str, Any], min_fit: int) -> bool:
    f = job["_fit"]
    if not f["media"]:
        return False  # no film/video/journalism context at all
    if f["strong_role"] and job["fit"] >= min_fit:
        return True
    return f["generic_role"] and job["fit"] >= min_fit + 10


def rescore_stored(job: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    """Re-apply the current scoring rules to a job stored by an earlier run. Returns True to keep it."""
    fit = fit_score(job["title"], f"{job.get('company', '')} {job.get('location', '')} {job.get('snippet', '')}", cfg["scoring"])
    job["fit"], job["matched"], job["_fit"] = fit["score"], fit["matched"], fit
    job["region"] = infer_region(job.get("location", ""), job.get("workplace_type", ""), cfg["regions"])
    if not job.get("location") and job["region"] == "Other / Unknown":
        job["region"] = infer_region(f"{job['title']} {job.get('snippet', '')[:400]}", "", cfg["regions"])
    keep = is_relevant(job, cfg["min_fit_score"])
    job.pop("_fit", None)
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated source keys to run (testing)")
    ap.add_argument("--no-jobspy", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="don't write output files")
    args = ap.parse_args()

    cfg = load_config()
    password = os.environ.get("SITE_PASSWORD") or None
    if not password:
        print("! SITE_PASSWORD is not set: output will be written UNENCRYPTED to docs/data.json (fine for local testing).")
    run_start = now_utc()
    run_ts = iso(run_start)
    only = set(args.only.split(",")) if args.only else None

    collected: List[Dict[str, Any]] = []
    status: List[Dict[str, Any]] = []
    ctx: Dict[str, Any] = {}

    # ---- regular sources
    for key, scfg in cfg["sources"].items():
        if key.startswith("_") or key not in SOURCES:
            continue
        if only and key not in only:
            continue
        label = scfg.get("label", key)
        if not scfg.get("enabled", True):
            status.append({"source": label, "state": "off"})
            continue
        t0 = time.time()
        ctx["warnings"] = []
        try:
            raws = SOURCES[key](scfg, ctx)
            jobs = [j for j in (normalize(r, label, cfg, run_ts) for r in raws) if j]
            kept = [j for j in jobs if is_relevant(j, cfg["min_fit_score"])]
            collected.extend(kept)
            st = {"source": label, "state": "ok", "fetched": len(jobs), "kept": len(kept)}
            if ctx["warnings"]:
                st["note"] = "; ".join(ctx["warnings"])[:300]
            status.append(st)
        except SkipSource as e:
            status.append({"source": label, "state": "skipped", "note": str(e)})
        except Exception as e:
            traceback.print_exc()
            status.append({"source": label, "state": "error", "note": f"{type(e).__name__}: {str(e)[:200]}"})
        status[-1]["seconds"] = round(time.time() - t0, 1)
        print(f"  {label:<28} {status[-1]}")

    # ---- JobSpy (LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google Jobs)
    jcfg = cfg.get("jobspy", {})
    if jcfg.get("enabled") and not args.no_jobspy and (not only or "jobspy" in only):
        try:
            res = run_jobspy(jcfg, ctx)
            for site, r in res.items():
                label = JOBSPY_LABELS.get(site, site)
                jobs = [j for j in (normalize(x, label, cfg, run_ts) for x in r["jobs"]) if j]
                kept = [j for j in jobs if is_relevant(j, cfg["min_fit_score"])]
                collected.extend(kept)
                if r["calls"] and r["failed_calls"] == r["calls"]:
                    state = "error"
                elif r["calls"] and not r["jobs"]:
                    state = "error"  # JobSpy often swallows blocks and just returns nothing
                elif r["failed_calls"]:
                    state = "partial"
                else:
                    state = "ok"
                st = {"source": label, "state": state, "fetched": len(jobs), "kept": len(kept), "seconds": round(r["seconds"], 1)}
                if r["error"]:
                    st["note"] = f"{r['failed_calls']}/{r['calls']} searches failed. Last error: {r['error']}"
                elif r["calls"] and not r["jobs"]:
                    st["note"] = f"0 jobs from {r['calls']} searches. The site is probably blocking automated requests from this server; it may work on a later run."
                status.append(st)
                print(f"  {label:<28} {st}")
            for site, on in (jcfg.get("sites") or {}).items():
                if not on:
                    status.append({"source": JOBSPY_LABELS.get(site, site), "state": "off"})
        except ImportError:
            status.append({"source": "JobSpy", "state": "error", "note": "python-jobspy is not installed"})
        except Exception as e:
            traceback.print_exc()
            status.append({"source": "JobSpy", "state": "error", "note": f"{type(e).__name__}: {str(e)[:200]}"})
    elif not jcfg.get("enabled"):
        status.append({"source": "JobSpy (LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google)", "state": "off"})

    # ---- de-duplicate within this run (same URL, or same title+company across sources)
    by_id: Dict[str, Dict[str, Any]] = {}
    by_tc: Dict[str, str] = {}
    for j in sorted(collected, key=lambda x: -x["fit"]):
        tc = f"{j['title'].lower()}|{j['company'].lower()}" if j["company"] else None
        if j["id"] in by_id:
            continue
        if tc and tc in by_tc:
            keep = by_id[by_tc[tc]]
            if j["source"] != keep["source"] and j["source"] not in keep["also_on"]:
                keep["also_on"].append(j["source"])
            continue
        by_id[j["id"]] = j
        if tc:
            by_tc[tc] = j["id"]

    # ---- merge with previous results
    prev = load_previous(password)
    merged: Dict[str, Dict[str, Any]] = {}
    dropped_by_rules = 0
    for old in prev.get("jobs", []):
        if rescore_stored(old, cfg):
            merged[old["id"]] = old
        else:
            dropped_by_rules += 1
    prev_tc = {f"{o['title'].lower()}|{o['company'].lower()}": o["id"] for o in merged.values() if o.get("company")}
    new_count = 0
    for jid, j in by_id.items():
        j.pop("_fit", None)
        old_id = jid if jid in merged else prev_tc.get(f"{j['title'].lower()}|{j['company'].lower()}") if j["company"] else None
        if old_id and old_id in merged:
            old = merged[old_id]
            j["id"] = old_id
            j["first_seen"] = old.get("first_seen", run_ts)
            j["posted_at"] = j["posted_at"] or old.get("posted_at")
            j["also_on"] = sorted(set(old.get("also_on", [])) | set(j["also_on"]))
            merged[old_id] = j
        else:
            merged[jid] = j
            new_count += 1

    cutoff = run_start - timedelta(days=int(cfg.get("keep_days", 60)))
    final = []
    for j in merged.values():
        j.pop("_fit", None)
        ref = parse_date(j.get("posted_at")) or parse_date(j.get("first_seen"))
        if ref and ref < cutoff:
            continue
        final.append(j)
    final.sort(key=lambda x: (-x["fit"], x.get("posted_at") or x.get("first_seen") or ""))

    payload = {
        "updated_at": run_ts,
        "new_count": new_count,
        "total": len(final),
        "sources_status": status,
        "filters": cfg.get("filters", {}),
        "quick_links": cfg.get("quick_links", {}),
        "jobs": final,
    }
    meta = {"updated_at": run_ts, "new_count": new_count, "total": len(final), "encrypted": bool(password)}

    print(f"\nRun finished: {len(by_id)} relevant this run, {new_count} new, {dropped_by_rules} stored jobs dropped by current rules, {len(final)} total kept.")
    if args.dry_run:
        return 0
    DOCS.mkdir(exist_ok=True)
    if password:
        ENC_FILE.write_text(json.dumps(encrypt_json(payload, password)))
        if PLAIN_FILE.exists():
            PLAIN_FILE.unlink()
    else:
        PLAIN_FILE.write_text(json.dumps(payload, ensure_ascii=False))
    META_FILE.write_text(json.dumps(meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
