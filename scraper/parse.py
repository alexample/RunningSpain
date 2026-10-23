"""Utilidades para leer páginas: JSON-LD, enlaces, precios, horas y distancias."""
import json
import re
import unicodedata
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import config
from .net import domain


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", norm(s))).strip("-")[:80]


def race_id(name: str, d: str) -> str:
    return f"{slug(name)}-{d[:4]}-{d[5:7]}{d[8:10]}"


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


_NOT_ROAD_RE = re.compile(r"\b(" + "|".join(re.escape(norm(w).strip()) for w in config.NOT_ROAD) + r")", re.I)


# Palabras que solas descartan, pero no si además se nombra una carrera a pie
# («Cursa i Caminada», «Cursa del Club Natació»).
_SOFT = {"caminata", "caminada", "marxa", "passejada", "nataci", "swim", "senderis", "senderisme"}
_RUN_RE = re.compile(r"\b(cursa|carrera|carreira|lasterketa|run|running|corre|marato|maraton|mitja|media|\d+\s?k\b|\d+\s?km)", re.I)


def is_road(*texts: str) -> bool:
    """True si el nombre no indica trail, montaña, cross, obstáculos, etc."""
    t = norm(" ".join(t for t in texts if t))
    hits = {m.group(1).lower() for m in _NOT_ROAD_RE.finditer(t)}
    if not hits:
        return True
    return all(h in _SOFT for h in hits) and bool(_RUN_RE.search(t))


def region_from_text(*texts: str) -> str | None:
    t = norm(" ".join(t for t in texts if t))
    # primero las claves más largas (p. ej. "santa cruz de tenerife" antes que "tenerife")
    for key in sorted(config.PROVINCE_TO_REGION, key=len, reverse=True):
        if re.search(r"\b" + re.escape(norm(key)) + r"\b", t):
            return config.PROVINCE_TO_REGION[key]
    return None


# ---------------------------------------------------------------- JSON-LD
def jsonld_events(html: str) -> list[dict]:
    """Devuelve los objetos schema.org de tipo *Event que haya en la página."""
    out = []
    for tag in soup(html).find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            o = stack.pop()
            if isinstance(o, list):
                stack.extend(o)
                continue
            if not isinstance(o, dict):
                continue
            if "@graph" in o:
                stack.extend(o["@graph"] if isinstance(o["@graph"], list) else [o["@graph"]])
            if o.get("@type") == "ItemList":
                for it in o.get("itemListElement", []) or []:
                    stack.append(it.get("item", it) if isinstance(it, dict) else it)
            t = o.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(isinstance(x, str) and x.endswith("Event") for x in types):
                out.append(o)
    return out


def event_fields(ev: dict) -> dict:
    """Normaliza un Event de schema.org a nuestros campos."""
    loc = ev.get("location") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    addr = loc.get("address") if isinstance(loc, dict) else None
    city = region_hint = ""
    if isinstance(addr, dict):
        city = addr.get("addressLocality") or ""
        region_hint = " ".join(str(addr.get(k) or "") for k in ("addressRegion", "addressLocality", "postalCode"))
    elif isinstance(addr, str):
        city = addr.split(",")[0]
        region_hint = addr
    country = ""
    if isinstance(addr, dict):
        co = addr.get("addressCountry") or ""
        country = (co.get("name") or co.get("@id") or "") if isinstance(co, dict) else str(co)
    if not city and isinstance(loc, dict):
        city = loc.get("name") or ""
    offers = ev.get("offers") or []
    if isinstance(offers, dict):
        offers = [offers]
    prices = []
    for o in offers:
        if isinstance(o, dict):
            for k in ("price", "lowPrice", "highPrice"):
                try:
                    v = float(str(o.get(k)).replace(",", "."))
                    if 0 < v < 400:
                        prices.append(v)
                except (TypeError, ValueError):
                    pass
    start = str(ev.get("startDate") or "")
    image = ev.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    same = ev.get("sameAs") or []
    if isinstance(same, str):
        same = [same]
    org = ev.get("organizer") or {}
    if isinstance(org, list):
        org = org[0] if org else {}
    candidates = [ev.get("url")] + list(same) + [org.get("url") if isinstance(org, dict) else None]
    return {
        "name": (ev.get("name") or "").strip(),
        "date": start[:10] if re.match(r"\d{4}-\d{2}-\d{2}", start) else None,
        "time": start[11:16] if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", start) and start[11:16] != "00:00" else None,
        "city": city.strip(),
        "region_hint": region_hint,
        "country": country.strip(),
        "description": ev.get("description") or "",
        "price": format_price(prices) if prices else None,
        "image": image if isinstance(image, str) else None,
        "official_candidates": [c for c in candidates if isinstance(c, str) and is_official_url(c)],
    }


