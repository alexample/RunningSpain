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
GENERIC = {"san", "sant", "silvestre", "media", "maraton", "medio", "mitja", "marato", "10k", "5k",
           "15k", "21k", "solidaria", "solidari", "navidad", "nadal", "nocturna", "urbana", "race",
           "run", "half", "contra", "cancer", "mujer", "dona", "por", "de", "del", "la", "el", "los",
           "las", "y", "i", "a", "en", "carrera", "cursa", "carreira", "popular", "ciudad", "ciutat",
           "villa", "vila", "2026", "2027", "2028", "edicion"}


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


def discover(db: dict, today: date) -> int:
    log("Buscando carreras en los calendarios…")
    cands = sources.list_sportplan(today, log) + sources.list_runninglife(today, log)
    known_sources = {r.get("source") for r in db["races"]}
    cands = [c for c in cands if c["source_url"] not in known_sources]
    cands.sort(key=lambda c: c.get("date") or "9999")
    log(f"{len(cands)} fichas nuevas que revisar (máximo {config.MAX_EVENT_PAGES})")
    added = 0
    for c in cands[: config.MAX_EVENT_PAGES]:
        r = sources.read_event_page(c, today)
        if not r:
            continue
        dup = next((x for x in db["races"] if same_race(x, r)), None)
        if dup:
            for k in ("time", "city", "region"):
                if not dup.get(k) and r.get(k):
                    dup[k] = r[k]
            if not dup.get("distances") and r.get("distances"):
                dup["distances"] = r["distances"]
            dup.setdefault("official_guess", r.get("official_guess"))
            continue
        r["id"] = parse.race_id(r["name"], r["date"])
        r["official"] = False
        r["url"] = ""
        db["races"].append(r)
        added += 1
    log(f"Añadidas {added} carreras nuevas")
    return added


def complete(db: dict, today: date) -> int:
    todo = [r for r in db["races"] if r["date"] >= today.isoformat() and enrich.needs_work(r, today)]
    big = lambda r: 0 if set(r.get("distances") or []) & {"42K", "21K"} else 1
    todo.sort(key=lambda r: (r["date"], big(r)))
    log(f"Completando fichas: {len(todo)} pendientes, se revisan {min(len(todo), config.MAX_ENRICH)}")
    done = 0
    for r in todo[: config.MAX_ENRICH]:
        upd = enrich.enrich(r, today)
        r.update({k: v for k, v in upd.items() if v is not None})
        if upd.get("official"):
            done += 1
    log(f"Fichas con web oficial nueva: {done}")
    return done


def prune(db: dict, today: date) -> int:
    limit = (today - timedelta(days=config.KEEP_PAST_DAYS)).isoformat()
    before = len(db["races"])
    db["races"] = [r for r in db["races"] if r["date"] >= limit]
    return before - len(db["races"])


def main(argv: list[str]) -> None:
    t0 = time.time()
    today = date.today()
    db = load()
    removed = prune(db, today)
    added = 0 if "--enrich-only" in argv else discover(db, today)
    save(db)
    completed = complete(db, today)
    save(db)
    with_site = sum(1 for r in db["races"] if r.get("official"))
    log(f"\nResumen: {len(db['races'])} carreras · {added} nuevas · {completed} completadas · "
        f"{removed} pasadas eliminadas · {with_site} con web oficial · "
        f"{net.stats['requests']} peticiones en {int(time.time() - t0)} s")


if __name__ == "__main__":
    main(sys.argv[1:])
