"""Sondeo: prueba de la lectura con IA del worker (sin guardar nada en los datos). Escribe estado/sondeo.json."""
import json
from datetime import date
from pathlib import Path
import requests
from . import ia, main

res = {}
r = requests.post(ia.ENDPOINT, json={}, timeout=30)
res["sin_token"] = [r.status_code, r.text[:120]]
r = requests.post(ia.ENDPOINT, json={}, headers={"Authorization": "Bearer a.b.c"}, timeout=30)
res["token_falso"] = [r.status_code, r.text[:120]]
tok = ia._token()
res["token_github"] = bool(tok)
db = main.load()
cands = ia.candidatas(db, date.today())
res["candidatas"] = len(cands)
res["pruebas"] = []
for c in cands[:3]:
    mat = ia._material(c)
    faltan = [ia.FALTAN[k] for k in ia.FALTAN if not c.get(k)]
    resp = requests.post(ia.ENDPOINT, headers={"Authorization": f"Bearer {tok}"}, timeout=90,
                         json={"nombre": c["name"], "fecha": c["date"], "lugar": c.get("city", ""), "faltan": faltan, **mat})
    out = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200]
    copia = dict(c)
    puesto = ia._aplica(copia, out if isinstance(out, dict) else {}, mat, date.today()) if resp.status_code == 200 else []
    res["pruebas"].append({"carrera": c["name"], "fecha": c["date"], "faltan": faltan, "status": resp.status_code, "respuesta": out,
                           "aplicaria": {k: copia.get(k) for k in puesto}, "n_img": len(mat["imagenes"]), "n_links": len(mat["enlaces"]),
                           "len_texto": len(mat["texto"])})
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1)[:3000])
