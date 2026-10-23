"""Pruebas sin conexión: python -m unittest discover -s tests"""
import unittest
from pathlib import Path
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


class XPostTests(unittest.TestCase):
    def test_oauth_signature_matches_x_docs(self):
        from scraper import xpost
        keys = {"api_key": "xvz1evFS4wEEPTGEFPHBog", "api_secret": "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
                "token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
                "token_secret": "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE"}
        h = xpost.oauth_header("POST", "https://api.twitter.com/1.1/statuses/update.json", keys,
                               extra={"include_entities": "true",
                                      "status": "Hello Ladies + Gentlemen, a signed OAuth request!"},
                               nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", ts="1318622958")
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', h)

    def test_compose_fits_and_skips_backlog(self):
        from scraper import xpost
        r = {"id": "x", "name": "Carrera " + "Muy " * 80 + "Larga", "date": "2026-11-29", "city": "Colmenar Viejo",
             "region": "Comunidad de Madrid", "distances": ["10K"], "addedAt": "2026-10-21"}
        self.assertLessEqual(xpost.x_len(xpost.compose(r)), 280)
        self.assertEqual(xpost.pending([r], {"publicadas": {}}, date(2026, 10, 22)), [])
        r["addedAt"] = "2026-10-23"
        self.assertEqual(len(xpost.pending([r], {"publicadas": {}}, date(2026, 10, 23))), 1)
        self.assertEqual(xpost.pending([r], {"publicadas": {"x": "1"}}, date(2026, 10, 23)), [])


SM_LIST = """<html><body>
<a href="/es/races/10k-ciudad-de-ejemplo-2026">10K</a>
<a href="/es/races/trail-sierra-ejemplo-2026">Trail</a>
<a href="/es/races?page=2">2</a></body></html>"""
SM_EVENT = """<html><head><script type="application/ld+json">
{"@type":"SportsEvent","name":"10K Ciudad de Ejemplo","startDate":"2026-11-29T10:00:00+01:00",
 "location":{"@type":"Place","address":{"addressLocality":"Lugo","addressRegion":"Lugo"}}}
</script></head><body><h1>10K Ciudad de Ejemplo</h1></body></html>"""
LS_EVENT = """<html><body><h1>XI CARRERA SOLIDARIA PUERTO DE EJEMPLO</h1>
<p>Lugar Cartagena Fecha 21 de Noviembre de 2026 Hora 16:30 Reglamento</p></body></html>"""
RU_INDEX = "<sitemapindex><sitemap><loc>https://runedia.mundodeportivo.com/sitemaps/sitemap-curses1.xml</loc></sitemap></sitemapindex>"
RU_MAP = """<urlset>
<url><loc>https://runedia.mundodeportivo.com/carrera/cursa-de-ejemplo-2026/202637600/</loc></url>
<url><loc>https://runedia.mundodeportivo.com/carrera/marxa-de-ejemplo-2026/202637601/</loc></url>
<url><loc>https://runedia.mundodeportivo.com/carrera/cursa-vieja-2024/20241234/</loc></url>
</urlset>"""


def fake_sources(url, binary=False):
    pages = {
        "https://sportmaniacs.com/es/races?page=1": SM_LIST,
        "https://sportmaniacs.com/es/races/10k-ciudad-de-ejemplo-2026": SM_EVENT,
        "https://runedia.mundodeportivo.com/sitemap_index.xml": RU_INDEX,
        "https://runedia.mundodeportivo.com/sitemaps/sitemap-curses1.xml": RU_MAP,
        "https://runedia.mundodeportivo.com/carrera/cursa-de-ejemplo-2026/202637600/": LS_EVENT.replace("21 de Noviembre", "6 de Diciembre"),
    }
    if url in pages:
        return pages[url], url, "text/html"
    return None, url, ""


class NewSourcesTests(unittest.TestCase):
    def test_date_from_text(self):
        self.assertEqual(parse.date_from_text("Lugar Cartagena Fecha 21 de Noviembre de 2026 Hora 16:30"), "2026-11-21")
        self.assertEqual(parse.date_from_text("Martes, 25-8-2026"), "2026-08-25")
        self.assertEqual(parse.date_from_text("dissabte 14 de desembre de 2026"), "2026-12-14")
        self.assertIsNone(parse.date_from_text("sin fecha"))

    def test_split_name_place_only_with_trailing_date(self):
        self.assertEqual(parse.split_name_place("XII TimonCap Costa Cálida 2026 Cabo de Palos 24/10/2026"),
                         ("XII TimonCap Costa Cálida", "Cabo de Palos"))
        self.assertEqual(parse.split_name_place("Media Maratón de Cuenca"), ("Media Maratón de Cuenca", ""))
        self.assertEqual(parse.split_name_place("Desafío Hybrid Race San Pedro del Pinatar San Pedro del Pinatar 07/11/2026"),
                         ("Desafío Hybrid Race San Pedro del Pinatar", "San Pedro del Pinatar"))
        self.assertEqual(parse.clean_name("Media Maratón de Cuenca"), "Media Maratón de Cuenca")
        self.assertEqual(parse.clean_name("Maratón de Sevilla 2027"), "Maratón de Sevilla")

    def test_nice_name(self):
        self.assertEqual(parse.nice_name("XI CARRERA SOLIDARIA DE LA VILLA"), "XI Carrera Solidaria de la Villa")
        self.assertEqual(parse.nice_name("Media Maratón de Lugo"), "Media Maratón de Lugo")

    def test_generic_page_without_jsonld(self):
        with mock.patch("scraper.net.get", return_value=(LS_EVENT, "https://www.lineadesalida.net/carreras/x", "text/html")):
            r = sources.read_event_page({"source_url": "https://www.lineadesalida.net/carreras/x"}, date(2026, 10, 23))
        self.assertEqual(r["date"], "2026-11-21")
        self.assertEqual(r["time"], "16:30")
        self.assertEqual(r["name"], "XI Carrera Solidaria Puerto de Ejemplo")

    def test_lists_filter_trail_and_old_years(self):
        with mock.patch("scraper.net.get", side_effect=fake_sources):
            sm = sources.list_sportmaniacs(date(2026, 10, 23), lambda m: None)
            ru = sources.list_runedia(date(2026, 10, 23), lambda m: None)
        self.assertEqual([c["source_url"] for c in sm], ["https://sportmaniacs.com/es/races/10k-ciudad-de-ejemplo-2026"])
        self.assertEqual([c["source_url"] for c in ru], ["https://runedia.mundodeportivo.com/carrera/cursa-de-ejemplo-2026/202637600/"])

    def test_discover_remembers_what_it_saw(self):
        import tempfile
        today = date(2026, 10, 23)
        db = {"races": []}
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(main, "SEEN", Path(tmp) / "vistos.json"), \
             mock.patch("scraper.net.get", side_effect=fake_sources) as get, \
             mock.patch.object(sources, "list_runninglife", return_value=[]), \
             mock.patch.object(sources, "list_carreraspopulares", return_value=[]), \
             mock.patch.object(sources, "list_lineadesalida", return_value=[]):
            added = main.discover(db, today, {"added": [], "updated": {}})
            self.assertEqual(added, 2)
            opened_first = [c.args[0] for c in get.call_args_list if "/carrera/" in c.args[0] or "/es/races/" in c.args[0]]
            get.reset_mock()
            db2 = {"races": []}   # aunque no estén en los datos, ya se vieron: no se vuelven a abrir
            main.discover(db2, today, {"added": [], "updated": {}})
            opened_second = [c.args[0] for c in get.call_args_list if "/carrera/" in c.args[0] or "/es/races/" in c.args[0]]
        self.assertEqual(len(opened_first), 2)
        self.assertEqual(opened_second, [])
        names = sorted(r["name"] for r in db["races"])
        self.assertEqual(names, ["10K Ciudad de Ejemplo", "XI Carrera Solidaria Puerto de Ejemplo"])


class MediaTests(unittest.TestCase):
    PAGE = """<html><head><meta property="og:image" content="/img/logo.png">
    <meta name="twitter:image" content="/img/foto-salida.jpg"></head><body>
    <img src="/up/2026/cartel-10k.jpg" alt="Cartel 10K"><img src="/img/patrocinadores.png" alt="Patrocinadores">
    <a href="https://www.strava.com/routes/123">Ver recorrido en Strava</a><a href="/docs/circuito.pdf">Circuito</a>
    <a href="https://facebook.com/x/ruta">ruta</a></body></html>"""

    def test_best_image_prefers_poster_and_skips_logos(self):
        img, score = parse.best_image(self.PAGE, "https://x.es/")
        self.assertEqual(img, "https://x.es/up/2026/cartel-10k.jpg")
        self.assertGreater(score, 4)
        self.assertEqual(parse.best_image("<html><meta property='og:image' content='/logo.png'></html>", "https://x.es/"), (None, 0))

    def test_find_route(self):
        self.assertEqual(parse.find_route(self.PAGE, "https://x.es/"), "https://www.strava.com/routes/123")
        self.assertEqual(parse.find_route('<a href="/files/10k.gpx">Track</a>', "https://x.es/"), "https://x.es/files/10k.gpx")
        self.assertIsNone(parse.find_route('<a href="/contacto">Contacto</a>', "https://x.es/"))

    def test_route_rejects_other_races_news_and_sitemaps(self):
        cal = """<a href="https://running.life/en/event/carrera-solidaria-ruta-091">Carrera Solidaria Ruta 091</a>
        <a href="https://www.mundodeportivo.com/running/20261022/1/ruta-correr-montana">Ruta para correr</a>"""
        self.assertIsNone(parse.find_route(cal, "https://running.life/en/event/x", strict=True))
        self.assertIsNone(parse.find_route('<a href="/es/mapa-web/">Mapa web</a>', "https://www.fdmvalencia.es/"))
        self.assertEqual(parse.find_route('<a href="/recorrido-10k/">Recorrido</a>', "https://www.mi10k.es/"),
                         "https://www.mi10k.es/recorrido-10k/")
        self.assertFalse(parse.is_route_url("https://running.life/en/event/carrera-solidaria-ruta-091-torremolinos"))
        self.assertTrue(parse.is_route_url("https://www.strava.com/routes/123"))
        self.assertFalse(parse.is_route_url("https://sportmaniacs.com/es/services/inscription/pulpi---circuito-de-carreras-populares-2026"))
        self.assertTrue(parse.is_route_url("https://www.mi10k.es/docs/circuito-2026.pdf"))

    def test_tags_follow_km(self):
        self.assertEqual(parse.tags_from_km("21,097 km · 10 km"), ["21K", "10K"])
        self.assertEqual(parse.tags_from_km("7,5 km"), ["7,5K"])
        db = {"races": [{"id": "a", "name": "Media Maratón de X", "date": "2026-11-01", "km": "10 km", "distances": ["21K"]}]}
        main.tidy(db)
        self.assertEqual(db["races"][0]["distances"], ["10K"])

    def test_media_pass_fills_missing_poster_and_route(self):
        today = date(2026, 10, 23)
        db = {"races": [{"id": "a", "name": "10K X", "date": "2026-11-01", "source": "https://cal.es/a"}]}
        with mock.patch("scraper.net.get", return_value=(self.PAGE, "https://cal.es/a", "text/html")):
            main.media(db, today, {"added": [], "updated": {}})
        r = db["races"][0]
        self.assertEqual(r["banner"], "https://cal.es/up/2026/cartel-10k.jpg")
        self.assertEqual(r["route"], "https://www.strava.com/routes/123")
        self.assertEqual(r["mediaChecked"], "2026-10-23")


if __name__ == "__main__":
    unittest.main()
