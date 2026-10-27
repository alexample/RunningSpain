"""Sondeo: fechas de running.life (en/event vs es/carrera), km en páginas y carteles. Escribe estado/sondeo.json."""
import json
import re
from pathlib import Path
from . import net, parse

res = {"fechas": {}, "km": {}, "img": {}}
FECHAS = [
    "https://running.life/en/event/media-maraton-de-cordoba",
    "https://running.life/en/event/cursa-popular-vila-de-sant-boi",
    "https://running.life/en/event/mitja-marato-internacional-vila-de-santa-pola",
    "https://running.life/es/carrera/mitja-marato-internacional-vila-de-santa-pola",
    "https://running.life/en/event/media-maraton-de-guadalajara",
    "https://running.life/es/carrera/media-maraton-de-guadalajara",
    "https://running.life/en/event/san-pintena",
    "https://running.life/en/event/10k-de-sarinena",
]
for u in FECHAS:
    html, final, _ = net.get(u)
    if not html:
        res["fechas"][u] = "sin acceso"
        continue
    evs = parse.jsonld_events(html)
    txt = parse.page_text(html)
    res["fechas"][u] = {
        "final": final,
        "ld": [{k: e.get(k) for k in ("name", "startDate", "endDate", "eventStatus", "url")} for e in evs][:4],
        "trozos": [txt[max(0, m.start() - 80): m.end() + 80] for m in re.finditer(r"20(26|27)", txt)][:8],
        "estim": [txt[max(0, m.start() - 80): m.end() + 80] for m in re.finditer(r"estimat|tentativ|to be confirmed|por confirmar|pendiente|previous|last edition|edición anterior", txt, re.I)][:5],
        "inicio": txt[:1500],
    }

KM = [
    "https://running.life/en/event/cursa-antiracista-solsona",
    "https://running.life/en/event/escaldada",
    "https://running.life/es/carrera/desafio-bomberos-san-sebastian-de-los-reyes",
    "https://www.runnink.com/evento/media-maraton-y-10k-rural-villanueva-de-la-torre",
    "https://www.udat.es/",
    "https://www.derbidelasaficiones.com/",
    "https://inscripcion.kirolprobak.com/inscripcion/10k-halloweenrun-zorroza-bilbao",
]
for u in KM:
    html, final, _ = net.get(u)
    if not html or isinstance(html, bytes):
        res["km"][u] = "sin acceso"
        continue
    txt = parse.page_text(html)
    res["km"][u] = {"len": len(txt), "hits": [[m.start(), txt[max(0, m.start() - 70): m.end() + 30]] for m in parse.KM_RE.finditer(txt)][:25]}

IMG = [
    "https://running.life/en/event/wolf-race-perdiguera",
    "https://running.life/en/event/cursa-de-les-caves",
    "https://www.carreraspopulares.com/carrera/cursa-de-les-caves",
    "https://www.lineadesalida.net/carreras/iv-carrera-cofrade-cuatro-millas",
    "https://eltast.lamitja.cat/",
    "https://www.laconquistadelaalmendra.com/",
    "https://runnersporthuelva.com/21k/",
    "https://sportmaniacs.com/es/races/21k-ciudad-de-huelva-26",
    "https://cursasantgalderic.blogspot.com/",
    "https://running.life/en/search?q=daganzo",
    "https://running.life/es/buscar?q=daganzo",
]
for u in IMG:
    html, final, _ = net.get(u)
    if not html or isinstance(html, bytes):
        res["img"][u] = "sin acceso"
        continue
    s = parse.soup(html)
    imgs = []
    for im in s.find_all("img"):
        src = im.get("data-src") or im.get("data-lazy-src") or im.get("src") or ""
        imgs.append([src[:160], (im.get("alt") or "")[:60], im.get("width"), im.get("height"), " ".join(im.get("class") or [])[:40]])
    metas = {p: (s.find("meta", attrs={"property": p}) or {}).get("content") if s.find("meta", attrs={"property": p}) else None for p in ("og:image", "twitter:image")}
    res["img"][u] = {"final": final, "best": parse.best_image(html, final), "metas": metas,
                     "ld_img": [e.get("image") for e in parse.jsonld_events(html)][:3], "imgs": imgs[:30],
                     "bg": re.findall(r"background(?:-image)?\s*:\s*url\(([^)]+)\)", html)[:8]}

Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
