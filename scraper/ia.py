"""Último recurso: lectura con IA (Workers AI del worker de Cloudflare, gratis y con tope diario).

Solo se usa, de forma excepcional, cuando el robot no ha podido por sí mismo:
  · la ficha se publicó hace IA_MIN_DIAS_PUBLICADA días o más,
  · la carrera es próxima (dentro de IA_PROXIMA_DIAS),
  · y aún le falta cartel, km, recorrido o estado de inscripción.
Cada carrera se pregunta como mucho una vez cada IA_REINTENTO_DIAS, y nunca más de IA_MAX_POR_EJECUCION por vuelta.
La IA solo puede ELEGIR entre imágenes y enlaces que el robot ha visto en las páginas (no puede inventar direcciones),
y lo que devuelve se valida igual que lo que encuentra el robot.
"""
import os
import re
from datetime import date, timedelta

import requests

from . import config, enrich, net, parse

ENDPOINT = "https://dondeloechan-ia.alexample.workers.dev/runningspain-ia"
FALTAN = {"banner": "cartel", "km": "km", "route": "recorrido", "inscripcion": "estado de inscripción"}
_ROUTE_LINK = re.compile(r"recorrido|recorregut|ibilbide|circuito|mapa|plano|track|gpx|kml|wikiloc|strava|garmin|komoot|"
                         r"maps/d/|mymaps|ridewithgps|plotaroute|perfil", re.I)


