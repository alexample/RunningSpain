"""Sondeo: contexto de la frase que da el estado de inscripción en varias páginas. Escribe estado/sondeo.json."""
import json
import re
from pathlib import Path

import requests

from . import config, parse

H = {"User-Agent": config.USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"}
URLS = [
    "https://web.rockthesport.com/es/event/fedola-family-run-2026",
    "https://web.rockthesport.com/es/event/iv-ruta-del-barbo-cadreita",
    "https://web.rockthesport.com/es/event/29-salto-15k-donostia-san-sebast",
    "https://web.rockthesport.com/es/event/vi-carrera-hazvisible22q",
    "https://burgos21k.com/",
    "https://gesport.cat/mitja-marato-costa-barcelona-maresme-2026/",
]
pats = {"agotada": parse._ST_AGOTADA, "cerrada": parse._ST_CERRADA, "prox": parse._ST_PROX, "abierta": parse._ST_ABIERTA}
out = []
for u in URLS:
    try:
        r = requests.get(u, headers=H, timeout=25)
        s = parse.soup(r.text)
        for t in s(["script", "style", "noscript", "footer", "nav"]):
            t.decompose()
        text = re.sub(r"\s+", " ", s.get_text(" "))[:20000]
        hits = {}
        for k, p in pats.items():
            hits[k] = [text[max(0, m.start() - 90):m.end() + 60] for m in p.finditer(text)][:4]
        ld = [str((e.get("offers") or {})) [:300] for e in parse.jsonld_events(r.text)]
        out.append({"url": u, "status": r.status_code, "estado": parse.registration_status(r.text, True), "hits": hits, "ld": ld})
    except Exception as e:
        out.append({"url": u, "error": repr(e)[:200]})
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
