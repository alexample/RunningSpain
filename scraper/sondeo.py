"""Sondeo: baja las tipografías de la web (Google Fonts, licencia OFL) para servirlas desde la propia web."""
import re
from pathlib import Path
import requests

CSS = "https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@600;700;800&family=Figtree:wght@400;500;600&display=swap"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
out = Path("docs/fuentes")
out.mkdir(parents=True, exist_ok=True)
css = requests.get(CSS, headers=UA, timeout=30).text
n = 0
def baja(m):
    global n
    url = m.group(1)
    n += 1
    name = f"f{n}.woff2"
    (out / name).write_bytes(requests.get(url, headers=UA, timeout=30).content)
    return f"url({name})"
css = re.sub(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", baja, css)
(out / "fuentes.css").write_text("/* Saira Condensed y Figtree (SIL Open Font License), servidas desde la propia web */\n" + css, encoding="utf-8")
print(n, "archivos")
