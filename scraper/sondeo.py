"""Sondeo rápido de fuentes: estado HTTP de varias URL. Escribe estado/sondeo.json."""
import json
from pathlib import Path

import requests

from . import config

URLS = [
    "https://running.life/races/spain", "https://running.life/5k-races/spain", "https://running.life/15k-races/spain",
    "https://running.life/running-races/spain", "https://running.life/es/carreras/espana",
    "https://www.carreraspopulares.com/", "https://www.carreraspopulares.com/calendario/",
    "https://runedia.mundodeportivo.com/calendario-carreras/espana/", "https://www.runnea.com/calendario-carreras/",
    "https://www.corriendovoy.com/carreras", "https://www.todoscorremos.com/", "https://www.sportmaniacs.com/es/races",
    "https://www.rockthesport.com/es/eventos", "https://www.mychip.es/es/calendario", "https://www.deporticket.com/",
    "https://www.championchipnorte.com/", "https://www.atletismorfea.es/calendario", "https://www.ahotu.com/es/calendario/running/espana",
    "https://www.finishers.com/es/carreras/espana", "https://www.worldsmarathons.com/es/s/running/spain",
    "https://www.calendariocarreras.es/", "https://www.carreraspormontana.com/", "https://www.runningzaragoza.com/calendario",
    "https://www.sportmaniacs.com/es/calendar", "https://www.inscripcionesonline.com/", "https://www.lineadesalida.net/",
]
out = []
import re
from urllib.parse import urlparse
import urllib.robotparser
def robots_ok(u):
    rp = urllib.robotparser.RobotFileParser(f"{urlparse(u).scheme}://{urlparse(u).netloc}/robots.txt")
    try:
        rp.read(); return rp.can_fetch(config.USER_AGENT, u)
    except Exception:
        return None
for ua in (config.USER_AGENT,):
    for u in URLS:
        try:
            r = requests.get(u, timeout=25, headers={"User-Agent": ua, "Accept-Language": "es-ES,es;q=0.9"})
            t = r.text
            out.append({"ua": ua[:20], "url": u, "status": r.status_code, "final": r.url, "bytes": len(r.content),
                        "server": r.headers.get("server"), "robots": robots_ok(u),
                        "jsonld_event": len(re.findall(r'"@type"\s*:\s*"(?:Sports)?Event"', t)),
                        "fechas": len(re.findall(r"\b20(?:26|27)-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/20(?:26|27)\b", t)),
                        "titulo": (re.search(r"<title>(.*?)</title>", t, re.S) or [None, ""])[1].strip()[:80]})
        except Exception as e:
            out.append({"ua": ua[:20], "url": u, "error": repr(e)[:200]})
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
