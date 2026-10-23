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


def page_base(html: str, url: str) -> str:
    """Dirección base para los enlaces relativos: respeta <base href> si la página lo declara."""
    m = re.search(r"<base\s[^>]*href=[\"']([^\"']+)[\"']", html[:20000] or "", re.I)
    return urljoin(url, m.group(1).strip()) if m else url


def abs_url(base: str, href: str) -> str:
    """Enlace absoluto y bien codificado (espacios y tildes incluidos)."""
    from requests.utils import requote_uri
    return requote_uri(urljoin(base, (href or "").strip()))


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
    base = page_base(html, base)
    s = soup(html)
    res = []
    for a in s.find_all("a", href=True):
        href = abs_url(base, a["href"])
        if href.startswith("http") and is_official_url(href) and domain(href) != domain(base):
            res.append((href.split("#")[0], a.get_text(" ", strip=True)))
    return res


def guess_official(html: str, base: str) -> str | None:
    """Elige el enlace externo con más pinta de web oficial en una ficha de calendario."""
    base = page_base(html, base)
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


REG_WORDS = re.compile(r"reglament|normativ|\bbases\b|araudi|regulation|\brules\b|regolamento", re.I)
_REG_BAD = re.compile(r"protecci[oó]n de datos|rgpd|gdpr|privacidad|privacy|cookies|aviso legal|legal-notice|"
                      r"condiciones de (uso|compra)|terminos|términos|facebook|instagram|twitter|whatsapp", re.I)
_DOC = re.compile(r"\.pdf(\?|#|$)|drive\.google\.com/(file|open|uc)|docs\.google\.com/(document|viewer)|"
                  r"dropbox\.com/.+\.pdf|onedrive|1drv\.ms|\.docx?(\?|$)", re.I)


def is_document(url: str) -> bool:
    """¿El enlace va directamente al documento (PDF, Drive, Word…) y no a una página?"""
    return bool(_DOC.search(url or ""))


def find_regulation(html: str, base: str, only_docs: bool = False) -> str | None:
    """Enlace al reglamento. Prefiere el documento directo (PDF/Drive) frente a una página «Reglamento»."""
    base = page_base(html, base)
    best, best_score = None, 0
    for a in soup(html).find_all("a", href=True):
        href = abs_url(base, a["href"])
        if not href.startswith("http"):
            continue
        txt = a.get_text(" ", strip=True)[:120] + " " + str(a.get("title") or "")
        if _REG_BAD.search(txt) or _REG_BAD.search(href):
            continue
        named = REG_WORDS.search(txt) or REG_WORDS.search(href)
        doc = is_document(href)
        if named and doc:
            score = 10
        elif doc and re.search(r"descarg|download|pdf", txt, re.I) and not only_docs:
            score = 5          # «Descargar PDF» sin decir qué es: puede ser el reglamento
        elif named and not only_docs:
            score = 3          # página «Reglamento»: se intentará llegar al PDF desde ella
        else:
            continue
        if re.search(r"20(26|27)", href + txt):
            score += 1         # la edición actual mejor que una antigua
        if score > best_score:
            best, best_score = href, score
    return best


def og_image(html: str, base: str) -> str | None:
    s = soup(html)
    for prop in ("og:image", "twitter:image", "og:image:url"):
        m = s.find("meta", attrs={"property": prop}) or s.find("meta", attrs={"name": prop})
        if m and m.get("content"):
            return urljoin(base, m["content"].strip())
    return None


_IMG_BAD = re.compile(r"logo|icon|favicon|sprite|avatar|default|placeholder|blank|pixel|loading|spinner|"
                      r"share|social|og-image|og_image|banner-web|header-bg|bandera|flag|sponsor|patrocin|"
                      r"\.svg|\.gif|\.ico|gravatar|emoji|badge|app-store|google-play|qr", re.I)
_IMG_POSTER = re.compile(r"cartel|cartell|poster|afiche|flyer|affiche|kartel", re.I)


