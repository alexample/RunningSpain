"""Diagnóstico del descubrimiento de carreras. Escribe estado/diagnostico.json.

Uso: python -m scraper.diagnostico
"""
import json
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from . import config, main, net, parse, sources

OUT = Path(__file__).resolve().parent.parent / "estado" / "diagnostico.json"


def pagination_hints(html: str) -> dict:
    s = parse.soup(html)
    hrefs = [a["href"] for a in s.find_all("a", href=True)]
    pag = sorted({h for h in hrefs if re.search(r"[?&](page|p|pagina|offset)=\d+|/page/\d+", h)})[:15]
    more = sorted({a.get_text(" ", strip=True)[:40] for a in s.find_all(["a", "button"])
                   if re.search(r"(ver|cargar|mostrar) m[aá]s|siguiente|next|load more", a.get_text(" ", strip=True), re.I)})[:10]
    nxt = [l.get("href") for l in s.find_all("link", rel=True) if "next" in (l.get("rel") or [])]
    return {"enlaces_pagina": pag, "botones_mas": more, "rel_next": nxt,
            "scripts_api": sorted(set(re.findall(r"https?://[^\"' ]*api[^\"' ]{0,80}", html)))[:8]}


def main_diag() -> None:
    today = date.today()
    db = main.load()
    known = {r.get("source") for r in db["races"]}
    rep = {"hoy": today.isoformat(), "carreras_en_datos": len(db["races"]),
           "max_fecha_en_datos": max(r["date"] for r in db["races"]), "sportplan": [], "runninglife": []}

    # 1) Páginas de región de sportplan
    for slug in config.SPORTPLAN_REGIONS[:55]:
        page = config.SPORTPLAN_REGION_URL.format(slug=slug)
        html, final, _ = net.get(page)
        if not html:
            rep["sportplan"].append({"slug": slug, "error": True})
            continue
        links = sources._links(html, final, sources.SP_EVENT)
        dates = sorted(filter(None, (parse.date_from_url(u) for u, _ in links)))
        item = {"slug": slug, "fichas": len(links), "con_fecha": len(dates),
                "primera": dates[0] if dates else None, "ultima": dates[-1] if dates else None,
                "nuevas_no_conocidas": sum(1 for u, _ in links if u not in known),
                "jsonld": len(parse.jsonld_events(html)), "bytes": len(html)}
        if slug in ("madrid", "barcelona", "valencia"):
            item["paginacion"] = pagination_hints(html)
        rep["sportplan"].append(item)

    # 2) Listas de running.life
    for base in config.RUNNINGLIFE_LISTS:
        info = {"lista": base, "paginas": []}
        for p in range(1, 6):
            url = base + (f"?page={p}" if p > 1 else "")
            html, final, _ = net.get(url)
            if not html:
                info["paginas"].append({"p": p, "error": True})
                break
            links = sources._links(html, final, sources.RL_EVENT)
            evs = [parse.event_fields(e) for e in parse.jsonld_events(html)]
            ds = sorted(filter(None, (e["date"] for e in evs)))
            info["paginas"].append({"p": p, "enlaces": len(links), "jsonld": len(evs),
                                    "primera": ds[0] if ds else None, "ultima": ds[-1] if ds else None,
                                    "nuevas_no_conocidas": sum(1 for u, _ in links if u not in known),
                                    "ejemplo": links[:2]})
            if p == 1:
                info["paginacion"] = pagination_hints(html)
        rep["runninglife"].append(info)

    # 3) Qué pasa con los candidatos que el robot abriría hoy
    cands = sources.list_sportplan(today, lambda m: None) + sources.list_runninglife(today, lambda m: None)
    new = [c for c in cands if c["source_url"] not in known]
    rep["candidatos_total"] = len(cands)
    rep["candidatos_nuevos"] = len(new)
    reasons, samples = Counter(), {}
    for c in sorted(new, key=lambda c: c.get("date") or "9999")[:80]:
        html, final, _ = net.get(c["source_url"])
        if not html:
            why = "sin_acceso"
        else:
            evs = parse.jsonld_events(html)
            f = parse.event_fields(evs[0]) if evs else {}
            name = f.get("name") or c.get("name_hint") or ""
            d = f.get("date") or c.get("date")
            if not name:
                why = "sin_nombre"
            elif not d:
                why = "sin_fecha"
            elif not sources._in_window(d, today):
                why = "fuera_de_ventana"
            elif not parse.is_road(name):
                why = "no_asfalto"
            else:
                r = {"name": name, "date": d, "city": f.get("city", "")}
                why = "duplicada" if any(main.same_race(x, r) for x in db["races"]) else "seria_nueva"
        reasons[why] += 1
        samples.setdefault(why, [])
        if len(samples[why]) < 6:
            samples[why].append({"url": c["source_url"], "fecha": c.get("date"), "nombre": c.get("name_hint", "")[:70]})
    rep["motivos"] = dict(reasons)
    rep["ejemplos"] = samples
    rep["peticiones"] = net.stats
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("candidatos_total", "candidatos_nuevos", "motivos")}, ensure_ascii=False))


if __name__ == "__main__":
    main_diag()
