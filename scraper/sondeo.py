"""Crea el enlace corto de la web principal con un nombre propio en is.gd. Escribe estado/sondeo.json."""
import json
from pathlib import Path
from urllib.parse import quote
import requests
from . import config
URL = "https://alexample.github.io/RunningSpain/"
res = {}
for alias in ("runningspain", "running_spain", "runningspain_es", "runspain"):
    r = requests.get(f"https://is.gd/create.php?format=json&url={quote(URL, safe='')}&shorturl={alias}",
                     headers={"User-Agent": config.USER_AGENT}, timeout=20)
    res[alias] = r.text[:200]
    if '"shorturl"' in r.text:
        break
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(res)
