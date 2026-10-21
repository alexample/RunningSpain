"""Pruebas sin conexión: python -m unittest discover -s tests"""
import unittest
from datetime import date
from unittest import mock

from scraper import enrich, main, parse, sources

EVENT_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"SportsEvent","name":"Media Maratón de Ejemplo 2026",
 "startDate":"2026-11-15T09:30:00+01:00",
 "location":{"@type":"Place","name":"Plaza Mayor","address":{"@type":"PostalAddress","addressLocality":"Ejemplo","addressRegion":"Salamanca"}},
 "offers":{"@type":"Offer","price":"18"},
 "url":"https://sportplan.es/es/events/media-ejemplo"}
</script></head><body>
<h1>Media Maratón de Ejemplo</h1>
<a href="https://www.mediaejemplo.es/">Web oficial</a>
<a href="https://facebook.com/mediaejemplo">Facebook</a>
</body></html>
"""

OFFICIAL_PAGE = """
<html><head><meta property="og:image" content="/img/cartel-2026.jpg"></head><body>
<p>La salida será a las 9:30 h desde la Plaza Mayor. Recorrido de 21,097 km y prueba de 10 km.</p>
<a href="/docs/Reglamento-2026.pdf">Reglamento</a>
</body></html>
"""
REG_TEXT = "Cuota de inscripción: 15 € hasta el 30 de septiembre y 20 € después. Precio en la feria 25 €."


def fake_get(url, binary=False):
    if "sportplan" in url:
        return EVENT_PAGE, url, "text/html"
    if url.endswith(".pdf"):
        return b"%PDF", url, "application/pdf"
    return OFFICIAL_PAGE, url, "text/html"


class ParseTests(unittest.TestCase):
    def test_jsonld(self):
        f = parse.event_fields(parse.jsonld_events(EVENT_PAGE)[0])
        self.assertEqual(f["date"], "2026-11-15")
        self.assertEqual(f["time"], "09:30")
        self.assertEqual(f["price"], "18 €")
        self.assertEqual(parse.region_from_text(f["region_hint"]), "Castilla y León")

    def test_official_guess_skips_aggregators_and_social(self):
        self.assertEqual(parse.guess_official(EVENT_PAGE, "https://sportplan.es/es/events/x"), "https://www.mediaejemplo.es/")

    def test_extractors(self):
        self.assertEqual(parse.extract_price(REG_TEXT), "15–25 €")
        self.assertEqual(parse.extract_time("La salida será a las 9:30 h"), "09:30")
        self.assertEqual(parse.extract_km("Recorrido de 21,097 km y prueba de 10 km"), "21,097 km · 10 km")
        self.assertEqual(parse.find_regulation(OFFICIAL_PAGE, "https://www.mediaejemplo.es/"),
                         "https://www.mediaejemplo.es/docs/Reglamento-2026.pdf")
        self.assertEqual(parse.og_image(OFFICIAL_PAGE, "https://www.mediaejemplo.es/"),
                         "https://www.mediaejemplo.es/img/cartel-2026.jpg")

    def test_road_filter(self):
        self.assertTrue(parse.is_road("Media Maratón de Ejemplo"))
        self.assertTrue(parse.is_road("San Silvestre Vallecana"))
        self.assertFalse(parse.is_road("Trail Sierra de Mijas"))
        self.assertFalse(parse.is_road("Cross Popular de Navidad"))
        self.assertFalse(parse.is_road("Carrera de Obstáculos Pirata"))

    def test_distances(self):
        self.assertEqual(parse.distances_from("Media Maratón y 10K"), ["21K", "10K"])
        self.assertEqual(parse.distances_from("Maratón Valencia"), ["42K"])

    def test_dedupe(self):
        a = {"name": "San Silvestre de Gijón", "date": "2026-12-31", "city": "Gijón"}
        b = {"name": "San Silvestre de Oviedo", "date": "2026-12-31", "city": "Oviedo"}
        c = {"name": "XL San Silvestre Gijón 2026", "date": "2026-12-31", "city": "Gijón"}
        self.assertFalse(main.same_race(a, b))
        self.assertTrue(main.same_race(a, c))


class FlowTests(unittest.TestCase):
    def test_read_and_enrich(self):
        today = date(2026, 10, 22)
        with mock.patch("scraper.net.get", side_effect=fake_get), \
             mock.patch("scraper.enrich.pdf_text", return_value=REG_TEXT):
            r = sources.read_event_page({"source_url": "https://sportplan.es/es/events/media-ejemplo"}, today)
            self.assertEqual(r["name"], "Media Maratón de Ejemplo")
            self.assertEqual(r["region"], "Castilla y León")
            self.assertEqual(r["official_guess"], "https://www.mediaejemplo.es/")
            r.update({"official": False, "url": "", "price": ""})
            upd = enrich.enrich(r, today)
        self.assertTrue(upd["official"])
        self.assertEqual(upd["url"], "https://www.mediaejemplo.es/")
        self.assertEqual(upd["regulation"], "https://www.mediaejemplo.es/docs/Reglamento-2026.pdf")
        self.assertEqual(upd["price"], "15–25 €")
        self.assertEqual(upd["km"], "21,097 km · 10 km")
        self.assertEqual(upd["banner"], "https://www.mediaejemplo.es/img/cartel-2026.jpg")


class ChangesTests(unittest.TestCase):
    def test_complete_records_changed_fields(self):
        today = date(2026, 10, 22)
        db = {"races": [{"id": "a-2026-1101", "name": "A", "date": "2026-11-01", "price": "", "url": ""}]}
        changes = {"added": [], "updated": {}}
        with mock.patch("scraper.enrich.needs_work", return_value=True), \
             mock.patch("scraper.enrich.enrich", return_value={"price": "12 €", "url": "https://a.es/", "official": True, "checkedAt": "x"}):
            main.complete(db, today, changes)
        self.assertEqual(changes["updated"], {"a-2026-1101": ["url", "price"]})
        self.assertEqual(db["races"][0]["changedAt"], "2026-10-22")


if __name__ == "__main__":
    unittest.main()
