"""Publica en X cada carrera nueva que encuentra el robot y los cambios importantes de las próximas
(inscripciones abiertas, dorsales agotados, cambio de fecha). El tuit empieza diciendo el motivo.

Uso:  python -m scraper.xpost            (publica, si hay claves)
      python -m scraper.xpost --prueba   (solo muestra los textos)

Dos formas (secretos de GitHub):
  - MACRODROID_WEBHOOK: URL del disparador Webhook de MacroDroid. Cada carrera se envía al móvil
    en la variable "tweet" (más "carrera" y "enlace") y la macro abre X con el texto.
  - X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET: publica directamente con la API de X (de pago).
Lleva la cuenta de lo publicado en estado/x.json para no repetir nunca.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from . import config, share, shorten

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data" / "carreras.json"
STATE = ROOT / "estado" / "x.json"
URL = "https://api.x.com/2/tweets"
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
REGION_TAG = {
    "Andalucía": "Andalucía", "Aragón": "Aragón", "Asturias": "Asturias", "Islas Baleares": "Baleares",
    "Canarias": "Canarias", "Cantabria": "Cantabria", "Castilla y León": "CastillaYLeón",
    "Castilla-La Mancha": "CastillaLaMancha", "Cataluña": "Catalunya", "Comunidad Valenciana": "ComunitatValenciana",
    "Extremadura": "Extremadura", "Galicia": "Galicia", "Comunidad de Madrid": "Madrid",
    "Región de Murcia": "Murcia", "Navarra": "Navarra", "País Vasco": "Euskadi", "La Rioja": "LaRioja",
    "Ceuta": "Ceuta", "Melilla": "Melilla",
}


MOTIVOS = {"nueva": "🏃 Nueva carrera", "abierta": "✅ Inscripciones abiertas", "agotada": "🚫 Dorsales agotados",
           "fecha": "📆 Cambio de fecha"}


def x_len(text: str) -> int:
    """Longitud según X: casi todo cuenta 1, emojis y CJK cuentan 2, un enlace cuenta 23."""
    n = 0
    for word in text.split(" "):
        if word.startswith("http"):
            n += 23 + 1
            continue
        for ch in word:
            n += 2 if (ord(ch) > 0x2FFF or unicodedata.category(ch) == "So") else 1
        n += 1
    return n - 1


def compose(r: dict, con_enlace: bool | None = None) -> str:
    y, m, d = map(int, r["date"].split("-"))
    dt = date(y, m, d)
    when = f"{DAYS[dt.weekday()]} {d} de {MONTHS[m - 1]}" + (f" · {r['time']} h" if r.get("time") else "")
    place = r.get("city") or ""
    if r.get("region") and r["region"] != place:
        place = f"{place} ({r['region']})" if place else r["region"]
    dist = r.get("km") or " · ".join(r.get("distances") or [])
    motivo = r.get("_motivo", "nueva")
    lines = [f"{MOTIVOS[motivo]}: {r['name']}", f"📅 {when}"]
    if motivo == "fecha" and r.get("_antes"):
        ya, ma, da = map(int, r["_antes"].split("-"))
        lines.append(f"↩️ Antes: {DAYS[date(ya, ma, da).weekday()]} {da} de {MONTHS[ma - 1]}")
    if place:
        lines.append(f"📍 {place}")
    if dist:
        lines.append(f"📏 {dist}")
    if r.get("price"):
        lines.append(f"💶 {r['price']}")
    tags = "#running #carreras" + (f" #{REGION_TAG[r['region']]}" if r.get("region") in REGION_TAG else "")
    if con_enlace is None:
        con_enlace = config.X_CON_ENLACE
    link = shorten.load().get(r["id"]) or share.share_url(r)   # enlace acortado a la ficha (o el largo si aún no hay)
    tail = [link] if con_enlace else []
    tail.append(tags)
    text = "\n".join(lines + [""] + tail)
    while x_len(text) > 280 and len(lines[0]) > 30:   # recorta el nombre si no cabe
        lines[0] = lines[0].rstrip("…")[:-1].rstrip() + "…"
        text = "\n".join(lines + [""] + tail)
    return text


def _pct(s: str) -> str:
    return quote(s, safe="~-._")


def oauth_header(method: str, url: str, keys: dict, extra: dict | None = None,
                 nonce: str | None = None, ts: str | None = None) -> str:
    """Cabecera OAuth 1.0a. `extra` son parámetros de URL/formulario (el cuerpo JSON no entra en la firma)."""
    params = {
        "oauth_consumer_key": keys["api_key"],
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": ts or str(int(time.time())),
        "oauth_token": keys["token"],
        "oauth_version": "1.0",
    }
    signed = {**params, **(extra or {})}
    base = "&".join([method, _pct(url), _pct("&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(signed.items())))])
    signing_key = f"{_pct(keys['api_secret'])}&{_pct(keys['token_secret'])}"
    params["oauth_signature"] = base64.b64encode(hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(params.items()))


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"publicadas": {}}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def avisos(races: list, st: dict, today: date) -> list:
    """Cambios importantes de carreras próximas (60 días) detectados en los últimos 3 días, sin tuitear aún."""
    hecho = st.setdefault("avisos", {})
    desde = (today - timedelta(days=3)).isoformat()
    hasta = (today + timedelta(days=60)).isoformat()
    out = []
    for r in races:
        c = r.get("cambio") or {}
        if not (today.isoformat() <= r["date"] <= hasta) or (c.get("t") or "")[:10] < desde or "nueva" in c.get("c", []):
            continue
        motivo, antes = None, None
        if "inscripcion" in c.get("c", []):
            if r.get("inscripcion") == "abierta" and c.get("inscAntes") in ("proximamente", "cerrada"):
                motivo = "abierta"
            elif r.get("inscripcion") == "agotada" and c.get("inscAntes") == "abierta":
                motivo = "agotada"
        if not motivo and "date" in c.get("c", []) and c.get("fechaAntes") and c["fechaAntes"] != r["date"]:
            motivo, antes = "fecha", c["fechaAntes"]
        if not motivo:
            continue
        clave = f"{r['id']}:{motivo}:{r['date'] if motivo == 'fecha' else r.get('inscripcion')}"
        if clave in hecho:
            continue
        out.append({**r, "_motivo": motivo, "_antes": antes, "_clave": clave})
    return sorted(out, key=lambda r: (r["date"], r.get("time") or "99"))


def pending(races: list, st: dict, today: date) -> list:
    done = st["publicadas"]
    todo = [r for r in races
            if r.get("addedAt") and r["addedAt"] >= config.X_DESDE
            and r["date"] >= today.isoformat() and r["id"] not in done]
    # Orden de envío: primero las añadidas antes; dentro del mismo día, por fecha de la carrera (la más próxima primero)
    nuevas = sorted(todo, key=lambda r: (r["addedAt"], r["date"], r.get("time") or "99", r["name"]))
    return nuevas + avisos(races, st, today)


def marcar(st: dict, r: dict, via: str) -> None:
    if r.get("_clave"):
        st.setdefault("avisos", {})[r["_clave"]] = date.today().isoformat()
    else:
        st["publicadas"][r["id"]] = via


def ntfy_topic(hook: str) -> str:
    """Tema privado de ntfy, derivado del secreto (nadie puede adivinarlo sin la URL del webhook)."""
    return "runningspain-" + hashlib.sha256(hook.encode()).hexdigest()[:16]


def send_ntfy(topic: str, todo: list, st: dict, guardar: bool = True) -> int:
    sent = 0
    for i, r in enumerate(todo):
        if i:
            time.sleep(config.MACRO_PAUSA)
        text = compose(r, con_enlace=config.MACRO_CON_ENLACE)
        try:
            resp = requests.post(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"), timeout=30,
                                 headers={"Title": "RunningSpain", "Tags": "runner"})
        except requests.RequestException as e:
            print(f"ntfy: error de red con «{r['name']}»: {e}")
            break
        if resp.ok:
            marcar(st, r, "ntfy")
            if guardar:
                save_state(st)
            sent += 1
            print(f"ntfy: enviada «{r['name']}»")
        else:
            print(f"ntfy: error {resp.status_code} con «{r['name']}»: {resp.text[:200]}")
            break
    print(f"ntfy: {sent} envíos hechos")
    return 0


def send_macrodroid(hook: str, todo: list, st: dict, guardar: bool = True) -> int:
    sent = 0
    for i, r in enumerate(todo):
        if i:
            time.sleep(config.MACRO_PAUSA)
        text = compose(r, con_enlace=config.MACRO_CON_ENLACE)
        enlace = r["url"] if r.get("official") and r.get("url") else config.X_WEB
        try:
            todos = {"tweet": text, "carrera": r["name"], "enlace": enlace,
                     "orden": str(i + 1), "total": str(len(todo)), "fecha": r["date"]}
            params = {k: todos[k] for k in config.MACRO_PARAMS if k in todos}
            # Espacios como %20 (no "+"), que MacroDroid decodifica siempre bien
            qs = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())
            url = hook + (("&" if "?" in hook else "?") + qs if qs else "")
            if config.MACRO_RELE:
                resp = requests.post(config.MACRO_RELE, data=text.encode("utf-8"), timeout=30,
                                     headers={"Content-Type": "text/plain; charset=utf-8", "X-Hook": url,
                                              "User-Agent": "RunningSpainBot/1.0"})
            elif config.MACRO_CUERPO:
                resp = requests.post(url, data=text.encode("utf-8"), timeout=30,
                                     headers={"Content-Type": "text/plain; charset=utf-8"})
            else:
                resp = requests.get(url, timeout=30)
        except requests.RequestException as e:
            print(f"MacroDroid: error de red con «{r['name']}»: {e}")
            break
        if resp.ok:
            marcar(st, r, "macrodroid")
            if guardar:
                save_state(st)
            sent += 1
            print(f"MacroDroid: enviada «{r['name']}» → respuesta {resp.status_code} {resp.text[:80]}")
        else:
            print(f"MacroDroid: error {resp.status_code} con «{r['name']}»: {resp.text[:200]}")
            break
    print(f"MacroDroid: {sent} envíos hechos")
    return 0


def main(argv: list[str]) -> int:
    today = date.today()
    races = json.loads(DATA.read_text(encoding="utf-8"))["races"]
    st = load_state()
    todo = pending(races, st, today)
    n_av = sum(1 for r in todo if r.get("_motivo"))
    print(f"X: {len(todo) - n_av} carreras nuevas y {n_av} avisos sin publicar (tope {config.X_MAX_POR_EJECUCION} por ejecución)")
    if "--prueba-macro" in argv:
        # Envía UNA carrera real a MacroDroid sin anotarla como publicada (para probar la macro)
        hook = os.environ.get("MACRODROID_WEBHOOK", "").strip().rstrip(".,;")
        if not hook:
            print("MacroDroid: falta el secreto MACRODROID_WEBHOOK")
            return 1
        cand = sorted((r for r in races if r["date"] >= today.isoformat() and r.get("official")),
                      key=lambda r: (r["date"], r.get("time") or "99"))[:1]
        if config.NTFY:
            return send_ntfy(ntfy_topic(hook), cand, {"publicadas": {}}, guardar=False)
        return send_macrodroid(hook, cand, {"publicadas": {}}, guardar=False)
    if "--prueba" in argv:
        for r in todo[: config.X_MAX_POR_EJECUCION]:
            t = compose(r)
            print(f"--- {x_len(t)} caracteres\n{t}")
        return 0
    if todo:
        try:
            shorten.ensure(races, must=[r["id"] for r in todo[: config.X_MAX_POR_EJECUCION]], limit=config.X_MAX_POR_EJECUCION)
        except Exception as e:
            print(f"Enlaces cortos: error {e}")
    hook = os.environ.get("MACRODROID_WEBHOOK", "").strip().rstrip(".,;")
    if hook and config.NTFY:
        return send_ntfy(ntfy_topic(hook), todo[: config.X_MAX_POR_EJECUCION], st)
    if hook:
        return send_macrodroid(hook, todo[: config.X_MAX_POR_EJECUCION], st)
    keys = {"api_key": os.environ.get("X_API_KEY", ""), "api_secret": os.environ.get("X_API_SECRET", ""),
            "token": os.environ.get("X_ACCESS_TOKEN", ""), "token_secret": os.environ.get("X_ACCESS_SECRET", "")}
    if not all(keys.values()):
        print("X: no hay MACRODROID_WEBHOOK ni claves de la API de X. No se publica nada.")
        return 0
    sent = 0
    for r in todo[: config.X_MAX_POR_EJECUCION]:
        text = compose(r)
        resp = requests.post(URL, json={"text": text}, timeout=30,
                             headers={"Authorization": oauth_header("POST", URL, keys), "Content-Type": "application/json"})
        if resp.status_code == 201:
            marcar(st, r, resp.json().get("data", {}).get("id", ""))
            save_state(st)
            sent += 1
            print(f"X: publicada «{r['name']}»")
            time.sleep(3)
            continue
        print(f"X: error {resp.status_code} con «{r['name']}»: {resp.text[:300]}")
        if resp.status_code == 403 and "duplicate" in resp.text.lower():
            marcar(st, r, "duplicada")   # ya estaba publicada: no reintentar
            save_state(st)
            continue
        break   # sin saldo (402), límite (429), claves mal (401/403): se reintenta en la próxima ejecución
    print(f"X: {sent} publicaciones hechas")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