# ---------------------------------------------------------------- enlaces
def is_official_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    d = domain(url)
    return not any(d == x or d.endswith("." + x) for x in config.NOT_OFFICIAL)


def is_signup_platform(url: str) -> bool:
    d = domain(url)
    return any(d == x or d.endswith("." + x) for x in config.SIGNUP_PLATFORMS)


OFFICIAL_HINT = re.compile(r"web|oficial|official|site|inscri|registr|organiza|más info|mas info|info", re.I)


def external_links(html: str, base: str) -> list[tuple[str, str]]:
    s = soup(html)
    res = []
    for a in s.find_all("a", href=True):
        href = urljoin(base, a["href"].strip())
        if href.startswith("http") and is_official_url(href) and domain(href) != domain(base):
            res.append((href.split("#")[0], a.get_text(" ", strip=True)))
    return res


def guess_official(html: str, base: str) -> str | None:
    """Elige el enlace externo con más pinta de web oficial en una ficha de calendario."""
    links = external_links(html, base)
    if not links:
        return None
    scored = []
    for href, txt in links:
        score = 0
        if OFFICIAL_HINT.search(txt or ""):
            score += 3
        if is_signup_platform(href):
            score += 1
        if href.lower().endswith((".jpg", ".png", ".pdf")):
            score -= 3
        scored.append((score, href))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored[0][0] > 0 else None


REG_WORDS = re.compile(r"reglament|normativ|bases|araudi|regulation|rules|reglament", re.I)


def find_regulation(html: str, base: str) -> str | None:
    s = soup(html)
    best = None
    for a in s.find_all("a", href=True):
        href = urljoin(base, a["href"].strip())
        txt = a.get_text(" ", strip=True)
        if REG_WORDS.search(txt) or REG_WORDS.search(href):
            if href.lower().split("?")[0].endswith(".pdf"):
                return href
            best = best or href
    return best


def og_image(html: str, base: str) -> str | None:
    s = soup(html)
    for prop in ("og:image", "twitter:image", "og:image:url"):
        m = s.find("meta", attrs={"property": prop}) or s.find("meta", attrs={"name": prop})
        if m and m.get("content"):
            return urljoin(base, m["content"].strip())
    return None


def page_text(html: str) -> str:
    s = soup(html)
    for t in s(["script", "style", "noscript"]):
        t.decompose()
    return re.sub(r"\s+", " ", s.get_text(" ")).strip()


# ---------------------------------------------------------------- extracción
PRICE_RE = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?)\s?(?:€|euros?\b|eur\b)", re.I)
PRICE_CONTEXT = re.compile(r"inscripci|precio|cuota|tarifa|preu|import|dorsal", re.I)


def format_price(values: list[float]) -> str:
    vals = sorted({round(v, 2) for v in values})
    f = lambda v: (f"{v:.2f}".rstrip("0").rstrip(".")).replace(".", ",")
    return f"{f(vals[0])} €" if len(vals) == 1 else f"{f(vals[0])}–{f(vals[-1])} €"


def extract_price(text: str) -> str | None:
    vals = []
    for m in PRICE_RE.finditer(text or ""):
        ctx = text[max(0, m.start() - 160): m.end() + 40]
        if not PRICE_CONTEXT.search(ctx):
            continue
        try:
            v = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if 2 <= v <= 300:
            vals.append(v)
    return format_price(vals[:12]) if vals else None