def best_image(html: str, base: str) -> tuple[str | None, int]:
    """El mejor cartel de una página y su puntuación (0 = ninguno).
    Prefiere imágenes llamadas «cartel/poster»; luego la imagen del evento (JSON-LD); luego og:image."""
    base = page_base(html, base)
    s = soup(html)
    cands: dict[str, int] = {}

    def add(url, score):
        if not url or not isinstance(url, str):
            return
        url = abs_url(base, url)
        if not url.startswith("http") or _IMG_BAD.search(url):
            return
        if _IMG_POSTER.search(url):
            score += 4
        cands[url] = max(cands.get(url, 0), score)

    for ev in jsonld_events(html):
        img = ev.get("image")
        for i in (img if isinstance(img, list) else [img]):
            add(i.get("url") if isinstance(i, dict) else i, 4)
    for prop in ("og:image", "twitter:image", "og:image:url"):
        m = s.find("meta", attrs={"property": prop}) or s.find("meta", attrs={"name": prop})
        if m and m.get("content"):
            add(m["content"], 2)
    for img in s.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
        label = " ".join(str(img.get(k) or "") for k in ("alt", "title", "class", "id"))
        if _IMG_POSTER.search(label):
            add(src, 5)
    for a in s.find_all("a", href=True):   # enlaces directos al cartel («Ver cartel»)
        if re.search(r"\.(jpe?g|png|webp)(\?|$)", a["href"], re.I) and _IMG_POSTER.search(a.get_text(" ") + " " + a["href"]):
            add(a["href"], 6)
    if not cands:
        return None, 0
    url = max(cands, key=cands.get)
    return url, cands[url]


_ROUTE_HOSTS = re.compile(r"(strava\.com/(routes|segments)|wikiloc\.com|connect\.garmin\.com/modern/course|"
                          r"komoot\.(com|de)/tour|ridewithgps\.com/routes|plotaroute\.com|mapmyrun\.com/routes|"
                          r"onthegomap\.com|google\.[a-z.]+/maps/d/|mapometer\.com|alltrails\.com|relive\.cc|"
                          r"footpathapp\.com|runkeeper\.com/user/.+/route|openrunner\.com)", re.I)
_ROUTE_WORD = re.compile(r"\b(recorrido|recorridos|circuito|recorregut|ibilbidea?|perfil del recorrido|track gps|mapa del recorrido)\b", re.I)
_ROUTE_URL_WORD = re.compile(r"recorrido|circuito|recorregut|ibilbide|perfil", re.I)
_ROUTE_BAD = re.compile(r"facebook|instagram|twitter|youtube|tiktok|whatsapp|mapa-web|sitemap|mapa-del-sitio|"
                        r"/noticia|/news|/blog/|/running/20\d\d|/event/|/events/|/carrera/|/races/|/calendario|"
                        r"inscripci|inscription|/services/|circuito-de-carreras|circuito-provincial|circuit-de-curses", re.I)


def is_route_url(url: str) -> bool:
    """¿Parece de verdad un recorrido? (servicio de rutas, archivo GPX/KML o página/archivo «recorrido» del organizador)"""
    if not url or not url.startswith("http"):
        return False
    if re.search(r"\.(gpx|kml|kmz)(\?|$)", url, re.I) or _ROUTE_HOSTS.search(url) or "wikiloc.com/wikiloc/view.do" in url:
        return True
    if re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I) and re.search(r"recorrido|circuito|recorregut|ibilbide|plano|perfil|mapa|route|course", url, re.I):
        return is_official_url(url)
    return bool(_ROUTE_URL_WORD.search(url)) and not _ROUTE_BAD.search(url) and is_official_url(url)


def _embed_to_view(src: str) -> str | None:
    """Convierte un mapa incrustado en un enlace que se pueda abrir."""
    m = re.search(r"wikiloc\.com/wikiloc/(?:spatialArtifacts|embedv2)\.do\?.*?\bid=(\d+)", src, re.I)
    if m:
        return f"https://es.wikiloc.com/wikiloc/view.do?id={m.group(1)}"
    m = re.search(r"google\.[a-z.]+/maps/d/(?:u/\d+/)?(?:embed|viewer|edit)\?.*?\bmid=([\w-]+)", src, re.I)
    if m:
        return f"https://www.google.com/maps/d/viewer?mid={m.group(1)}"
    m = re.search(r"strava\.com/(routes|activities|segments)/(\d+)", src, re.I)
    if m:
        return f"https://www.strava.com/{m.group(1)}/{m.group(2)}"
    m = re.search(r"connect\.garmin\.com/modern/course/(?:embed/)?(\d+)", src, re.I)
    if m:
        return f"https://connect.garmin.com/modern/course/{m.group(1)}"
    m = re.search(r"komoot\.[a-z]+/(?:[a-z-]+/)?tour/(\d+)", src, re.I)
    if m:
        return f"https://www.komoot.com/tour/{m.group(1)}"
    m = re.search(r"ridewithgps\.com/(?:embeds\?type=route&id=|routes/)(\d+)", src, re.I)
    if m:
        return f"https://ridewithgps.com/routes/{m.group(1)}"
    m = re.search(r"(plotaroute\.com/(?:route|embedmap)/\d+|mapmyrun\.com/routes/view/\d+|onthegomap\.com/s/\w+)", src, re.I)
    if m:
        return "https://www." + m.group(1).replace("embedmap", "route")
    return None


