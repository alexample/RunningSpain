"""Sondeo de páginas de carrera y listados. Escribe estado/sondeo.json."""
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import config, parse

H = {"User-Agent": config.USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"}
URLS = [
    # listados
    "https://runedia.mundodeportivo.com/calendario-carreras/espana/",
    "https://runedia.mundodeportivo.com/calendario-carreras/espana/?pag=2",
    "https://runedia.mundodeportivo.com/sitemap_index.xml",
    "https://www.carreraspopulares.com/calendario_carreras/lista",
    "https://sportmaniacs.com/es/races?page=2",
    "https://running.life/10k-races/spain/andalucia",
    # fichas
    "https://runedia.mundodeportivo.com/carrera/cursa-popular-sant-marti-2026/202637000/",
    "https://sportmaniacs.com/es/races/13ordm-carrera-popular-la-villa-de-don-fadrique-toledo",
    "https://www.lineadesalida.net/carreras/xi-carrera-solidaria-puerto-de-cartagena-10kcpc",
]
out = []
for u in URLS:
    try:
        r = requests.get(u, headers=H, timeout=25)
        t = r.text
        s = BeautifulSoup(t, "html.parser")
        evs = parse.jsonld_events(t) if "xml" not in r.headers.get("content-type", "") else []
        hrefs = [urljoin(r.url, a["href"]) for a in s.find_all("a", href=True)]
        o = {"url": u, "status": r.status_code, "final": r.url, "ctype": r.headers.get("content-type"),
             "bytes": len(t), "jsonld": [parse.event_fields(e) for e in evs[:2]],
             "h1": (s.find("h1").get_text(" ", strip=True)[:100] if s.find("h1") else None),
             "fechas_texto": re.findall(r"\b\d{1,2}/\d{1,2}/20\d{2}\b|\b\d{1,2} de [a-záé]+ de 20\d{2}\b|\b20\d{2}-\d{2}-\d{2}\b", t)[:8],
             "paginacion": sorted({h for h in hrefs if re.search(r"[?&](pag|page|p)=\d+", h)})[:8],
             "eventos_muestra": [h for h in hrefs if re.search(r"/carrera/|/races/[^/?]+$|/carreras/|/event/|/calendario_carreras/(?!lista)", h)][:10],
             "xml_locs": re.findall(r"<loc>(.*?)</loc>", t)[:15],
             "texto": re.sub(r"\s+", " ", s.get_text(" "))[:700]}
        out.append(o)
    except Exception as e:
        out.append({"url": u, "error": repr(e)[:200]})
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
