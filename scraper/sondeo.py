"""Sondeo: enlaces a resultados en las carreras del último fin de semana. Escribe estado/sondeo.json."""
import json
import re
from pathlib import Path
from . import enrich, main, net, parse

PAL = re.compile(r"resultad|clasifica|classifica|sailkapen|results|tiempos|temps|ranking|live|directo|crono|diploma", re.I)
db = main.load()
past = [r for r in db["races"] if "2026-10-24" <= r["date"] <= "2026-10-26"]
past.sort(key=lambda r: (not r.get("official"), r["date"]))
res = []
for r in past[:28]:
    pages = ([r["url"]] if r.get("official") and r.get("url") else []) + enrich.source_pages(r)
    item = {"name": r["name"], "date": r["date"], "pages": []}
    for u in pages[:3]:
        html, final, _ = net.get(u)
        if not html or isinstance(html, bytes):
            item["pages"].append({"u": u, "sin": True})
            continue
        s = parse.soup(html)
        links = []
        for a in s.find_all("a", href=True):
            t = a.get_text(" ", strip=True)[:70]
            h = parse.abs_url(parse.page_base(html, final), a["href"])
            if PAL.search(t + " " + h):
                links.append([t, h[:160]])
        txt = parse.own_part(parse.page_text(html))
        item["pages"].append({"u": final, "links": links[:15],
                              "txt": [txt[max(0, m.start() - 60): m.end() + 60] for m in re.finditer(r"resultad|clasificaci|classificaci", txt, re.I)][:4]})
    res.append(item)
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(res))