def find_route_media(html: str, base: str) -> tuple[str | None, int]:
    """Recorrido incrustado o en imagen dentro de la propia página: mapas (iframe), widgets de Strava, imágenes «recorrido»."""
    base = page_base(html, base)
    s = soup(html)
    for f in s.find_all("iframe"):
        v = _embed_to_view(f.get("src") or f.get("data-src") or "")
        if v:
            return v, 5
    for d in s.select("[data-embed-id][data-embed-type]"):   # widget de Strava
        if (d.get("data-embed-type") or "") in ("route", "activity", "segment"):
            return f"https://www.strava.com/{d['data-embed-type']}s/{d['data-embed-id']}", 5
    for img in s.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
        label = " ".join(str(img.get(k) or "") for k in ("alt", "title")) + " " + src
        if re.search(r"recorrido|circuito|recorregut|ibilbide|plano|perfil|mapa[-_ ]|route|course", label, re.I) \
                and not _IMG_BAD.search(src) and re.search(r"\.(jpe?g|png|webp)(\?|$)", src, re.I):
            return abs_url(base, src), 3
    return None, 0


def find_route(html: str, base: str, strict: bool = False) -> str | None:
    """Enlace al recorrido: Strava, Wikiloc, Garmin, Google My Maps…, un .gpx/.kml o una página «Recorrido»
    de la propia web. Con strict=True (páginas de calendarios) solo valen servicios de rutas y archivos GPX/KML."""
    base = page_base(html, base)
    best, best_score = None, 0
    for a in soup(html).find_all("a", href=True):
        href = abs_url(base, a["href"])
        if not href.startswith("http"):
            continue
        text = a.get_text(" ", strip=True)[:80] + " " + str(a.get("title") or "")
        score = 0
        if re.search(r"\.(gpx|kml|kmz)(\?|$)", href, re.I):
            score = 6
        elif _ROUTE_HOSTS.search(href):
            score = 5
        elif not strict and not _ROUTE_BAD.search(href) and domain(href) == domain(base) and (
                _ROUTE_WORD.search(text) or _ROUTE_URL_WORD.search(href.split("?")[0].rsplit("/", 1)[-1])):
            score = 3 if re.search(r"\.(jpe?g|png|webp|pdf)(\?|$)", href, re.I) else 2
        if score > best_score:
            best, best_score = href, score
    if not strict:
        emb, sc = find_route_media(html, base)
        if emb and sc > best_score:
            best, best_score = emb, sc
    else:   # en calendarios, solo mapas incrustados de servicios de rutas (no imágenes)
        emb, sc = find_route_media(html, base)
        if emb and sc >= 5 and sc > best_score:
            best, best_score = emb, sc
    return best if best_score >= 2 else None


# ---------------------------------------------------------------- estado de la inscripción
_ST_AGOTADA = re.compile(r"(dorsales|inscripciones|plazas|entradas)\s+(agotad|completad)|sold\s?out|\bagotado\b(?=.{0,20}dorsal)|"
                         r"aforo\s+completo|sin\s+plazas\s+disponibles|no\s+quedan\s+(dorsales|plazas)|dorsals\s+esgotats", re.I)
_ST_CERRADA = re.compile(r"inscripci[oó]n(es)?\s+(cerrad|finalizad|tancad)|plazo\s+de\s+inscripci[oó]n\s+(cerrado|finalizado)|"
                         r"inscripci[oó]n(es)?\s+no\s+disponibles?|registration\s+closed|inscripcions\s+tancades", re.I)
_ST_PROX = re.compile(r"inscripci[oó]n(es)?\s+(pr[oó]ximamente|muy\s+pronto)|(se\s+abrir[aá]n|abrir[aá]n)\s+(las\s+)?inscripciones|"
                      r"apertura\s+de\s+(las\s+)?inscripciones|inscripcions\s+properament|coming\s+soon", re.I)
_ST_ABIERTA = re.compile(r"inscripci[oó]n(es)?\s+(abiertas?|obertes?|disponibles?)|registration\s+open|"
                         r"[uú]ltimos\s+dorsales|quedan\s+pocos\s+dorsales", re.I)
