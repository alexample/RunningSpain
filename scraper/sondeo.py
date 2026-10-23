"""Sondeo rápido de fuentes: estado HTTP de varias URL. Escribe estado/sondeo.json."""
import json
from pathlib import Path

import requests

from . import config

URLS = [
    "https://sportplan.es/robots.txt",
    "https://sportplan.es/",
    "https://sportplan.es/es/regions/madrid",
    "https://sportplan.es/es/regions/barcelona",
    "https://sportplan.es/es/series/san-silvestre",
    "https://www.sportplan.es/es/regions/madrid",
]
out = []
for ua in (config.USER_AGENT, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"):
    for u in URLS:
        try:
            r = requests.get(u, timeout=25, headers={"User-Agent": ua, "Accept-Language": "es-ES,es;q=0.9"})
            out.append({"ua": ua[:20], "url": u, "status": r.status_code, "final": r.url, "bytes": len(r.content),
                        "server": r.headers.get("server"), "inicio": r.text[:300]})
        except Exception as e:
            out.append({"ua": ua[:20], "url": u, "error": repr(e)[:200]})
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps([{k: o.get(k) for k in ("ua", "url", "status", "final", "error")} for o in out], indent=1))
