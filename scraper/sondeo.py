"""Prueba de las valoraciones del Worker. Escribe estado/sondeo.json."""
import json
from pathlib import Path
import requests
B = "https://dondeloechan-ia.alexample.workers.dev/valoraciones"
H = {"Origin": "https://alexample.github.io", "Content-Type": "application/json"}
res = {}
r = requests.post(B, headers=H, data=json.dumps({"k": "zz-prueba", "e": 4, "d": "pruebarobot0000001"}), timeout=20); res["voto4"] = [r.status_code, r.text[:200]]
r = requests.post(B, headers=H, data=json.dumps({"k": "zz-prueba", "e": 5, "d": "pruebarobot0000001"}), timeout=20); res["cambia5"] = [r.status_code, r.text[:200]]
r = requests.post(B, headers=H, data=json.dumps({"k": "zz-prueba", "e": 9, "d": "pruebarobot0000001"}), timeout=20); res["invalido"] = [r.status_code, r.text[:120]]
r = requests.post(B, headers={"Origin": "https://malo.example", "Content-Type": "application/json"}, data=json.dumps({"k": "zz-prueba", "e": 1, "d": "pruebarobot0000002"}), timeout=20); res["otro_origen"] = [r.status_code, r.text[:120]]
r = requests.get(B, headers={"Origin": "https://alexample.github.io"}, timeout=20); res["lectura"] = [r.status_code, r.text[:200], r.headers.get("access-control-allow-origin")]
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(res)
