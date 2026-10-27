"""Completa cada carrera desde su web oficial: enlace, reglamento, precio, hora, km y cartel."""
import io
import json
import os
import re
from datetime import date

import requests

from . import config, net, parse

_llm_calls = 0


def pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return " ".join((p.extract_text() or "") for p in reader.pages[:12])
    except Exception:
        return ""


def fetch_text(url: str) -> tuple[str, str | None, str]:
    """Devuelve (texto, html_o_None, url_final) de una página o PDF."""
    body, final, ctype = net.get(url)
    if body is None:
        return "", None, final
    if isinstance(body, bytes):
        return pdf_text(body), None, final
    return parse.page_text(body), body, final


def resolve_regulation(url: str, found_on: str | None = None) -> str | None:
    """Enlace más directo al reglamento QUE FUNCIONE.
    - Si es una página, entra y busca el PDF/documento que contenga.
    - Comprueba que el enlace abre (y que un «.pdf» es de verdad un PDF).
    - Si el documento no abre, vale la página donde estaba; si nada abre, None."""
    if not url:
        return None
    candidates = []
    if parse.is_document(url):
        candidates = [url, found_on]
    else:
        body, final, ctype = net.get(url)
        if body is not None and (isinstance(body, bytes) or "pdf" in (ctype or "")):
            candidates = [final, found_on]          # la «página» era el PDF (redirección)
        elif body is not None:
            doc = parse.find_regulation(body, final, only_docs=True)
            candidates = [doc, final, found_on]
        else:
            candidates = [found_on]
    for c in candidates:
        if c:
            ok, final, _ = net.probe(c)
            if ok:
                return c if parse.is_document(c) else final
    return None


def route_from_site(url: str) -> str | None:
    """Recorrido en la web de la carrera: en la portada o, si hay una página «Recorrido», dentro de ella."""
    html, final, _ = net.get(url)
    if not html or isinstance(html, bytes):
        return None
    found = parse.find_route(html, final)
    if not found:
        return None
    # si lo encontrado es una página de la propia web («/recorrido/»), mirar dentro el mapa, GPX o imagen
    if net.domain(found) == net.domain(final) and not re.search(r"\.(gpx|kml|kmz|jpe?g|png|webp|pdf)(\?|$)", found, re.I):
        inner, f2, _ = net.get(found)
        if inner and not isinstance(inner, bytes):
            emb, _ = parse.find_route_media(inner, f2)
            links = parse.find_route(inner, f2)
            better = emb or (links if links and links != found and not net.domain(links) == net.domain(f2) else None)
            if better:
                return better
    return found


