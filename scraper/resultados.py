"""Resultados de las carreras recién disputadas.

Durante los RESULTADOS_DIAS días siguientes a la carrera, el robot mira la web oficial y las fichas de las
plataformas (Sportmaniacs, Elitechip, Cruzando la Meta…) por si ya hay clasificaciones. Si al acabar ese plazo
no las ha encontrado, y solo entonces, pregunta a la IA, que únicamente puede elegir uno de los enlaces vistos.
"""
import re
from datetime import date, timedelta

import requests

from . import config, enrich, ia, net, parse

_PAL = re.compile(r"resultad|clasifica|classifica|sailkapen|results?\b|rankings?|tiempos|temps|diploma", re.I)
_FUERTE = re.compile(r"\b(ver|consulta|descarga|view|veure)\b.*\b(resultad|clasifica|classifica|results|rankings?)|"
                     r"^\s*(resultados|clasificaci[oó]n(es)?|classificaci[oó](ns)?|results|rankings?|sailkapenak?)\s*(20\d\d)?\s*$", re.I)
# enlaces genéricos de las plataformas o de la web (listados de todas las carreras, directo, servicios…)
_GENERICO = re.compile(r"/(results|resultados|clasificaciones|classificacions)/?$|zwshow=results$|carreras/finalizadas|carreras-live|"
                       r"/informacion|#servicio|pendiente|pending|live-?timing|/live/?$|inscrip|inscription|facebook|instagram|twitter|youtube", re.I)
_PLATAFORMA = re.compile(r"/rankings?\b|compsec=clas|rankings\.|/clasificaciones/v2/|/clasificacion/|/classificacio|/results/\d|"
                         r"resultados\.php|clasificaciones\.php|/resultats", re.I)


def _palabras(name: str) -> set[str]:
    return parse._name_words(name)


def candidatos(html: str, final: str, r: dict) -> list[tuple[int, str, str]]:
    """Enlaces a resultados en una página, con su puntuación (más alta = más seguro que son de esta carrera)."""
    base = parse.page_base(html, final)
    s = parse.soup(html)
    year = r["date"][:4]
    words = _palabras(r["name"])
    out = {}
    for a in s.find_all("a", href=True):
        t = a.get_text(" ", strip=True)[:90]
        h = parse.abs_url(base, a["href"]).split("#")[0] if "#results" not in a["href"] else parse.abs_url(base, a["href"])
        if not h.startswith("http") or not _PAL.search(t + " " + h) or _GENERICO.search(h) or _GENERICO.search(t):
            continue
        score = 1
        if _FUERTE.search(t):
            score += 1
        if year in h or year in t or (words and words & parse._name_words(t + " " + h.replace("-", " ").replace("_", " "))):
            score += 2
        if _PLATAFORMA.search(h) or re.search(r"\.(pdf|xlsx?)(\?|$)", h, re.I):
            score += 2
        if net.domain(h) == net.domain(final) and _PAL.search(h):
            score += 1
        out[h] = max(out.get(h, (0, ""))[0], score), t
    return sorted(((sc, h, t) for h, (sc, t) in out.items()), reverse=True)


def sportmaniacs(html: str, final: str) -> str | None:
    """En Sportmaniacs, la ficha de la carrera enseña «Ver clasificaciones» cuando ya están (antes, «Pendiente»)."""
    if "sportmaniacs.com" not in final:
        return None
    if re.search(r"ver clasificaciones|view results|/rankings\b", html, re.I):
        m = re.search(r"https://sportmaniacs\.com/(es|en)/races/([a-z0-9-]+)", html)
        if m:
            return f"https://sportmaniacs.com/es/races/{m.group(2)}#results"
    return None


def buscar(r: dict) -> tuple[str | None, list[dict]]:
    """(enlace seguro a los resultados o None, enlaces candidatos para la IA)."""
    pages = ([r["url"]] if r.get("official") and r.get("url") else []) + enrich.source_pages(r)
    todos = []
    for u in pages[:4]:
        html, final, _ = net.get(u)
        if not html or isinstance(html, bytes):
            continue
        sm = sportmaniacs(html, final)
        if sm:
            return sm, []
        for sc, h, t in candidatos(html, final, r):
            if sc >= 4:
                return h, []
            todos.append({"u": h, "t": t, "sc": sc})
    todos.sort(key=lambda x: -x["sc"])
    return None, todos[:30]


def _ia(r: dict, cands: list[dict], tok: str) -> str | None:
    if not cands or not tok:
        return None
    try:
        resp = requests.post(ia.ENDPOINT, headers={"Authorization": f"Bearer {tok}"}, timeout=90,
                             json={"modo": "resultados", "nombre": r["name"], "fecha": r["date"],
                                   "lugar": f"{r.get('city', '')} ({r.get('region', '')})",
                                   "enlaces": [{"u": c["u"], "t": c["t"]} for c in cands]})
        i = resp.json().get("resultados") if resp.status_code == 200 else None
    except Exception:
        return None
    return cands[i]["u"] if isinstance(i, int) and 0 <= i < len(cands) else None


def pasada(db: dict, today: date, changes: dict, log) -> int:
    desde = (today - timedelta(days=config.RESULTADOS_DIAS)).isoformat()
    todo = [r for r in db["races"] if desde <= r["date"] <= today.isoformat() and not r.get("resultados")]
    log(f"Resultados: {len(todo)} carreras disputadas en los últimos {config.RESULTADOS_DIAS} días sin resultados todavía")
    hallados, por_ia, tok = 0, 0, None
    for r in todo:
        url, cands = buscar(r)
        r["resultadosAt"] = today.isoformat()
        ultimo = r["date"] == desde      # último día del plazo: si el robot no los ha visto, último recurso
        if not url and ultimo and config.IA_ACTIVA and cands and por_ia < config.RESULTADOS_IA_MAX:
            tok = tok or ia._token()
            url = _ia(r, cands, tok)
            por_ia += 1
            if url:
                r["ia"] = sorted(set((r.get("ia") or []) + ["resultados"]))
        if url:
            r["resultados"] = url
            hallados += 1
            changes["updated"].setdefault(r["id"], []).append("resultados")
            log(f"  🏁 {r['name']} ({r['date']}): {url}")
    log(f"Resultados encontrados: {hallados} (con IA: {sum(1 for r in todo if 'resultados' in (r.get('ia') or []))}, preguntas a la IA: {por_ia})")
    return hallados
