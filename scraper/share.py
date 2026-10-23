"""Páginas para compartir cada carrera (docs/c/<id>.html).

WhatsApp, Telegram o X muestran la vista previa de un enlace leyendo sus etiquetas og:*. La web es una
sola página, así que cada carrera tiene una pequeña página con su nombre, fecha y cartel que, al abrirse,
lleva a su ficha en la web (…/#c-<id>).
"""
import html
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "docs"
OUT = ROOT / "c"
SITE = "https://alexample.github.io/RunningSpain/"
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def safe_id(rid: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", rid.lower())[:120]


def describe(r: dict) -> tuple[str, str]:
    y, m, d = map(int, r["date"].split("-"))
    when = f"{DAYS[date(y, m, d).weekday()]} {d} de {MONTHS[m - 1]} de {y}" + (f" · {r['time']} h" if r.get("time") else "")
    place = r.get("city") or ""
    if r.get("region") and r["region"] != place:
        place = f"{place} ({r['region']})" if place else r["region"]
    bits = [when]
    if place:
        bits.append(place)
    dist = r.get("km") or " · ".join(r.get("distances") or [])
    if dist:
        bits.append(dist)
    return when, " · ".join(bits[1:]) if len(bits) > 1 else ""


def page(r: dict) -> str:
    e = lambda s: html.escape(s or "", quote=True)
    when, rest = describe(r)
    target = f"{SITE}#c-{r['id']}"
    self_url = f"{SITE}c/{safe_id(r['id'])}.html"
    img = r.get("banner") or SITE + "logo.png"
    desc = when + (" · " + rest if rest else "")
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(r['name'])} · RunningSpain</title>
<meta name="description" content="{e(desc)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="RunningSpain">
<meta property="og:title" content="{e(r['name'])}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{e(img)}">
<meta property="og:url" content="{e(self_url)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="../logo.svg">
<link rel="canonical" href="{e(self_url)}">
<meta http-equiv="refresh" content="0; url={e(target)}">
<script>location.replace({target!r});</script>
</head><body style="font-family:system-ui,sans-serif;padding:24px">
<p><a href="{e(target)}">{e(r['name'])}</a> · {e(desc)}</p>
</body></html>
"""


def write_all(races: list[dict]) -> int:
    """Crea o actualiza las páginas de las carreras actuales y borra las de carreras que ya no están."""
    OUT.mkdir(parents=True, exist_ok=True)
    keep = set()
    changed = 0
    for r in races:
        name = safe_id(r["id"]) + ".html"
        keep.add(name)
        f = OUT / name
        content = page(r)
        if not f.exists() or f.read_text(encoding="utf-8") != content:
            f.write_text(content, encoding="utf-8")
            changed += 1
    for f in OUT.glob("*.html"):
        if f.name not in keep:
            f.unlink()
    return changed


def share_url(r: dict) -> str:
    return f"{SITE}c/{safe_id(r['id'])}.html"
