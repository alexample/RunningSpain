"""Recoge carreras de los calendarios públicos (solo para descubrirlas).

Los calendarios sirven para saber qué carreras hay y cuándo. Su enlace no se
muestra en la web: la ficha enlaza solo a la web oficial que encuentre enrich.py.
"""
import re
from datetime import date, timedelta
from urllib.parse import urljoin

from . import config, net, parse

SP_EVENT = re.compile(r"/es/events/[a-z0-9][a-z0-9-]+")
RL_EVENT = re.compile(r"/(?:en/event|es/carrera)/[a-z0-9][a-z0-9-]+(?:/\d{4}-\d{2}-\d{2})?")


def _in_window(d: str | None, today: date) -> bool:
    if not d:
        return True  # se decidirá al abrir la ficha
    try:
        x = date.fromisoformat(d)
    except ValueError:
        return False
    return today - timedelta(days=1) <= x <= today + timedelta(days=config.DAYS_AHEAD)


def _links(html: str, base: str, pattern: re.Pattern) -> list[tuple[str, str]]:
    res, seen = [], set()
    for a in parse.soup(html).find_all("a", href=True):
        href = a["href"].strip()
        m = pattern.search(href)
        if not m:
            continue
        url = urljoin(base, m.group(0))
        if url in seen:
            continue
        seen.add(url)
        res.append((url, a.get_text(" ", strip=True)))
    return res


def list_sportplan(today: date, log) -> list[dict]:
    found = {}
    pages = [config.SPORTPLAN_REGION_URL.format(slug=s) for s in config.SPORTPLAN_REGIONS]
    pages += config.SPORTPLAN_SERIES
    for page in pages:
        html, final, _ = net.get(page)
        if not html:
            log(f"  sin acceso: {page}")
            continue
        slug = page.rstrip("/").split("/")[-1]
        default_region = config.SLUG_REGION.get(slug)
        n = 0
        for url, txt in _links(html, final, SP_EVENT):
            d = parse.date_from_url(url)
            if not _in_window(d, today) or url in found:
                continue
            found[url] = {"source_url": url, "name_hint": txt, "date": d, "region_default": default_region}
            n += 1
        log(f"  {page}: {n} fichas")
    return list(found.values())


def list_runninglife(today: date, log) -> list[dict]:
    found = {}
    limit = (today + timedelta(days=config.DAYS_AHEAD)).isoformat()
    for base in config.RUNNINGLIFE_LISTS:
        for page in range(1, config.RUNNINGLIFE_MAX_PAGES + 1):
            url = base + (f"?page={page}" if page > 1 else "")
            html, final, _ = net.get(url)
            if not html:
                break
            events = parse.jsonld_events(html)
            links = _links(html, final, RL_EVENT)
            last_date = None
            for ev in events:
                f = parse.event_fields(ev)
                last_date = max(last_date or "", f["date"] or "")
            new = 0
            for link, txt in links:
                if link not in found:
                    found[link] = {"source_url": link, "name_hint": txt, "date": parse.date_from_url(link)}
                    new += 1
            if not new or (last_date and last_date > limit):
                break
        log(f"  {base}: {len(found)} fichas acumuladas")
    return list(found.values())


def read_event_page(cand: dict, today: date) -> dict | None:
    """Abre la ficha del calendario y devuelve una carrera normalizada (o None)."""
    html, final, _ = net.get(cand["source_url"])
    if not html:
        return None
    events = parse.jsonld_events(html)
    f = parse.event_fields(events[0]) if events else {}
    name = f.get("name") or cand.get("name_hint") or ""
    if not name:
        h1 = parse.soup(html).find("h1")
        name = h1.get_text(" ", strip=True) if h1 else ""
    d = f.get("date") or cand.get("date")
    if not name or not d or not _in_window(d, today):
        return None
    text = parse.page_text(html)[:6000]
    if not parse.is_road(name):
        return None
    city = f.get("city") or ""
    region = (parse.region_from_text(f.get("region_hint", ""), city)
              or parse.region_from_text(text[:1500])
              or cand.get("region_default"))
    official = (f.get("official_candidates") or [None])[0] or parse.guess_official(html, final)
    return {
        "name": re.sub(r"\s+20\d{2}$", "", name).strip(),
        "date": d,
        "time": f.get("time") or "",
        "city": city,
        "region": region or "",
        "distances": parse.distances_from(name + " " + text[:800]),
        "price": f.get("price") or "",
        "source": cand["source_url"],
        "official_guess": official,
    }
