"""Robot de RunningSpain: descubre carreras, las completa y guarda docs/data/carreras.json.

Uso:  python -m scraper.main            (ejecución completa)
      python -m scraper.main --enrich-only
"""
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config, enrich, net, parse, sources

DATA = Path(__file__).resolve().parent.parent / "docs" / "data" / "carreras.json"
SEEN = Path(__file__).resolve().parent.parent / "estado" / "vistos.json"
FINAL = {"no_asfalto", "duplicada", "añadida", "sin_nombre", "extranjera"}   # no se vuelven a abrir nunca
GENERIC = {"san", "sant", "silvestre", "media", "maraton", "medio", "mitja", "marato", "10k", "5k",
           "15k", "21k", "solidaria", "solidari", "navidad", "nadal", "nocturna", "urbana", "race",
           "run", "half", "contra", "cancer", "mujer", "dona", "por", "de", "del", "la", "el", "los",
           "las", "y", "i", "a", "en", "carrera", "cursa", "carreira", "popular", "ciudad", "ciutat",
           "villa", "vila", "2026", "2027", "2028", "edicion"}
# Campos cuyo cambio se anuncia en la web como "actualizada"
TRACKED = ("url", "regulation", "banner", "price", "time", "km", "date", "route", "inscripcion")


RUN_AT = datetime.now(timezone.utc).isoformat(timespec="minutes")


def touch(r: dict) -> None:
    """Apunta en la ficha la fecha y hora de esta revisión del robot (se muestra en la web)."""
    r["revisada"] = RUN_AT


def log(msg: str) -> None:
    print(msg, flush=True)


def key(name: str, city: str) -> set[str]:
    k = {w for w in re.findall(r"[a-z0-9]+", parse.norm(name)) if w not in GENERIC and not re.fullmatch(r"[ivxlc]+", w)}
    return k or {"@" + w for w in re.findall(r"[a-z0-9]+", parse.norm(city))}


def same_race(a: dict, b: dict) -> bool:
    if a["date"] != b["date"]:
        return False
    ka, kb = key(a["name"], a.get("city", "")), key(b["name"], b.get("city", ""))
    return bool(ka and kb) and len(ka & kb) / min(len(ka), len(kb)) >= 0.6


def load() -> dict:
    if DATA.exists():
        return json.loads(DATA.read_text(encoding="utf-8"))
    return {"updatedAt": None, "races": []}


