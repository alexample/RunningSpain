"""Imagen de vista previa de cada carrera (docs/c/img/<código>.jpg, 1200×630) para X, WhatsApp, Telegram…

X no muestra la miniatura si el cartel está en una web que no le deja descargarlo (robots.txt, antihotlinking,
imagen enorme o lenta). Por eso el robot baja el cartel una vez, compone una tarjeta con él y los datos de la
carrera, y la sirve desde la propia web de RunningSpain, que X siempre puede leer.
"""
import hashlib
import io
import json
import re
import textwrap
from datetime import date, timedelta
from pathlib import Path

from . import net

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
except ImportError:          # sin Pillow, las páginas siguen usando el cartel original
    Image = None

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "c" / "img"
INDICE = OUT / "indice.json"
FUENTES = ROOT / "estado" / "fuentes"
W, H = 1200, 630
TINTA, FONDO, ACENTO, GRIS = (22, 25, 29), (251, 251, 248), (224, 70, 28), (93, 102, 112)
K_COLOR = {"42K": (224, 70, 28), "21K": (31, 95, 191), "10K": (19, 128, 90)}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_GF = "https://github.com/google/fonts/raw/main/ofl/"
_FUENTES = {"titulo": ("sairacondensed/SairaCondensed-Bold.ttf", ["DejaVuSansCondensed-Bold.ttf", "LiberationSansNarrow-Bold.ttf", "Poppins-Bold.ttf"]),
            "texto": ("figtree/Figtree%5Bwght%5D.ttf", ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Poppins-Regular.ttf"])}
_cache_fuentes: dict = {}


def _fuente(tipo: str, size: int):
    clave = (tipo, size)
    if clave in _cache_fuentes:
        return _cache_fuentes[clave]
    remoto, locales = _FUENTES[tipo]
    f = FUENTES / remoto.rsplit("/", 1)[-1].replace("%5B", "[").replace("%5D", "]")
    if not f.exists():   # las fuentes de la web (Saira Condensed y Figtree, licencia OFL) se bajan una vez
        try:
            import requests
            r = requests.get(_GF + remoto, timeout=20)
            if r.status_code == 200 and len(r.content) > 10000:
                FUENTES.mkdir(parents=True, exist_ok=True)
                f.write_bytes(r.content)
        except Exception:
            pass
    cands = [f] + [p for n in locales for p in Path("/usr/share/fonts").rglob(n)]
    font = None
    for c in cands:
        try:
            font = ImageFont.truetype(str(c), size)
            break
        except Exception:
            continue
    font = font or ImageFont.load_default(size)
    _cache_fuentes[clave] = font
    return font


def _poster(url: str):
    if not url:
        return None
    data, _, ctype = net.get(url, binary=True)
    if not data or len(data) > 15_000_000 or (ctype and "image" not in ctype and "octet" not in ctype):
        return None
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
        return im if min(im.size) >= 120 else None
    except Exception:
        return None


def _wrap(draw, txt, font, ancho, max_lineas):
    palabras, lineas, cur = txt.split(), [], ""
    for p in palabras:
        prueba = (cur + " " + p).strip()
        if draw.textlength(prueba, font=font) <= ancho:
            cur = prueba
        else:
            if cur:
                lineas.append(cur)
            cur = p
    if cur:
        lineas.append(cur)
    if len(lineas) > max_lineas:
        lineas = lineas[:max_lineas]
        while lineas[-1] and draw.textlength(lineas[-1] + "…", font=font) > ancho:
            lineas[-1] = lineas[-1][:-1]
        lineas[-1] = lineas[-1].rstrip() + "…"
    return lineas


def _etiqueta(r: dict) -> str:
    d = (r.get("distances") or [""])[0]
    return d or "RUN"


def componer(r: dict, poster) -> "Image.Image":
    img = Image.new("RGB", (W, H), FONDO)
    draw = ImageDraw.Draw(img)
    izq = 470
    if poster:   # cartel entero a la izquierda, sobre una versión difuminada de sí mismo
        fondo = ImageOps.fit(poster, (izq, H)).filter(ImageFilter.GaussianBlur(18))
        fondo = Image.blend(fondo, Image.new("RGB", fondo.size, TINTA), 0.35)
        img.paste(fondo, (0, 0))
        p = poster.copy()
        p.thumbnail((izq - 40, H - 40))
        img.paste(p, ((izq - p.width) // 2, (H - p.height) // 2))
    else:        # sin cartel: un dorsal con la distancia, como en la web
        col = K_COLOR.get(_etiqueta(r), (107, 91, 181))
        draw.rectangle([0, 0, izq, H], fill=col)
        draw.rounded_rectangle([40, 90, izq - 40, H - 90], radius=18, fill=FONDO)
        for x in (62, izq - 62):
            for y in (112, H - 112):
                draw.ellipse([x - 7, y - 7, x + 7, y + 7], fill=(200, 204, 208))
        et = _etiqueta(r)
        size = 190
        f = _fuente("titulo", size)
        while size > 60 and draw.textlength(et, font=f) > izq - 140:
            size -= 10
            f = _fuente("titulo", size)
        draw.text((izq // 2, H // 2), et, font=f, fill=TINTA, anchor="mm")
    x, ancho = izq + 50, W - izq - 90
    draw.rectangle([izq, 0, izq + 8, H], fill=ACENTO)
    draw.text((x, 58), "RUNNINGSPAIN", font=_fuente("titulo", 30), fill=ACENTO)
    ft = _fuente("titulo", 64)
    lineas = _wrap(draw, r["name"], ft, ancho, 3)
    y = 110
    for ln in lineas:
        draw.text((x, y), ln, font=ft, fill=TINTA)
        y += 72
    y += 18
    yy, m, d = map(int, r["date"].split("-"))
    cuando = f"{DIAS[date(yy, m, d).weekday()]} {d} de {MESES[m - 1]}" + (f" · {r['time']} h" if r.get("time") else "")
    lugar = r.get("city") or ""
    if r.get("region") and r["region"] != lugar:
        lugar = f"{lugar} · {r['region']}" if lugar else r["region"]
    dist = r.get("km") or " · ".join(r.get("distances") or [])
    fx = _fuente("texto", 34)
    for icono, txt in (("📅", cuando), ("📍", lugar), ("📏", dist)):
        if not txt:
            continue
        for ln in _wrap(draw, txt, fx, ancho, 2):
            draw.text((x, y), ln, font=fx, fill=TINTA if icono == "📅" else GRIS)
            y += 44
        y += 6
    draw.text((x, H - 70), "Calendario de carreras populares de España", font=_fuente("texto", 24), fill=GRIS)
    return img


def _firma(r: dict) -> str:
    campos = [r.get(k) or "" for k in ("name", "date", "time", "city", "region", "km", "banner")] + [",".join(r.get("distances") or []), "v1"]
    return hashlib.sha1("|".join(campos).encode()).hexdigest()[:12]


def asegurar(races: list[dict], today: date, log=print, short_code=None, max_bajadas: int = 120) -> int:
    """Crea o actualiza la tarjeta de las carreras próximas (45 días) y de las recién añadidas; borra las que sobran."""
    if Image is None:
        log("Tarjetas: falta Pillow")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        indice = json.loads(INDICE.read_text(encoding="utf-8"))
    except Exception:
        indice = {}
    hasta = (today + timedelta(days=45)).isoformat()
    recien = (today - timedelta(days=3)).isoformat()
    quiero = [r for r in races if today.isoformat() <= r["date"] and (r["date"] <= hasta or (r.get("addedAt") or "") >= recien)]
    quiero.sort(key=lambda r: ((r.get("addedAt") or "") < recien, r["date"]))   # primero las que se van a tuitear
    hechas = bajadas = 0
    vivos = set()
    for r in quiero:
        code = short_code(r["id"])
        vivos.add(code)
        firma = _firma(r)
        if indice.get(code) == firma and (OUT / f"{code}.jpg").exists():
            continue
        if bajadas >= max_bajadas:
            continue
        poster = _poster(r.get("banner")) if r.get("banner") else None
        bajadas += 1
        try:
            componer(r, poster).save(OUT / f"{code}.jpg", "JPEG", quality=80, optimize=True, progressive=True)
        except Exception as e:
            log(f"  tarjeta {r['id']}: {e}")
            continue
        indice[code] = firma
        hechas += 1
    for f in OUT.glob("*.jpg"):
        if f.stem not in vivos:
            f.unlink()
            indice.pop(f.stem, None)
    INDICE.write_text(json.dumps(indice, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    log(f"Tarjetas para compartir: {hechas} nuevas o cambiadas · {len(vivos)} en total")
    return hechas


def url_relativa(code: str) -> str | None:
    return f"img/{code}.jpg" if (OUT / f"{code}.jpg").exists() else None
