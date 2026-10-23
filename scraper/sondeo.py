"""Sondeo: ¿funciona el acortador desde GitHub? Escribe estado/sondeo.json."""
import json
from pathlib import Path
from . import shorten
u = "https://alexample.github.io/RunningSpain/c/1tjcvbo.html"
res = {"is.gd/tinyurl": shorten.shorten(u)}
Path("estado").mkdir(exist_ok=True)
Path("estado/sondeo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(res)