_ST_BOTON = re.compile(r"^\s*(inscr[ií]bete( ya| ahora)?|inscribirme|inscribirse|inscripci[oó]n online|comprar dorsal|"
                       r"apúntate|apuntate|registrarse|inscriu-te)\s*$", re.I)


def registration_status(html: str, signup_platform: bool = False) -> str | None:
    """Estado de la inscripción si la página lo dice claramente: abierta, agotada, cerrada o proximamente.
    Manda lo que la página dice a la vista; el dato oculto (schema.org) solo si la página no dice nada,
    porque algunas plataformas lo marcan «SoldOut» aunque la inscripción esté abierta."""
    s = soup(html)
    for t in s(["script", "style", "noscript", "footer", "nav"]):
        t.decompose()
    text = re.sub(r"\s+", " ", s.get_text(" "))[:20000]
    if _ST_AGOTADA.search(text):
        return "agotada"
    if _ST_CERRADA.search(text):
        return "cerrada"
    if _ST_PROX.search(text):
        return "proximamente"
    if _ST_ABIERTA.search(text):
        return "abierta"
    if signup_platform:     # en una plataforma de inscripción, un botón «Inscríbete» activo = abierta
        for b in s.find_all(["a", "button"]):
            if _ST_BOTON.match(b.get_text(" ", strip=True)) and not b.get("disabled") and "disabled" not in " ".join(b.get("class") or []):
                return "abierta"
    for ev in jsonld_events(html):     # último recurso: dato estructurado (offers.availability)
        offers = ev.get("offers") or []
        for o in (offers if isinstance(offers, list) else [offers]):
            av = str(o.get("availability") or "") if isinstance(o, dict) else ""
            if "PreOrder" in av or "PreSale" in av:
                return "proximamente"
            if "InStock" in av or "LimitedAvailability" in av:
                return "abierta"
            # «SoldOut» oculto no se usa: Rockthesport lo pone incluso con la inscripción abierta
    return None


def tags_from_km(km: str) -> list[str]:
    """Etiquetas de distancia a partir de los km de la ficha («21,097 km · 10 km» → ["21K", "10K"])."""
    out = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*km", km or "", re.I):
        v = float(m.group(1).replace(",", "."))
        if 42 <= v <= 42.4:
            t = "42K"
        elif 21 <= v <= 21.2:
            t = "21K"
        else:
            t = f"{round(v, 1):g}".replace(".", ",") + "K"
        if t not in out:
            out.append(t)
    return out


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


def split_name_place(name: str) -> tuple[str, str]:
    """Separa nombres de listado con lugar y fecha pegados al final:
    «XII TimonCap Costa Cálida 2026 Cabo de Palos 24/10/2026» → («XII TimonCap Costa Cálida», «Cabo de Palos»).
    Solo actúa si el nombre acaba en una fecha; si no, lo devuelve tal cual."""
    n = (name or "").strip()
    m = re.match(r"^(.*?)\s+\d{1,2}/\d{1,2}/20\d{2}\s*$", n)
    if not m:
        return n, ""
    n = m.group(1).strip()
    m2 = re.match(r"^(.*\S)\s+20\d{2}\s+(.{2,40})$", n)
    if m2:
        return m2.group(1).strip(), m2.group(2).strip()
    w = n.split()
    for k in range(min(6, len(w) // 2), 0, -1):   # «… San Pedro del Pinatar San Pedro del Pinatar»
        if [x.lower() for x in w[-k:]] == [x.lower() for x in w[-2 * k:-k]]:
            return " ".join(w[:-k]), " ".join(w[-k:])
    return n, ""


def clean_name(name: str, city: str = "") -> str:
    """Quita la fecha (y el lugar) pegados al final y el año suelto del final."""
    n, _ = split_name_place(name)
    return re.sub(r"\s+20\d{2}$", "", n).strip()


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
    half = re.search(r"\b(media|medio|mitja|mig)\s+marat|\bhalf\s+marathon|\bsemi\s?marat|\b21[.,]0\d{1,2}\b|\b21\s?k\b|\bmezza", t)
    full = re.search(r"\bmarat(o|on|hon)\b|\b42[.,]195\b|\b42\s?k\b", t)
    if full and not re.search(r"\b(media|medio|mitja|mig|half|semi)\s?marat", t):
        out.append("42K")
    if half:
        out.append("21K")
    for n in ("15", "10", "8", "5"):
        if re.search(rf"\b{n}\s?k(m|ms)?\b", t):
            out.append(f"{n}K")
    return out