def save(db: dict) -> None:
    db["races"].sort(key=lambda r: (r["date"], r.get("time") or "99", r["name"]))
    db["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db["count"] = len(db["races"])
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")


def load_seen() -> dict:
    if SEEN.exists():
        return json.loads(SEEN.read_text(encoding="utf-8"))
    return {}


def save_seen(seen: dict, today: date) -> None:
    limit = (today - timedelta(days=200)).isoformat()
    seen = {u: v for u, v in seen.items() if v.get("t", "") >= limit or u.startswith("_")}
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    SEEN.write_text(json.dumps(seen, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")


def skip_seen(v: dict | None, today: date) -> bool:
    """True si la ficha ya se revisó y no merece la pena volver a abrirla hoy."""
    if not v:
        return False
    if v.get("m") in FINAL:
        return True
    d = v.get("d")
    if v.get("m") == "fuera_de_ventana" and d:
        return d < today.isoformat() or d > (today + timedelta(days=config.DAYS_AHEAD)).isoformat()
    try:
        return (today - date.fromisoformat(v.get("t", "2000-01-01"))).days < config.VISTOS_REINTENTO_DIAS
    except ValueError:
        return False


def discover(db: dict, today: date, changes: dict) -> int:
    log("Buscando carreras en los calendarios…")
    seen = load_seen()
    if not seen.get("_alt_v1"):   # una vez: reabrir las duplicadas para apuntarlas como fuente alternativa
        seen = {u: v for u, v in seen.items() if v.get("m") != "duplicada"}
        seen["_alt_v1"] = {"m": "marca", "t": today.isoformat()}
    cands = []
    for fn in (sources.list_sportplan, sources.list_runninglife, sources.list_sportmaniacs,
               sources.list_carreraspopulares, sources.list_lineadesalida, sources.list_runedia):
        try:
            cands += fn(today, log)
        except Exception as e:  # una fuente rota no debe parar el robot
            log(f"  error en {fn.__name__}: {e}")
    known_sources = {r.get("source") for r in db["races"]}
    total = len(cands)
    cands = [c for c in cands if c["source_url"] not in known_sources and not skip_seen(seen.get(c["source_url"]), today)]
    # primero las de fecha conocida (más próximas antes); después las de Runedia, con su propio tope
    dated = sorted((c for c in cands if c.get("date")), key=lambda c: c["date"])
    undated = [c for c in cands if not c.get("date") and "rid" not in c]
    runedia = [c for c in cands if "rid" in c][: config.RUNEDIA_MAX_POR_EJECUCION]
    queue = (dated + undated + runedia)[: config.MAX_EVENT_PAGES]
    log(f"{total} fichas en los calendarios · {len(cands)} sin revisar · se abren {len(queue)}")
    added, reasons = 0, {}
    for c in queue:
        r = sources.read_event_page(c, today)
        motivo = c.get("motivo", "sin_acceso")
        if r:
            dup = next((x for x in db["races"] if same_race(x, r)), None)
            if dup:
                motivo = "duplicada"
                for k in ("time", "city", "region"):
                    if not dup.get(k) and r.get(k):
                        dup[k] = r[k]
                        if k in TRACKED:
                            changes["updated"].setdefault(dup["id"], []).append(k)
                if not dup.get("distances") and r.get("distances"):
                    dup["distances"] = r["distances"]
                alt = dup.setdefault("alt", [])   # otra ficha de la misma carrera: sirve para completarla
                if c["source_url"] != dup.get("source") and c["source_url"] not in alt and len(alt) < 5:
                    alt.append(c["source_url"])
                dup.setdefault("official_guess", r.get("official_guess"))
                touch(dup)
            else:
                motivo = "añadida"
                r["id"] = parse.race_id(r["name"], r["date"])
                r["official"] = False
                r["url"] = ""
                r["addedAt"] = today.isoformat()
                touch(r)
                db["races"].append(r)
                changes["added"].append(r["id"])
                added += 1
        reasons[motivo] = reasons.get(motivo, 0) + 1
        seen[c["source_url"]] = {"m": motivo, "d": c.get("fecha"), "t": today.isoformat()}
    save_seen(seen, today)
    log(f"Resultado: {reasons}")
    log(f"Añadidas {added} carreras nuevas")
    return added


def complete(db: dict, today: date, changes: dict) -> int:
    todo = [r for r in db["races"] if r["date"] >= today.isoformat() and enrich.needs_work(r, today)]
    big = lambda r: 0 if set(r.get("distances") or []) & {"42K", "21K"} else 1
    todo.sort(key=lambda r: (r["date"], big(r)))
    log(f"Completando fichas: {len(todo)} pendientes, se revisan {min(len(todo), config.MAX_ENRICH)}")
    done = 0
    for r in todo[: config.MAX_ENRICH]:
        upd = enrich.enrich(r, today)
        touch(r)
        before = {k: r.get(k) for k in TRACKED}
        r.update({k: v for k, v in upd.items() if v is not None})
        changed = [k for k in TRACKED if r.get(k) and r.get(k) != before[k]]
        if changed and r["id"] not in changes["added"]:
            r["changedAt"] = today.isoformat()
            lst = changes["updated"].setdefault(r["id"], [])
            lst += [k for k in changed if k not in lst]
        if upd.get("official"):
            done += 1
    log(f"Fichas con web oficial nueva: {done}")
    return done


def media(db: dict, today: date, changes: dict) -> int:
    """Reabre la ficha del calendario de las carreras sin cartel o sin recorrido."""
    limit = (today - timedelta(days=config.MEDIA_RECHECK_DAYS)).isoformat()
    if not db.get("rutasV2"):   # una vez: volver a buscar recorrido (ahora también mapas incrustados e imágenes)
        for r in db["races"]:
            if not r.get("route"):
                r.pop("mediaChecked", None)
        db["rutasV2"] = today.isoformat()
    # reglamentos: llegar al PDF si era una página, y comprobar cada semana que el enlace sigue abriendo
    week = (today - timedelta(days=7)).isoformat()
    regs = [r for r in db["races"] if r["date"] >= today.isoformat() and r.get("regulation")
            and (not r.get("regResolved") or (r.get("regChecked") or "") < week)]
    regs.sort(key=lambda r: (r.get("regChecked") or "", r["date"]))
    better = broken = 0
    for r in regs[: config.MAX_MEDIA]:
        old = r["regulation"]
        page = r.get("url") if r.get("official") else None
        new = enrich.resolve_regulation(old, found_on=page)
        touch(r)
        if not new and page:      # el enlace ya no abre: se busca otra vez en la web oficial
            html, final, _ = net.get(page)
            again = parse.find_regulation(html, final) if html and not isinstance(html, bytes) else None
            new = enrich.resolve_regulation(again, found_on=final) if again else None
        r["regResolved"] = r["regChecked"] = today.isoformat()
        if new == old:
            continue
        if new:
            r["regulation"] = new
            better += 1
        else:
            r.pop("regulation")
            broken += 1
        if r["id"] not in changes["added"] and new:
            lst = changes["updated"].setdefault(r["id"], [])
            if "regulation" not in lst:
                lst.append("regulation")
    log(f"Reglamentos revisados: {min(len(regs), config.MAX_MEDIA)} · {better} cambiados por un enlace que funciona · {broken} quitados por no abrir")
    todo = [r for r in db["races"] if r["date"] >= today.isoformat() and r.get("source")
            and (not r.get("banner") or not r.get("route")) and (r.get("mediaChecked") or "") < limit]
    todo.sort(key=lambda r: r["date"])
    log(f"Carteles y recorridos: {len(todo)} pendientes, se revisan {min(len(todo), config.MAX_MEDIA)}")
    found = 0
    for r in todo[: config.MAX_MEDIA]:
        got = sources.read_media(r["source"])
        touch(r)
        # el recorrido, primero en la web de la carrera (portada o página «Recorrido»)
        if not r.get("route") and r.get("official") and r.get("url"):
            own = enrich.route_from_site(r["url"])
            if own:
                got["route"] = own
        r["mediaChecked"] = today.isoformat()
        changed = []
        if got.get("banner") and (not r.get("banner") or got["bannerScore"] > (r.get("bannerScore") or 0)):
            r["banner"], r["bannerScore"] = got["banner"], got["bannerScore"]
            changed.append("banner")
        if got.get("route") and not r.get("route"):
            r["route"] = got["route"]
            changed.append("route")
        if changed:
            found += 1
            if r["id"] not in changes["added"]:
                lst = changes["updated"].setdefault(r["id"], [])
                lst += [k for k in changed if k not in lst]
    log(f"Fichas con cartel o recorrido nuevo: {found}")
    return found


def signup_page(r: dict) -> tuple[str | None, bool]:
    """Página donde mirar el estado de la inscripción (la de inscripción si la hay) y si es una plataforma."""
    if r.get("official") and r.get("url"):
        return r["url"], parse.is_signup_platform(r["url"])
    src = r.get("source") or ""
    if src and parse.is_signup_platform(src):
        return src, True
    return None, False


def registrations(db: dict, today: date, changes: dict) -> int:
    """Comprueba si las inscripciones están abiertas, agotadas, cerradas o próximamente."""
    near = (today + timedelta(days=config.INSCRIPCION_CERCA_DIAS)).isoformat()
    week = (today - timedelta(days=7)).isoformat()
    due = []
    for r in db["races"]:
        if r["date"] < today.isoformat() or not signup_page(r)[0]:
            continue
        last = r.get("inscripcionAt") or ""
        if (r["date"] <= near and last < today.isoformat()) or last < week:
            due.append(r)
    due.sort(key=lambda r: (r.get("inscripcionAt") or "", r["date"]))   # primero las nunca revisadas
    log(f"Inscripciones: {len(due)} por revisar, se revisan {min(len(due), config.MAX_INSCRIPCION)}")
    changed = 0
    for r in due[: config.MAX_INSCRIPCION]:
        url, platform = signup_page(r)
        html, final, ctype = net.get(url)
        if not html or isinstance(html, bytes):
            continue
        st = parse.registration_status(html, platform)
        touch(r)
        r["inscripcionAt"] = today.isoformat()
        if st != r.get("inscripcion"):
            if st:
                r["inscripcion"] = st
            else:
                r.pop("inscripcion", None)
            changed += 1
            if st and r["id"] not in changes["added"]:
                lst = changes["updated"].setdefault(r["id"], [])
                if "inscripcion" not in lst:
                    lst.append("inscripcion")
    log(f"Inscripciones con estado nuevo: {changed}")
    return changed


def tidy(db: dict) -> int:
    """Aplica a los datos guardados los filtros y arreglos actuales (por si se mejoraron)."""
    before = len(db["races"])
    db["races"] = [r for r in db["races"] if parse.is_road(r["name"]) and not r.get("foreign")]
    for r in db["races"]:   # recorridos que no superan el filtro actual: fuera, y se vuelve a buscar
        if r.get("route") and not parse.is_route_url(r["route"]):
            r.pop("route")
            r.pop("mediaChecked", None)
    for r in db["races"]:   # las etiquetas de distancia, iguales que los km de la ficha
        tags = parse.tags_from_km(r.get("km", ""))
        if tags:
            r["distances"] = tags
    for r in db["races"]:
        name, place = parse.split_name_place(r["name"])
        if place and not r.get("city"):
            r["city"] = place
        r["name"] = parse.clean_name(name)
        if r.get("city"):
            r["city"] = parse.nice_name(r["city"])
    return before - len(db["races"])


def prune(db: dict, today: date) -> int:
    limit = (today - timedelta(days=config.KEEP_PAST_DAYS)).isoformat()
    before = len(db["races"])
    db["races"] = [r for r in db["races"] if r["date"] >= limit]
    return before - len(db["races"])


def main(argv: list[str]) -> None:
    t0 = time.time()
    today = date.today()
    db = load()
    removed = prune(db, today) + tidy(db)
    changes = {"added": [], "updated": {}}
    added = 0 if "--enrich-only" in argv else discover(db, today, changes)
    save(db)
    completed = complete(db, today, changes)
    save(db)
    media(db, today, changes)
    save(db)
    registrations(db, today, changes)
    ids = {r["id"] for r in db["races"]}
    db["lastRun"] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "added": [i for i in changes["added"] if i in ids],
        "updated": {i: f for i, f in changes["updated"].items() if i in ids},
        "removed": removed,
    }
    save(db)
    with_site = sum(1 for r in db["races"] if r.get("official"))
    log(f"\nResumen: {len(db['races'])} carreras · {added} nuevas · {completed} completadas · "
        f"{removed} pasadas eliminadas · {with_site} con web oficial · "
        f"{net.stats['requests']} peticiones en {int(time.time() - t0)} s")


if __name__ == "__main__":
    main(sys.argv[1:])
