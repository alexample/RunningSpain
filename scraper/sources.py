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
    if not config.SPORTPLAN_ACTIVO:
        return []
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


SM_EVENT = re.compile(r"/es/races/[a-z0-9][a-z0-9-]+")
CP_EVENT = re.compile(r"/carrera/[a-z0-9][a-z0-9-]+")
LS_EVENT = re.compile(r"/carreras/[a-z0-9][a-z0-9-]+")
RU_EVENT = re.compile(r"https://runedia\.mundodeportivo\.com/carrera/([a-z0-9-]+)-(20\d{2})/(\d+)/?")


def _paged(name: str, tpl: str, pattern: re.Pattern, max_pages: int, log, keep=lambda u: True) -> list[dict]:
    found = {}
    for n in range(1, max_pages + 1):
        html, final, _ = net.get(tpl.format(n=n))
        if not html:
            break
        new = 0
        for url, txt in _links(html, final, pattern):
            url = url.split("#")[0].split("?")[0]
            if url not in found and keep(url):
                found[url] = {"source_url": url, "name_hint": txt[:120], "date": None}
                new += 1
        if not new:
            break
    log(f"  {name}: {len(found)} fichas")
    return list(found.values())


def list_sportmaniacs(today: date, log) -> list[dict]:
    return _paged("sportmaniacs", config.SPORTMANIACS_LIST, SM_EVENT, config.SPORTMANIACS_MAX_PAGES, log,
                  keep=lambda u: parse.is_road(u.rsplit("/", 1)[-1].replace("-", " ")))


def list_carreraspopulares(today: date, log) -> list[dict]:
    return _paged("carreraspopulares", config.CARRERASPOPULARES_LIST, CP_EVENT, config.CARRERASPOPULARES_MAX_PAGES, log,
                  keep=lambda u: parse.is_road(u.rsplit("/", 1)[-1].replace("-", " ")))


def list_lineadesalida(today: date, log) -> list[dict]:
    res = _paged("lineadesalida", config.LINEADESALIDA_LIST + "?_={n}", LS_EVENT, 1, log,
                 keep=lambda u: parse.is_road(u.rsplit("/", 1)[-1].replace("-", " ")))
    for c in res:   # empresa de cronometraje de Murcia: casi todas sus carreras son de allí
        c["region_default"] = "Región de Murcia"
    return res


def list_runedia(today: date, log) -> list[dict]:
    """Runedia: las fichas de carreras salen de su sitemap (no tienen fecha en la URL)."""
    idx, _, _ = net.get(config.RUNEDIA_SITEMAP)
    if not idx:
        log("  runedia: sin acceso")
        return []
    years = {str(today.year), str(today.year + 1)}
    found = {}
    for sm in re.findall(r"<loc>([^<]*sitemap-curses[^<]*)</loc>", idx):
        xml, _, _ = net.get(sm.strip())
        if not xml:
            continue
        for m in RU_EVENT.finditer(xml):
            slug, year, rid = m.groups()
            if year not in years or not rid.startswith(year):
                continue
            if not parse.is_road(slug.replace("-", " ")):
                continue
            url = m.group(0) if m.group(0).endswith("/") else m.group(0) + "/"
            found[url] = {"source_url": url, "name_hint": slug.replace("-", " "), "date": None, "rid": int(rid)}
    # las más recientes (id mayor) primero: son las que se acaban de publicar
    res = sorted(found.values(), key=lambda c: -c["rid"])
    log(f"  runedia: {len(res)} fichas de {', '.join(sorted(years))} en el sitemap")
    return res


def read_event_page(cand: dict, today: date) -> dict | None:
    """Abre la ficha del calendario y devuelve una carrera normalizada (o None)."""
    cand["motivo"], cand["fecha"] = "sin_acceso", None
    html, final, _ = net.get(cand["source_url"])
    if not html:
        return None
    events = parse.jsonld_events(html)
    f = parse.event_fields(events[0]) if events else {}
    text = parse.page_text(html)[:6000]
    h1 = parse.soup(html).find("h1")
    h1 = h1.get_text(" ", strip=True) if h1 else ""
    hint = cand.get("name_hint") or ""
    if re.match(r"^[A-Z][a-z]{2} \d", hint):   # running.life usa la fecha como texto del enlace
        hint = ""
    name = parse.nice_name(f.get("name") or h1 or hint)
    d = f.get("date") or cand.get("date") or parse.date_from_text(text[:3000])
    cand["fecha"] = d
    if not name:
        cand["motivo"] = "sin_nombre"
        return None
    if not d:
        cand["motivo"] = "sin_fecha"
        return None
    if not _in_window(d, today):
        cand["motivo"] = "fuera_de_ventana"
        return None
    if not parse.is_road(name):
        cand["motivo"] = "no_asfalto"
        return None
    if not parse.is_spain(f.get("country", "")):
        cand["motivo"] = "extranjera"
        return None
    cand["motivo"] = "ok"
    city = f.get("city") or ""
    if not city:
        m = re.search(r"\bLugar:?\s+(.{2,40}?)\s+(?:Fecha|Hora|Distancia)\b", text[:3000])
        city = m.group(1).strip() if m else ""
    name, place = parse.split_name_place(name)
    city = parse.nice_name(city or place)
    name = parse.clean_name(name)
    region = (parse.region_from_text(f.get("region_hint", ""), city)
              or cand.get("region_default")
              or parse.region_from_text(text[:1500]))
    official = (f.get("official_candidates") or [None])[0] or parse.guess_official(html, final)
    return {
        "name": name,
        "date": d,
        "time": parse.local_time(f.get("start", ""), region or "") or parse.extract_time(text[:3000]) or "",
        "city": city,
        "region": region or "",
        "distances": parse.distances_from(name),
        "price": f.get("price") or "",
        "source": cand["source_url"],
        "official_guess": official,
        **_media(html, final),
    }


def _media(html: str, final: str) -> dict:
    """Cartel y recorrido que aparezcan en la página."""
    out = {}
    img, score = parse.best_image(html, final)
    if img:
        out["banner"], out["bannerScore"] = img, score
    # en webs de calendarios solo valen enlaces claros (Strava, Wikiloc, GPX…): sus «ruta» son otras carreras
    route = parse.find_route(html, final, strict=not parse.is_official_url(final))
    if route:
        out["route"] = route
    return out


def read_media(url: str) -> dict:
    html, final, _ = net.get(url)
    return _media(html, final) if html else {}