TIME_RE = re.compile(r"(?:salida|sortida|hora de inicio|comienzo|inicio|start|\bhora)[^0-9]{0,40}?\b([01]?\d|2[0-3])[:.h]\s?([0-5]\d)\b", re.I)


def extract_time(text: str) -> str | None:
    m = TIME_RE.search(text or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


KM_RE = re.compile(r"\b(\d{1,2}(?:[.,]\d{1,3})?)\s?(?:km|kms|kilómetros|kilometros|k)\b", re.I)


def extract_km(text: str) -> str | None:
    seen = []
    for m in KM_RE.finditer(text or ""):
        try:
            v = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if 3 <= v <= 50 and v not in seen:
            seen.append(v)
    if not seen:
        return None
    seen = sorted(seen, reverse=True)[:4]
    return " · ".join((f"{v:g}".replace(".", ",")) + " km" for v in seen)


DATE_IN_SLUG = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")

_MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
          "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
          "gener": 1, "febrer": 2, "marc": 3, "abril ": 4, "maig": 5, "juny": 6, "juliol": 7, "agost": 8,
          "setembre": 9, "octubre ": 10, "novembre": 11, "desembre": 12}
_DATE_TXT = re.compile(r"\b(\d{1,2})\s+de\s+([a-z]+)\s+(?:de\s+|del\s+)?(20\d{2})\b")
_DATE_NUM = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b")


def date_from_text(text: str) -> str | None:
    """Primera fecha razonable en un texto: «21 de noviembre de 2026», «21/11/2026» o «21-11-2026»."""
    t = norm(text or "")
    found = []
    for m in _DATE_TXT.finditer(t):
        mes = _MESES.get(m.group(2)) or _MESES.get(m.group(2) + " ")
        if mes:
            found.append((m.start(), int(m.group(3)), mes, int(m.group(1))))
    for m in _DATE_NUM.finditer(t):
        found.append((m.start(), int(m.group(3)), int(m.group(2)), int(m.group(1))))
    for _, y, mth, d in sorted(found):
        try:
            return date(y, mth, d).isoformat()
        except ValueError:
            continue
    return None


def is_spain(country: str) -> bool:
    """True si el país está vacío (no se sabe) o es España."""
    c = norm(country or "").strip(" .")
    return not c or c in {"es", "esp", "spain", "espana", "espanya", "espagne", "spanien"}


def clean_name(name: str, city: str = "") -> str:
    """Quita la fecha y el lugar pegados al final del nombre («… Cabo de Palos 24/10/2026»)."""
    n = re.sub(r"\s+\d{1,2}/\d{1,2}/20\d{2}\s*$", "", name or "").strip()
    if city and len(n) > len(city) + 5 and norm(n).endswith(" " + norm(city)):
        n = n[: -len(city)].strip(" -·,")
    n = re.sub(r"\s+20\d{2}$", "", n).strip()
    return n


def nice_name(name: str) -> str:
    """Pasa a formato título los nombres escritos todo en mayúsculas."""
    if name and name.upper() == name and sum(c.isalpha() for c in name) > 4:
        small = {"de", "del", "la", "el", "los", "las", "y", "i", "a", "en", "por", "contra"}
        words = name.lower().split()
        def fix(i, w):
            if re.fullmatch(r"[ivxlc]+[ºª.]?", w):
                return w.upper()
            return w if (i and w in small) else w[:1].upper() + w[1:]
        return " ".join(fix(i, w) for i, w in enumerate(words))
    return name


def date_from_url(url: str) -> str | None:
    m = DATE_IN_SLUG.search(url or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def distances_from(text: str) -> list[str]:
    t = norm(text)
    out = []
    if re.search(r"\b(maraton|marato|42\s?k|42[.,]195)\b", t) and not re.search(r"media|medio|mitja|half|semi", t):
        out.append("42K")
    if re.search(r"media|medio|mitja|half|semi|21\s?k|21[.,]09", t):
        out.append("21K")
    for n in ("15", "10", "8", "5"):
        if re.search(rf"\b{n}\s?k(m|ms)?\b", t):
            out.append(f"{n}K")
    return out
