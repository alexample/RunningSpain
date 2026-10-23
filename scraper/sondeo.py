"""Sondeo de Wikiloc: robots.txt y buscador. Escribe estado/sondeo.json."""
import json
import re
from pathlib import Path

import requests

from . import config

H = {"User-Agent": config.USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"}
URLS = [
    "https://es.wikiloc.com/robots.txt",
    "https://es.wikiloc.com/wikiloc/find.do?q=media+maraton+cuenca",
    "https://es.wikiloc.com/rutas/correr?q=media+maraton+cuenca",
    "https://es.wikiloc.com/wikiloc/map.do?q=media+maraton+cuenca",
    "https://es.wikiloc.com/wikiloc/spatialArtifacts.do?q=media+maraton+cuenca",
    "https://es.wikiloc.com/rutas/correr/espana/castilla-la-mancha/cuenca",
    "https://api.wikiloc.com/",
]
out = []
for u in URLS:
    try:
        r = requests.get(u, headers=H, timeout=25)
        t = r.text
        out.append({"url": u, "status": r.status_code, "final": r.url, "server": r.headers.get("server"),
                    "ctype": r.headers.get("content-type"), "bytes": len(t),
                    "titulo": (re.search(r"<title>(.*?)</title>", t, re.S) or [None, ""])[1].strip()[:100],
                    "rutas": sorted(set(re.findall(r"https://es\.wikiloc\.com/rutas-[a-z-]+/[a-z0-9-]+-\d+", t)))[:10],
                    "inicio": t[:1500] if "robots" in u else t[:300]})
    except Exception as e:
        out.append({"url": u, "error": repr(e)[:200]})
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
