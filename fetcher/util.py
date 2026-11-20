"""Shared helpers: HTTP, text cleanup, fit scoring, field inference, encryption."""
from __future__ import annotations

import base64
import gzip
import hashlib
import html
import json
import math
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_session: Optional[requests.Session] = None


def http() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    return _session


def get(url: str, **kw) -> requests.Response:
    kw.setdefault("timeout", 30)
    r = http().get(url, **kw)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------- text helpers

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(s: Any, limit: Optional[int] = None) -> str:
    if s is None:
        return ""
    s = html.unescape(_TAG_RE.sub(" ", str(s)))
    s = _WS_RE.sub(" ", s).strip()
    if limit and len(s) > limit:
        s = s[: limit - 1].rsplit(" ", 1)[0] + "…"
    return s


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value: Any) -> Optional[datetime]:
    """Accepts ISO strings, RFC-822 strings, unix timestamps, date objects."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if hasattr(value, "year") and hasattr(value, "month"):  # date
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:
            v /= 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc)
    s = str(value).strip()
    if s.isdigit():
        return parse_date(int(s))
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s[:len(fmt) + 6], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def job_id(url: str) -> str:
    u = url.strip().split("#")[0].rstrip("/").lower()
    u = re.sub(r"[?&](utm_[a-z]+|ref|src|source)=[^&]*", "", u)
    return hashlib.sha1(u.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- term matching

def _has_cjk(s: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in s)


_term_cache: Dict[str, re.Pattern] = {}


def term_in(term: str, text_lower: str) -> bool:
    """Word-boundary match for plain words; substring match for CJK or punctuated terms."""
    t = term.lower()
    if _has_cjk(t) or not re.match(r"^[\w].*[\w]$", t):
        return t in text_lower
    pat = _term_cache.get(t)
    if pat is None:
        pat = re.compile(r"(?<![\w])" + re.escape(t) + r"(?![\w])")
        _term_cache[t] = pat
    return bool(pat.search(text_lower))


# ---------------------------------------------------------------- scoring

def fit_score(title: str, body: str, scoring_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return {'score': 0-100, 'strong_role': bool, 'generic_role': bool, 'media': bool, 'matched': [...]}.

    strong_role:  a specific doc/film role word is in the title (e.g. videographer, fixer)
    generic_role: only a generic role word is in the title (e.g. producer, director)
    media:        the posting has media/film context somewhere
    """
    t = (title or "").lower()
    b = (body or "").lower()
    generic = {g.lower() for g in scoring_cfg.get("generic_roles", [])}
    raw = 0.0
    matched: List[str] = []
    strong_role = generic_role = strong_any = False
    for group in ("role_terms", "context_terms"):
        for term, weight in scoring_cfg.get(group, {}).items():
            if term.startswith("_"):
                continue
            in_t = term_in(term, t)
            if not (in_t or term_in(term, b)):
                continue
            raw += float(weight) * (2 if in_t else 1)
            matched.append(term)
            if group == "role_terms":
                is_generic = term.lower() in generic
                if not is_generic:
                    strong_any = True
                if in_t:
                    if is_generic:
                        generic_role = True
                    else:
                        strong_role = True
    for term, weight in scoring_cfg.get("negative_terms", {}).items():
        if not term.startswith("_") and term_in(term, t):
            raw += float(weight)
    media = term_in("video", t) or any(term_in(m, t) or term_in(m, b) for m in scoring_cfg.get("media_terms", []))
    raw = max(raw, 0.0)
    score = int(round(100 * (1 - math.exp(-raw / 80.0))))
    return {"score": score, "strong_role": strong_role, "generic_role": generic_role, "strong_any": strong_any,
            "media": media, "matched": matched[:12]}


# ---------------------------------------------------------------- field inference

REMOTE_WORDS = ("remote", "work from home", "wfh", "anywhere", "worldwide", "distributed", "远程")


