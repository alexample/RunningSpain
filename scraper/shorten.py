"""Enlaces acortados (is.gd, con TinyURL de respaldo) para las fichas de las carreras.

Se guardan en docs/data/cortos.json ({id: "https://is.gd/…"}): los usan los tweets y el botón de compartir.
Cada enlace se crea una sola vez; por ejecución se acortan como mucho MAX_CORTOS (primero las carreras más próximas)
para respetar los límites de los acortadores.
"""
import json
import time
from pathlib import Path
from urllib.parse import quote

import requests

from . import config, share

FILE = Path(__file__).resolve().parent.parent / "docs" / "data" / "cortos.json"
MAX_CORTOS = 60
H = {"User-Agent": config.USER_AGENT}


def load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(d: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(d, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


def shorten(url: str) -> str | None:
    """Acorta con is.gd; si falla, con TinyURL. None si los dos fallan."""
    for api in (f"https://is.gd/create.php?format=simple&url={quote(url, safe='')}",
                f"https://tinyurl.com/api-create.php?url={quote(url, safe='')}"):
        try:
            r = requests.get(api, headers=H, timeout=20)
            t = r.text.strip()
            if r.ok and t.startswith("https://") and len(t) < 40:
                return t
        except requests.RequestException:
            pass
        time.sleep(1)
    return None


def ensure(races: list[dict], must: list[str] | None = None, limit: int = MAX_CORTOS, log=print) -> dict:
    """Crea los enlaces cortos que falten: primero los de `must` (p. ej. las carreras que se van a tuitear),
    luego las carreras más próximas. Borra los de carreras que ya no están."""
    d = load()
    ids = {r["id"] for r in races}
    d = {k: v for k, v in d.items() if k in ids}
    by_id = {r["id"]: r for r in races}
    order = [i for i in (must or []) if i in by_id] + [r["id"] for r in sorted(races, key=lambda r: r["date"])]
    made = 0
    for rid in order:
        if made >= limit:
            break
        if rid in d:
            continue
        s = shorten(share.share_url(by_id[rid]))
        if not s:
            log("Acortador sin respuesta: se deja para la próxima vuelta")
            break
        d[rid] = s
        made += 1
        time.sleep(1.5)
    save(d)
    log(f"Enlaces cortos: {made} nuevos · {len(d)} en total")
    return d
