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
TRACKED = ("url", "regulation", "banner", "price", "time", "km", "date")


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
    seen = {u: v for u, v in seen.items() if v.get("t", "") >= limit}
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
                dup.setdefault("official_guess", r.get("official_guess"))
            else:
                motivo = "añadida"
                r["id"] = parse.race_id(r["name"], r["date"])
                r["official"] = False
                r["url"] = ""
                r["addedAt"] = today.isoformat()
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


def tidy(db: dict) -> int:
    """Aplica a los datos guardados los filtros y arreglos actuales (por si se mejoraron)."""
    before = len(db["races"])
    db["races"] = [r for r in db["races"] if parse.is_road(r["name"]) and not r.get("foreign")]
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