def ask_llm(name: str, d: str, text: str) -> dict:
    """Lectura opcional con IA (solo si hay ANTHROPIC_API_KEY). Barato: un modelo pequeño."""
    global _llm_calls
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or _llm_calls >= config.LLM_MAX_CALLS or not text:
        return {}
    _llm_calls += 1
    prompt = (
        f"Texto de la web o reglamento de la carrera «{name}» (fecha prevista {d}).\n"
        "Devuelve SOLO un JSON con: date (YYYY-MM-DD de la edición próxima o null), "
        "time (hora de salida principal HH:MM o null), km (distancias, p. ej. \"21,097 km · 10 km\", o null), "
        "price (precio de inscripción resumido, p. ej. \"15–25 €\", o null). No inventes: usa null si no consta.\n\n"
        + text[:14000]
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": config.LLM_MODEL, "max_tokens": 200,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        out = "".join(b.get("text", "") for b in r.json().get("content", []))
        m = re.search(r"\{.*\}", out, re.S)
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


def needs_work(r: dict, today: date) -> bool:
    if r.get("locked"):
        return False
    complete = (r.get("official") and r.get("price") and r.get("time") and r.get("regulation")
                and r.get("banner") and r.get("km") and not r.get("otraFecha") and not r.get("kmRevisar"))
    if complete:
        return False
    last = r.get("checkedAt")
    if not last:
        return True
    try:
        since = (today - date.fromisoformat(last[:10])).days
        until = (date.fromisoformat(r["date"]) - today).days
    except ValueError:
        return True
    if until <= config.RECHECK_SOON_DAYS:
        return True          # en cada vuelta (cada vuelta pasa una sola vez por cada carrera)
    if until <= config.RECHECK_NEAR_DAYS:
        return since >= 1
    return since >= config.RECHECK_DAYS


def source_pages(r: dict) -> list[str]:
    """Fichas de calendario de la carrera (la principal y las de otras fuentes), sin las que bloquean al robot."""
    out = []
    for u in [r.get("source")] + list(r.get("alt") or []):
        if u and u not in out and not (not config.SPORTPLAN_ACTIVO and "sportplan.es" in u):
            out.append(u)
    return out


def from_sources(r: dict) -> dict:
    """Lo que dicen las fichas de calendario: candidatas a web oficial, hora, precio y km."""
    found = {"official": [], "time": None, "price": None, "km": None}
    for u in source_pages(r):
        html, final, _ = net.get(u)
        if not html or isinstance(html, bytes):
            continue
        ev = parse.jsonld_events(html)
        f = parse.event_fields(ev[0]) if ev else {}
        found["official"] += f.get("official_candidates") or []
        g = parse.guess_official(html, final)
        if g:
            found["official"].append(g)
        text = parse.own_part(parse.page_text(html))[:8000]
        found["time"] = found["time"] or parse.local_time(f.get("start", ""), r.get("region", "")) or parse.extract_time(text)
        found["price"] = found["price"] or f.get("price") or parse.extract_price(text)
        found["km"] = found["km"] or parse.extract_km(text[:4000], r.get("name", ""))
    return found


def enrich(r: dict, today: date) -> dict:
    """Devuelve los campos nuevos que se han podido confirmar para la carrera r."""
    if not r.get("kmRevisar"):
        return _enrich(r, today)
    # km leídos con la regla antigua: se vuelven a leer con la nueva; si no sale nada, se quedan los que había
    upd = _enrich({k: v for k, v in r.items() if k != "km"}, today)
    upd["kmRevisar"] = ""
    if not upd.get("km"):
        upd["km"] = r.get("km")
    return upd


def _enrich(r: dict, today: date) -> dict:
    upd = {"checkedAt": today.isoformat()}
    src = from_sources(r) if (not r.get("official") or not r.get("time") or not r.get("price") or not r.get("km")) else None
    url = r.get("url") if r.get("official") else None
    if not url:
        guess = r.get("official_guess")
        if guess and "sportplan.es" in guess and not config.SPORTPLAN_ACTIVO:
            guess = None
        url = guess or ((src or {}).get("official") or [None])[0]
    if not url:
        upd["nosite"] = True
        _fill(upd, r, src)
        return upd

    text, html, final = fetch_text(url)
    if not text and not html:
        _fill(upd, r, src)
        return upd
    if r.get("otraFecha") and text:   # dos fuentes con fechas distintas: decide la web oficial si dice una sola
        esta, otra = parse.date_in_text(r["date"], text), parse.date_in_text(r["otraFecha"], text)
        if esta != otra:
            if otra:
                upd["date"] = r["otraFecha"]
            upd["fechaOk"], upd["otraFecha"] = True, ""
    if not r.get("official"):
        upd.update({"url": final, "official": True, "nosite": False})
        if parse.is_signup_platform(final):
            upd["signup"] = True

    regulation = r.get("regulation") or (parse.find_regulation(html, final) if html else (final if final.lower().endswith(".pdf") else None))
    if regulation and not r.get("regulation"):
        regulation = resolve_regulation(regulation, found_on=final)
        if regulation:
            upd["regulation"] = regulation
        upd["regResolved"] = upd["regChecked"] = today.isoformat()
    if html:
        img, score = parse.best_image(html, final, r.get("name", ""))
        # el cartel de la web oficial gana si puntúa igual o mejor que el que ya hubiera
        if img and (not r.get("banner") or score >= (r.get("bannerScore") or 0)) and img != r.get("banner"):
            upd["banner"], upd["bannerScore"] = img, score
        if not r.get("route"):
            route = parse.find_route(html, final)
            if route and net.domain(route) == net.domain(final) and parse.find_route_media(html, final)[0] is None:
                route = route_from_site(final) or route     # página «Recorrido»: entrar a por el mapa
            if route:
                upd["route"] = route

    reg_text = ""
    if regulation and (not r.get("price") or not r.get("time")):
        reg_text, _, _ = fetch_text(regulation)

    full = (text + " " + reg_text)[:60000]
    price = r.get("price") or parse.extract_price(full)
    time_ = r.get("time") or parse.extract_time(full)
    km = r.get("km") or parse.extract_km(parse.own_part(text)[:5000] + " · " + reg_text[:5000], r.get("name", ""))

    if (not price or not time_) and full:
        ai = ask_llm(r.get("name", ""), r.get("date", ""), reg_text or text)
        price = price or ai.get("price")
        time_ = time_ or ai.get("time")
        km = km or ai.get("km")
        new_date = ai.get("date")
        if new_date and re.match(r"\d{4}-\d{2}-\d{2}$", str(new_date)) and new_date != r.get("date"):
            try:
                if abs((date.fromisoformat(new_date) - date.fromisoformat(r["date"])).days) <= 60:
                    upd["date"] = new_date
                    upd["note"] = f"Fecha confirmada en la web oficial (antes figuraba el {r['date']})."
            except ValueError:
                pass

    if price and not r.get("price"):
        upd["price"] = price
    if time_ and not r.get("time") and re.match(r"^\d{2}:\d{2}$", time_):
        upd["time"] = time_
    if km and not r.get("km"):
        upd["km"] = km
        tags = parse.tags_from_km(km)
        if tags:
            upd["distances"] = tags
    _fill(upd, r, src)
    return upd


def _fill(upd: dict, r: dict, src: dict | None) -> None:
    """Completa hora, precio y km con lo que digan las fichas de calendario, si la web oficial no lo dijo."""
    if not src:
        return
    if not r.get("time") and not upd.get("time") and src.get("time") and re.match(r"^\d{2}:\d{2}$", src["time"]):
        upd["time"] = src["time"]
    if not r.get("price") and not upd.get("price") and src.get("price"):
        upd["price"] = src["price"]
    if not r.get("km") and not upd.get("km") and src.get("km"):
        upd["km"] = src["km"]
        tags = parse.tags_from_km(src["km"])
        if tags:
            upd["distances"] = tags