def infer_workplace(given: Optional[str], location: str, text: str, is_remote: Optional[bool] = None) -> str:
    if given:
        g = given.lower()
        if "hybrid" in g:
            return "Hybrid"
        if "remote" in g:
            return "Remote"
        if "site" in g or "office" in g:
            return "On-site"
    loc = (location or "").lower()
    tl = (text or "").lower()
    if "hybrid" in loc or term_in("hybrid", tl[:3000]):
        return "Hybrid"
    if is_remote is True or any(w in loc for w in REMOTE_WORDS):
        return "Remote"
    if any(term_in(w, tl[:1500]) for w in ("fully remote", "100% remote", "remote position", "remote role", "work remotely")):
        return "Remote"
    if any(term_in(w, tl[:3000]) for w in ("on-site", "onsite", "in-person", "in person", "on location")):
        return "On-site"
    if loc and loc not in ("unknown", "n/a"):
        return "On-site"
    return "Not specified"


def infer_employment(given: Any, text: str) -> str:
    vals: List[str] = []
    if isinstance(given, (list, tuple)):
        vals = [str(v) for v in given if v]
    elif given:
        vals = [str(given)]
    joined = " ".join(vals).lower().replace("_", "-").replace(" ", "-")
    for key, out in (
        ("intern", "Internship"),
        ("contract", "Contract"), ("freelance", "Contract"), ("temporary", "Contract"), ("temp", "Contract"),
        ("per-diem", "Contract"), ("gig", "Contract"), ("project", "Contract"),
        ("part-time", "Part-time"), ("parttime", "Part-time"),
        ("full-time", "Full-time"), ("fulltime", "Full-time"), ("permanent", "Full-time"),
    ):
        if key in joined:
            return out
    tl = (text or "").lower()[:4000]
    if term_in("internship", tl) or term_in("intern", tl):
        return "Internship"
    if any(term_in(w, tl) for w in ("freelance", "freelancer", "contract", "per day", "day rate", "per diem", "1099", "project-based", "project basis")):
        return "Contract"
    if term_in("part-time", tl) or term_in("part time", tl):
        return "Part-time"
    if term_in("full-time", tl) or term_in("full time", tl):
        return "Full-time"
    return "Not specified"


def infer_region(location: str, workplace: str, regions_cfg: Dict[str, List[str]]) -> str:
    loc = (location or "").strip().lower()
    if workplace == "Remote" and (not loc or any(w in loc for w in ("anywhere", "worldwide", "global", "remote")) and not any(
        term_in(k, loc) for name, keys in regions_cfg.items() if not name.startswith("_") for k in keys
    )):
        return "Remote / Anywhere"
    padded = f" {loc} "
    for name, keys in regions_cfg.items():
        if name.startswith("_"):
            continue
        for k in keys:
            kl = k.lower()
            if (kl.strip() != kl or "," in kl) and kl in padded:
                return name
            if kl.strip() == kl and term_in(kl, loc):
                return name
    if workplace == "Remote":
        return "Remote / Anywhere"
    return "Other / Unknown"


# ---------------------------------------------------------------- encryption
# Format: {"v":1,"kdf":"PBKDF2-SHA256","iter":N,"salt":b64,"iv":b64,"ct":b64}
# Plaintext = gzip(JSON). Ciphertext = AES-256-GCM (ciphertext||tag), decryptable with WebCrypto.

PBKDF2_ITER = 250_000


def encrypt_json(obj: Any, password: str) -> Dict[str, Any]:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = os.urandom(16)
    iv = os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITER).derive(password.encode("utf-8"))
    plain = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, plain, None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": PBKDF2_ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def decrypt_json(blob: Dict[str, Any], password: str) -> Any:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = base64.b64decode(blob["salt"])
    iv = base64.b64decode(blob["iv"])
    ct = base64.b64decode(blob["ct"])
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=int(blob["iter"])).derive(password.encode("utf-8"))
    return json.loads(gzip.decompress(AESGCM(key).decrypt(iv, ct, None)).decode("utf-8"))


def chunks(seq: Iterable[Any], n: int):
    buf: List[Any] = []
    for x in seq:
        buf.append(x)
        if len(buf) == n:
            yield buf
            buf = []
    if buf:
        yield buf
