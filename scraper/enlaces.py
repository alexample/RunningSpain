"""Comprueba que los enlaces de reglamento (y recorrido) abren de verdad. Escribe estado/enlaces.json.

Uso: python -m scraper.enlaces
"""
import json
from collections import Counter
from pathlib import Path

import requests

from . import config, main

OUT = Path(__file__).resolve().parent.parent / "estado" / "enlaces.json"
H = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36",
     "Accept-Language": "es-ES,es;q=0.9"}


def check(url: str) -> dict:
    try:
        r = requests.get(url, headers=H, timeout=25, stream=True, allow_redirects=True)
        head = next(r.iter_content(2048), b"")
        r.close()
        ctype = r.headers.get("content-type", "")
        return {"status": r.status_code, "final": r.url, "ctype": ctype.split(";")[0],
                "pdf": head.startswith(b"%PDF"), "html": b"<html" in head.lower() or b"<!doctype" in head.lower()}
    except Exception as e:
        return {"status": None, "error": type(e).__name__}


def run() -> None:
    db = main.load()
    res = {}
    for r in db["races"]:
        u = r.get("regulation")
        if u:
            res[r["id"]] = {"name": r["name"], "url": u, **check(u)}
    def kind(x):
        if x.get("status") is None:
            return "sin_respuesta:" + x.get("error", "")
        if x["status"] >= 400:
            return f"error_{x['status']}"
        if x["url"].lower().split("?")[0].endswith(".pdf") and not x["pdf"]:
            return "dice_pdf_pero_no_lo_es"
        return "ok_pdf" if x["pdf"] else "ok_pagina"
    for x in res.values():
        x["kind"] = kind(x)
    summary = Counter(x["kind"] for x in res.values())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"resumen": summary, "enlaces": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(dict(summary))


if __name__ == "__main__":
    run()
