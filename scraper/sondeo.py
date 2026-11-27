"""Sondeo: prueba del contador de visitas del worker."""
import json
from pathlib import Path
import requests
U = "https://dondeloechan-ia.alexample.workers.dev/visitas"
res = {"get": requests.get(U, timeout=20).text[:200]}
r = requests.post(U, json={"ks": ["zz-prueba-visitas"]}, headers={"Origin": "https://alexample.github.io"}, timeout=20)
res["post"] = [r.status_code, r.text[:200]]
r = requests.post(U, json={"ks": ["zz-prueba-visitas"]}, headers={"Origin": "https://malo.example"}, timeout=20)
res["post_origen_malo"] = [r.status_code, r.text[:200]]
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(res)
