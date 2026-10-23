"""Sondeo de fuentes: robots.txt y estructura de enlaces. Escribe estado/sondeo.json."""
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import config

H = {"User-Agent": config.USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"}
SITES = {
    "running.life": ["https://running.life/5k-races/spain"],
    "runedia.mundodeportivo.com": ["https://runedia.mundodeportivo.com/calendario-carreras/"],
    "sportmaniacs.com": ["https://sportmaniacs.com/es/races"],
    "www.lineadesalida.net": ["https://www.lineadesalida.net/"],
    "www.atletismorfea.es": ["https://www.atletismorfea.es/calendario"],
    "www.carreraspopulares.com": ["https://www.carreraspopulares.com/"],
    "worldsmarathons.com": ["https://worldsmarathons.com/es/s/running/spain"],
}
out = {}
for host, pages in SITES.items():
    o = {}
    try:
        r = requests.get(f"https://{host}/robots.txt", headers=H, timeout=20)
        o["robots_status"] = r.status_code
        o["robots"] = r.text[:1500]
    except Exception as e:
        o["robots_error"] = repr(e)[:150]
    for u in pages:
        try:
            r = requests.get(u, headers=H, timeout=25)
            s = BeautifulSoup(r.text, "html.parser")
            hrefs = [urljoin(r.url, a["href"]) for a in s.find_all("a", href=True)]
            same = [h for h in hrefs if urlparse(h).netloc.endswith(host.replace("www.", ""))]
            pref = Counter("/".join(urlparse(h).path.split("/")[:3]) for h in same)
            o["pagina"] = {"url": u, "status": r.status_code, "enlaces": len(hrefs),
                           "prefijos": pref.most_common(12),
                           "muestra": [h for h in same if re.search(r"\d", urlparse(h).path)][:15],
                           "externos": Counter(urlparse(h).netloc for h in hrefs if not urlparse(h).netloc.endswith(host.replace("www.", ""))).most_common(8),
                           "texto": re.sub(r"\s+", " ", s.get_text(" "))[:1200]}
        except Exception as e:
            o["pagina_error"] = repr(e)[:150]
    out[host] = o
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
