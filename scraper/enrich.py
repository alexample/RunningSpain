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
    complete = r.get("official") and r.get("price") and r.get("regulation") and r.get("banner") and r.get("km")
    if complete:
        return False
    last = r.get("checkedAt")
    if last:
        try:
            if (today - date.fromisoformat(last[:10])).days < config.RECHECK_DAYS:
                return False
        except ValueError:
            pass
    return True


def enrich(r: dict, today: date) -> dict:
    """Devuelve los campos nuevos que se han podido confirmar para la carrera r."""
    upd = {"checkedAt": today.isoformat()}
    url = r.get("url") if r.get("official") else None
    if not url:
        guess = r.get("official_guess")
        if not guess and r.get("source"):
            html, final, _ = net.get(r["source"])
            if html:
                ev = parse.jsonld_events(html)
                cands = parse.event_fields(ev[0])["official_candidates"] if ev else []
                guess = (cands or [None])[0] or parse.guess_official(html, final)
        url = guess
    if not url:
        upd["nosite"] = True
        return upd

    text, html, final = fetch_text(url)
    if not text and not html:
        return upd
    if not r.get("official"):
        upd.update({"url": final, "official": True, "nosite": False})
        if parse.is_signup_platform(final):
            upd["signup"] = True

    regulation = r.get("regulation") or (parse.find_regulation(html, final) if html else (final if final.lower().endswith(".pdf") else None))
    if regulation and not r.get("regulation"):
        upd["regulation"] = regulation
    if html:
        img, score = parse.best_image(html, final)
        # el cartel de la web oficial gana si puntúa igual o mejor que el que ya hubiera
        if img and (not r.get("banner") or score >= (r.get("bannerScore") or 0)) and img != r.get("banner"):
            upd["banner"], upd["bannerScore"] = img, score
        if not r.get("route"):
            route = parse.find_route(html, final)
            if route:
                upd["route"] = route

    reg_text = ""
    if regulation and (not r.get("price") or not r.get("time")):
        reg_text, _, _ = fetch_text(regulation)

    full = (text + " " + reg_text)[:60000]
    price = r.get("price") or parse.extract_price(full)
    time_ = r.get("time") or parse.extract_time(full)
    km = r.get("km") or parse.extract_km(text[:5000] + " " + reg_text[:5000])

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
    return upd