def _token() -> str | None:
    """Token firmado por GitHub para esta ejecución (el worker comprueba que viene de alexample/RunningSpain)."""
    url, tok = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"), os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not url or not tok:
        return None
    try:
        r = requests.get(url + "&audience=runningspain-ia", headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        return r.json().get("value")
    except Exception:
        return None


def candidatas(db: dict, today: date) -> list[dict]:
    hasta = (today + timedelta(days=config.IA_PROXIMA_DIAS)).isoformat()
    publicada = (today - timedelta(days=config.IA_MIN_DIAS_PUBLICADA)).isoformat()
    reintento = (today - timedelta(days=config.IA_REINTENTO_DIAS)).isoformat()
    out = []
    for r in db["races"]:
        if not (today.isoformat() <= r["date"] <= hasta) or r.get("locked"):
            continue
        if (r.get("addedAt") or "2000-01-01") > publicada or (r.get("iaAt") or "") > reintento:
            continue
        if not [k for k in FALTAN if not r.get(k)]:
            continue
        if not (r.get("official") and r.get("url")) and not enrich.source_pages(r):
            continue
        out.append(r)
    out.sort(key=lambda r: r["date"])
    return out


def _material(r: dict) -> dict:
    """Texto, imágenes y enlaces de la web oficial, el reglamento y las fichas de calendario."""
    pages = ([r["url"]] if r.get("official") and r.get("url") else []) + enrich.source_pages(r)
    texto, imgs, links, vistos = [], [], [], set()
    for u in pages[:3]:
        html, final, _ = net.get(u)
        if not html or isinstance(html, bytes):
            continue
        texto.append(f"[{final}]\n" + parse.own_part(parse.page_text(html))[:5000])
        base = parse.page_base(html, final)
        s = parse.soup(html)
        for im in s.find_all("img"):
            src = im.get("data-src") or im.get("data-lazy-src") or im.get("src") or ""
            cls = " ".join(im.get("class") or [])
            if not src or re.search(r"event-card|card-thumb|related", cls, re.I):
                continue
            src = parse.abs_url(base, src)
            if (src.startswith("http") and src not in vistos and not parse.IMG_GENERIC.search(src)
                    and not parse._IMG_BAD.search(src)):
                vistos.add(src)
                imgs.append({"u": src, "alt": (im.get("alt") or im.get("title") or "")[:80]})
        for a in s.find_all("a", href=True):
            href = parse.abs_url(base, a["href"])
            t = a.get_text(" ", strip=True)[:80]
            if href.startswith("http") and href not in vistos and _ROUTE_LINK.search(href + " " + t):
                vistos.add(href)
                links.append({"u": href, "t": t})
    if r.get("regulation"):
        reg, _, _ = enrich.fetch_text(r["regulation"])
        if reg:
            texto.append("[Reglamento]\n" + reg[:4000])
    return {"texto": "\n\n".join(texto)[:14000], "imagenes": imgs[:30], "enlaces": links[:40]}


def _aplica(r: dict, res: dict, mat: dict, today: date) -> list[str]:
    """Solo rellena lo que falta y solo si pasa las mismas comprobaciones que lo del robot."""
    puesto = []
    if not r.get("km") and isinstance(res.get("km"), str):
        km = parse.extract_km("distancia " + res["km"].replace("·", " y distancia "), r.get("name", ""))
        if km and not parse.km_dudosos(km, r["name"]):
            r["km"] = km
            tags = parse.tags_from_km(km)
            if tags:
                r["distances"] = tags
            puesto.append("km")
    st = res.get("inscripcion")
    if not r.get("inscripcion") and st in ("abierta", "cerrada", "agotada", "proximamente"):
        r["inscripcion"], r["inscripcionAt"] = st, today.isoformat()
        puesto.append("inscripcion")
    i = res.get("cartel")
    if not r.get("banner") and isinstance(i, int) and 0 <= i < len(mat["imagenes"]):
        r["banner"], r["bannerScore"] = mat["imagenes"][i]["u"], 3
        puesto.append("banner")
    i = res.get("recorrido")
    if not r.get("route") and isinstance(i, int) and 0 <= i < len(mat["enlaces"]):
        u = mat["enlaces"][i]["u"]
        if parse.is_route_url(u) or re.search(r"\.(gpx|kml|kmz|pdf|jpe?g|png)(\?|$)", u, re.I):
            r["route"] = u
            puesto.append("route")
    return puesto


def pasada(db: dict, today: date, changes: dict, log) -> int:
    if not config.IA_ACTIVA:
        return 0
    todo = candidatas(db, today)
    log(f"IA (último recurso): {len(todo)} carreras próximas siguen sin datos tras {config.IA_MIN_DIAS_PUBLICADA} días; "
        f"se preguntan {min(len(todo), config.IA_MAX_POR_EJECUCION)}")
    if not todo:
        return 0
    tok = _token()
    if not tok:
        log("  IA: sin token de GitHub (solo funciona dentro de GitHub Actions)")
        return 0
    rellenas = 0
    for r in todo[: config.IA_MAX_POR_EJECUCION]:
        mat = _material(r)
        r["iaAt"] = today.isoformat()
        if not mat["texto"] and not mat["imagenes"]:
            continue
        faltan = [FALTAN[k] for k in FALTAN if not r.get(k)]
        try:
            resp = requests.post(ENDPOINT, headers={"Authorization": f"Bearer {tok}"}, timeout=90,
                                 json={"nombre": r["name"], "fecha": r["date"], "lugar": f"{r.get('city', '')} ({r.get('region', '')})",
                                       "faltan": faltan, **mat})
        except Exception as e:
            log(f"  IA: error de conexión {e}")
            break
        if resp.status_code == 429:
            log("  IA: tope diario alcanzado")
            break
        if resp.status_code != 200:
            log(f"  IA: respuesta {resp.status_code}")
            continue
        puesto = _aplica(r, resp.json(), mat, today)
        if puesto:
            rellenas += 1
            r["ia"] = sorted(set((r.get("ia") or []) + puesto))
            r["changedAt"] = today.isoformat()
            if r["id"] not in changes["added"]:
                lst = changes["updated"].setdefault(r["id"], [])
                lst += [k for k in puesto if k not in lst]
        log(f"  IA: {r['name']} ({r['date']}) → {', '.join(puesto) or 'nada fiable'}")
    log(f"Fichas completadas con IA: {rellenas}")
    return rellenas
