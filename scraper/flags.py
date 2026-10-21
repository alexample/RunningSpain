"""Descarga las banderas de las comunidades autónomas (Wikimedia Commons) a docs/flags/.

Uso: python -m scraper.flags   (solo descarga las que falten)
"""
import sys
from pathlib import Path
from urllib.parse import quote

import requests

from .parse import slug

OUT = Path(__file__).resolve().parent.parent / "docs" / "flags"
UA = "RunningSpainBot/1.0 (+https://github.com/alexample/RunningSpain)"

# Comunidad -> nombres posibles del archivo en Commons (se prueba en orden)
FLAGS = {
    "Andalucía": ["Flag of Andalucía.svg"],
    "Aragón": ["Flag of Aragon.svg"],
    "Asturias": ["Flag of Asturias.svg"],
    "Islas Baleares": ["Flag of the Balearic Islands.svg"],
    "Canarias": ["Flag of the Canary Islands.svg"],
    "Cantabria": ["Flag of Cantabria.svg", "Flag of Cantabria (Official).svg"],
    "Castilla y León": ["Flag of Castile and León.svg", "Flag of Castilla y León.svg"],
    "Castilla-La Mancha": ["Flag of Castile-La Mancha.svg", "Flag of Castilla-La Mancha.svg"],
    "Cataluña": ["Flag of Catalonia.svg"],
    "Comunidad Valenciana": ["Flag of the Valencian Community (2x3).svg", "Flag of the Valencian Community.svg"],
    "Extremadura": ["Flag of Extremadura, Spain (with coat of arms).svg", "Flag of Extremadura (with coat of arms).svg",
                    "Flag of Extremadura.svg"],
    "Galicia": ["Flag of Galicia.svg"],
    "Comunidad de Madrid": ["Flag of the Community of Madrid.svg"],
    "Región de Murcia": ["Flag of the Region of Murcia.svg", "Flag of Murcia.svg"],
    "Navarra": ["Bandera de Navarra.svg", "Flag of Navarre.svg"],
    "País Vasco": ["Flag of the Basque Country.svg"],
    "La Rioja": ["Flag of La Rioja (with coat of arms).svg", "Flag of La Rioja.svg"],
    "Ceuta": ["Flag of Ceuta.svg"],
    "Melilla": ["Flag of Melilla.svg"],
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    failed = []
    for region, names in FLAGS.items():
        dest = OUT / f"{slug(region)}.png"
        if dest.exists():
            continue
        for name in names:
            url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(name.replace(" ", "_")) + "?width=96"
            try:
                r = s.get(url, timeout=30)
            except requests.RequestException as e:
                print(f"  {name}: {e}")
                continue
            if r.ok and r.headers.get("content-type", "").startswith("image/png"):
                dest.write_bytes(r.content)
                print(f"OK  {region} <- {name}")
                break
            print(f"  {name}: HTTP {r.status_code} {r.headers.get('content-type')}")
        else:
            failed.append(region)
            print(f"FALTA {region}")
    print(f"{len(FLAGS) - len(failed)}/{len(FLAGS)} banderas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
