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
             mock.patch("scraper.net.probe", side_effect=lambda u: (True, u, u.endswith(".pdf"))), \
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
        self.assertTrue(parse.is_route_url("https://es.wikiloc.com/rutas-carrera/media-maraton-montehermoso-2025-123456"))
        self.assertFalse(parse.is_route_url("https://www.wikiloc.com"))
        self.assertFalse(parse.is_route_url("https://es.wikiloc.com/rutas/carrera/espana/extremadura/montehermoso"))
        self.assertFalse(parse.is_route_url("https://sportmaniacs.com/es/services/inscription/pulpi---circuito-de-carreras-populares-2026"))
        self.assertTrue(parse.is_route_url("https://www.mi10k.es/docs/circuito-2026.pdf"))

    def test_tags_follow_km(self):
        self.assertEqual(parse.tags_from_km("21,097 km · 10 km"), ["21K", "10K"])
        self.assertEqual(parse.tags_from_km("7,5 km"), ["7,5K"])
        db = {"kmV2": "x", "races": [{"id": "a", "name": "Carrera de X", "date": "2026-11-01", "km": "10 km", "distances": ["21K"]}]}
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


class RegulationTests(unittest.TestCase):
    def test_prefers_pdf_and_skips_privacy(self):
        html = """<a href="/privacidad">Política de privacidad y protección de datos</a>
        <a href="/reglamento/">Reglamento</a>
        <a href="/docs/Reglamento-2026.pdf">Descargar reglamento</a>"""
        self.assertEqual(parse.find_regulation(html, "https://x.es/"), "https://x.es/docs/Reglamento-2026.pdf")
        self.assertIsNone(parse.find_regulation('<a href="/rgpd">Reglamento general de protección de datos</a>', "https://x.es/"))
        self.assertTrue(parse.is_document("https://drive.google.com/file/d/abc/view"))

    def test_base_href_and_spaces(self):
        html = '<base href="https://www.babelsport.com/"><a href="userfiles/e4ff_Reglamento Carrera 2026.pdf">Reglamento</a>'
        self.assertEqual(parse.find_regulation(html, "https://www.babelsport.com/evento/x-2026/Reglamento"),
                         "https://www.babelsport.com/userfiles/e4ff_Reglamento%20Carrera%202026.pdf")

    def test_broken_pdf_falls_back_to_page(self):
        def probe(u):
            return (not u.endswith(".pdf"), u, False)   # el PDF devuelve una página: no vale
        with mock.patch("scraper.net.probe", side_effect=probe):
            self.assertEqual(enrich.resolve_regulation("https://deporchip.com/r.pdf", found_on="https://x.es/carrera"),
                             "https://x.es/carrera")
        with mock.patch("scraper.net.probe", return_value=(False, "u", False)):
            self.assertIsNone(enrich.resolve_regulation("https://deporchip.com/r.pdf"))

    def test_resolve_page_to_pdf(self):
        page = '<h1>Reglamento</h1><a href="/wp-content/uploads/2026/09/Normativa-10K.pdf">Normativa 10K (PDF)</a>'
        with mock.patch("scraper.net.probe", side_effect=lambda u: (True, u, u.endswith(".pdf"))), \
             mock.patch("scraper.net.get", return_value=(page, "https://x.es/reglamento/", "text/html")):
            self.assertEqual(enrich.resolve_regulation("https://x.es/reglamento/"),
                             "https://x.es/wp-content/uploads/2026/09/Normativa-10K.pdf")
        with mock.patch("scraper.net.probe", side_effect=lambda u: (True, u, False)), \
             mock.patch("scraper.net.get", return_value=("<p>Texto del reglamento en la página</p>", "https://x.es/r", "text/html")):
            self.assertEqual(enrich.resolve_regulation("https://x.es/r"), "https://x.es/r")
        with mock.patch("scraper.net.probe", side_effect=lambda u: (True, u, True)), \
             mock.patch("scraper.net.get", return_value=(b"%PDF", "https://x.es/r.pdf", "application/pdf")):
            self.assertEqual(enrich.resolve_regulation("https://x.es/descarga?id=3"), "https://x.es/r.pdf")


class RegistrationTests(unittest.TestCase):
    def test_states(self):
        st = parse.registration_status
        self.assertEqual(st("<p>¡Dorsales agotados! Gracias a todos.</p>"), "agotada")
        self.assertEqual(st("<p>Plazo de inscripción cerrado</p>"), "cerrada")
        self.assertEqual(st("<p>Inscripciones próximamente</p>"), "proximamente")
        self.assertEqual(st("<p>Inscripciones abiertas hasta el 20 de noviembre</p>"), "abierta")
        self.assertIsNone(st("<p>10K por las calles del centro</p>"))
        self.assertIsNone(st('<a class="btn">Inscríbete</a>'))                    # en una web cualquiera no basta
        self.assertEqual(st('<a class="btn">Inscríbete</a>', True), "abierta")   # en una plataforma, sí
        ld = """<script type="application/ld+json">{"@type":"SportsEvent","name":"X","startDate":"2026-11-01",
        "offers":{"@type":"Offer","availability":"https://schema.org/SoldOut"}}</script>"""
        self.assertIsNone(st(ld))   # el «SoldOut» oculto no basta
        # Rockthesport: la página dice «Inscripciones abiertas» aunque el dato oculto diga SoldOut
        self.assertEqual(st(ld + "<p>Inscripciones abiertas</p>"), "abierta")
        self.assertEqual(st(ld + "<p>Inscripciones cerradas desde 22 oct 2026</p>"), "cerrada")

    def test_pass_checks_near_races_daily(self):
        today = date(2026, 10, 23)
        db = {"races": [
            {"id": "a", "name": "A", "date": "2026-11-01", "official": True, "url": "https://www.rockthesport.com/es/evento/a"},
            {"id": "b", "name": "B", "date": "2026-11-02", "official": True, "url": "https://b.es/", "inscripcionAt": "2026-10-23"},
            {"id": "c", "name": "C", "date": "2027-01-20", "official": True, "url": "https://c.es/", "inscripcionAt": "2026-10-20"},
        ]}
        with mock.patch("scraper.net.get", return_value=("<p>Inscripciones abiertas</p>", "u", "text/html")) as get:
            main.registrations(db, today, {"added": [], "updated": {}})
        self.assertEqual(get.call_count, 1)    # b ya se miró hoy; c (lejana) se miró hace 3 días
        self.assertEqual(db["races"][0]["inscripcion"], "abierta")


class RecheckTests(unittest.TestCase):
    def test_near_races_are_retried_sooner(self):
        today = date(2026, 10, 23)
        base = {"name": "X", "official": True, "url": "https://x.es/", "checkedAt": "2026-10-21"}
        self.assertTrue(enrich.needs_work({**base, "date": "2026-10-25"}, today))          # este fin de semana
        self.assertTrue(enrich.needs_work({**base, "date": "2026-11-01"}, today))          # en 9 días: a diario
        self.assertFalse(enrich.needs_work({**base, "date": "2026-11-01", "checkedAt": "2026-10-23"}, today))
        self.assertFalse(enrich.needs_work({**base, "date": "2026-12-20"}, today))         # lejana: cada 7 días

    def test_fill_from_calendar_page_when_official_lacks_data(self):
        today = date(2026, 10, 23)
        sm = """<script type="application/ld+json">{"@type":"SportsEvent","name":"10K X","startDate":"2026-10-25T10:00:00+02:00",
        "offers":{"@type":"Offer","price":"12"}}</script><p>Recorrido de 10 km por el centro</p>"""
        r = {"id": "x", "name": "10K X", "date": "2026-10-25", "source": "https://sportmaniacs.com/es/races/x",
             "alt": ["https://sportplan.es/es/events/x"]}
        def get(u, binary=False):
            return (sm, u, "text/html") if "sportmaniacs" in u else (None, u, None)
        with mock.patch("scraper.net.get", side_effect=get) as g, mock.patch("scraper.net.probe", return_value=(False, "", False)):
            upd = enrich.enrich(r, today)
        self.assertEqual(upd.get("time"), "10:00")
        self.assertEqual(upd.get("price"), "12 €")
        self.assertEqual(upd.get("km"), "10 km")
        self.assertFalse(any("sportplan" in c.args[0] for c in g.call_args_list))   # la fuente bloqueada no se abre


class RouteSiteTests(unittest.TestCase):
    def test_embedded_maps_and_images(self):
        fr = parse.find_route_media
        self.assertEqual(fr('<iframe src="https://www.google.com/maps/d/embed?mid=1AbC_x&ehbc=2E312F"></iframe>', "https://x.es/")[0],
                         "https://www.google.com/maps/d/viewer?mid=1AbC_x")
        self.assertEqual(fr('<iframe src="https://es.wikiloc.com/wikiloc/spatialArtifacts.do?event=view&id=98765&measures=on"></iframe>', "https://x.es/")[0],
                         "https://es.wikiloc.com/wikiloc/view.do?id=98765")
        self.assertEqual(fr('<div class="strava-embed-placeholder" data-embed-type="route" data-embed-id="321"></div>', "https://x.es/")[0],
                         "https://www.strava.com/routes/321")
        self.assertEqual(fr('<img src="/wp-content/uploads/2026/09/recorrido-10k.jpg" alt="">', "https://x.es/")[0],
                         "https://x.es/wp-content/uploads/2026/09/recorrido-10k.jpg")
        self.assertIsNone(fr('<img src="/logo.png" alt="Logo"><iframe src="https://www.youtube.com/embed/x"></iframe>', "https://x.es/")[0])

    def test_route_page_inside_site(self):
        home = '<a href="/recorrido/">Recorrido</a>'
        page = '<h1>Recorrido</h1><iframe src="https://www.google.com/maps/d/embed?mid=ZZZ"></iframe>'
        def get(u, binary=False):
            return (page if "recorrido" in u else home), u, "text/html"
        with mock.patch("scraper.net.get", side_effect=get):
            self.assertEqual(enrich.route_from_site("https://mi10k.es/"), "https://www.google.com/maps/d/viewer?mid=ZZZ")


class TimeZoneTests(unittest.TestCase):
    def test_local_time(self):
        lt = parse.local_time
        self.assertEqual(lt("2026-10-24T09:30:00+02:00"), "09:30")
        self.assertEqual(lt("2026-10-24T07:30:00Z"), "09:30")                 # UTC → Península (verano)
        self.assertEqual(lt("2026-10-24T07:30:00Z", "Canarias"), "08:30")     # UTC → Canarias
        self.assertEqual(lt("2026-11-22T09:00:00Z"), "10:00")                 # invierno
        self.assertEqual(lt("2026-10-24T10:00"), "10:00")                     # sin zona: tal cual
        self.assertEqual(lt("2026-10-25T10:00:00+02:00"), "10:00")            # desfase local mal puesto: la hora escrita
        self.assertIsNone(lt("2026-10-24T00:00:00"))
        self.assertIsNone(lt("2026-10-24"))


class ShareTests(unittest.TestCase):
    def test_short_links_in_tweets(self):
        from scraper import share, xpost
        r = {"id": "carrera-popular-aesan-2026-1024", "name": "Carrera Popular AESAN", "date": "2026-10-24",
             "time": "08:30", "city": "Madrid", "region": "Comunidad de Madrid", "km": "5 km"}
        code = share.short_code(r["id"])
        self.assertLessEqual(len(code), 7)
        self.assertEqual(share.share_url(r), f"https://alexample.github.io/RunningSpain/c/{code}.html")
        with mock.patch("scraper.shorten.load", return_value={}):
            self.assertIn(share.share_url(r), xpost.compose(r, con_enlace=True))
        self.assertIn('href="https://alexample.github.io/RunningSpain/#c-carrera-popular-aesan-2026-1024"', share.page(r))


class ShortenTests(unittest.TestCase):
    def test_ensure_creates_once_and_tweets_use_it(self):
        import tempfile
        from scraper import shorten, xpost
        races = [{"id": "b", "name": "B", "date": "2026-12-01"}, {"id": "a", "name": "A", "date": "2026-11-01", "city": "Lugo"}]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(shorten, "FILE", Path(tmp) / "c.json"), \
             mock.patch.object(shorten, "shorten", side_effect=lambda u: "https://is.gd/" + u[-12:-5]) as sh, \
             mock.patch("time.sleep"):
            d = shorten.ensure(races, must=["b"], limit=1, log=lambda m: None)
            self.assertEqual(list(d), ["b"])               # primero las que se van a tuitear
            shorten.ensure(races, limit=5, log=lambda m: None)
            self.assertEqual(sh.call_count, 2)             # «b» no se vuelve a acortar
            self.assertIn(shorten.load()["a"], xpost.compose(races[1], con_enlace=True))


class LimpiezaTests(unittest.TestCase):
    """Duplicadas, km y carteles (octubre 2026)."""

    def test_km_ignora_avituallamientos_y_otras_carreras(self):
        ex = parse.extract_km
        self.assertEqual(ex("10 KILÓMETROS HOMOLOGADOS 05 KM AVITUALLAMIENTO 01 KM 02 KM 03 KM 04 KM", "Derbi"), "10 km")
        self.assertEqual(ex("x" * 300 + " 5 km Cursa Events nearby Nov 14 Avià | 27 km from Solsona Trail Run 18 km", "Cursa X"), "5 km")
        self.assertEqual(ex("Distancia de 21,097 km. Avituallamientos en el km 5, 10 y 15.", "Media Maratón de T"), "21,097 km")
        self.assertEqual(ex("Viento 9.5 km/h, 19 km/h", "10K Halloween"), "10 km")
        self.assertEqual(ex("Un recorrido de 7,5 km. Avituallamiento a los 4 km. Situado a 2 km del centro.", "Carrera X"), "7,5 km")
        self.assertTrue(parse.km_dudosos("27 km · 22 km · 16 km · 10 km", "10K de Carabanchel"))
        self.assertTrue(parse.km_dudosos("10 km", "Media Maratón de Talavera"))
        self.assertFalse(parse.km_dudosos("21,097 km · 10 km", "Media Maratón de X"))

    def test_misma_carrera_con_fechas_distintas(self):
        a = {"id": "a", "name": "Cursa Popular Vila de Sant Boi", "city": "Sant Boi de Llobregat", "date": "2026-11-15",
             "source": "https://running.life/en/event/x"}
        b = {"id": "b", "name": "Cursa Popular Vila de Sant Boi", "city": "Sant Boi de Llobregat", "date": "2026-11-22",
             "source": "https://sportplan.es/es/events/x", "banner": "https://x.es/cartel.jpg"}
        c = {"id": "c", "name": "5K de Sant Boi", "city": "Sant Boi de Llobregat", "date": "2026-12-05", "source": "https://y"}
        d = {"id": "d", "name": "10K de Sant Boi", "city": "Sant Boi de Llobregat", "date": "2026-12-05", "source": "https://z"}
        self.assertTrue(main.same_race_loose(a, b))
        self.assertFalse(main.same_race_loose(c, d))
        db = {"races": [a, b, c, d]}
        self.assertEqual(main.merge_dups(db, {"added": [], "updated": {}}), 1)
        self.assertEqual(len(db["races"]), 3)
        kept = db["races"][0] if db["races"][0]["id"] in ("a", "b") else next(r for r in db["races"] if r["id"] in ("a", "b"))
        self.assertEqual(kept["date"], "2026-11-15")          # Sportplan ya no se revisa: gana running.life
        self.assertEqual(kept["otraFecha"], "2026-11-22")
        self.assertEqual(kept["banner"], "https://x.es/cartel.jpg")

    def test_la_web_oficial_decide_la_fecha(self):
        a = {"id": "a", "name": "La Palauenca", "city": "Palau", "date": "2026-11-15", "official": True, "url": "https://palauenca.cat/",
             "source": "https://running.life/en/event/p"}
        b = {"id": "b", "name": "La Palauenca", "city": "Palau", "date": "2026-11-22", "source": "https://sportplan.es/es/events/p"}
        db = {"races": [a, b]}
        with mock.patch.object(enrich, "fetch_text", return_value=("Diumenge 22 de novembre de 2026, sortida a les 10h", None, "")):
            main.merge_dups(db)
        self.assertEqual(db["races"][0]["date"], "2026-11-22")
        self.assertTrue(db["races"][0]["fechaOk"])
        self.assertFalse(db["races"][0].get("otraFecha"))
        self.assertTrue(parse.date_in_text("2026-11-22", "NOV 22 2026"))
        self.assertFalse(parse.date_in_text("2026-11-15", "domingo 22 de noviembre"))

    def test_carteles(self):
        h = ('<img src="https://l.net/storage/miniaturas/1min.jpg" alt="Cartel carrera">'
             '<img src="https://l.net/storage/carteles/1cartelCuatroMillas26.jpg" alt="...">')
        self.assertEqual(parse.best_image(h, "https://l.net/c", "Cuatro Millas")[0], "https://l.net/storage/carteles/1cartelCuatroMillas26.jpg")
        self.assertEqual(parse.best_image('<meta property="og:image" content="https://e.cat/img/tast-2026-social.jpg">', "https://e.cat/")[0],
                         "https://e.cat/img/tast-2026-social.jpg")
        self.assertEqual(parse.best_image('<meta property="og:image" content="https://www.carreraspopulares.com/calendario/carteles_def/cartel_def_3.jpg">'
                                          '<img class="event-card-thumb" src="https://x.com/Cartel-otra.jpg">', "https://r.life/e"), (None, 0))
        self.assertEqual(parse.best_image('<img src="f/21k-huelva_1.jpg" alt="21K Huelva">', "https://h.com/21k/", "21K Ciudad de Huelva")[0],
                         "https://h.com/21k/f/21k-huelva_1.jpg")
        db = {"races": [{"id": str(i), "name": f"Carrera {i}", "date": "2026-11-01",
                         "banner": "https://sportmaniacs.com/images/share/sportmaniacs-race.jpg"} for i in range(2)]}
        main.tidy(db)
        self.assertFalse(any(r.get("banner") for r in db["races"]))


class TarjetaTests(unittest.TestCase):
    def test_tarjeta_propia_para_x(self):
        import tempfile
        from scraper import share, tarjeta
        r = {"id": "cursa-x-2026-1101", "name": "Cursa de les Caves", "date": "2026-11-01", "time": "10:00", "city": "Lavern",
             "region": "Cataluña", "km": "10 km", "distances": ["10K"], "addedAt": "2026-10-27"}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tarjeta, "OUT", Path(d)), mock.patch.object(tarjeta, "INDICE", Path(d) / "i.json"):
            self.assertEqual(tarjeta.asegurar([r], date(2026, 10, 27), log=lambda *_: None, short_code=share.short_code), 1)
            code = share.short_code(r["id"])
            self.assertTrue((Path(d) / f"{code}.jpg").exists())
            pagina = share.page(r)
            self.assertIn(f'content="https://alexample.github.io/RunningSpain/c/img/{code}.jpg"', pagina)
            self.assertIn('name="twitter:image"', pagina)
            self.assertNotIn("http-equiv=\"refresh\"", pagina)
            self.assertEqual(tarjeta.asegurar([r], date(2026, 10, 27), log=lambda *_: None, short_code=share.short_code), 0)   # sin cambios


class IATests(unittest.TestCase):
    def test_solo_excepcional_y_validado(self):
        from scraper import ia
        hoy = date(2026, 10, 27)
        base = {"name": "10K de Prueba", "city": "X", "region": "Y", "official": True, "url": "https://x.es/"}
        db = {"races": [
            dict(base, id="vieja", date="2026-11-05", addedAt="2026-10-20"),                       # sí: publicada hace días, próxima
            dict(base, id="nueva", date="2026-11-05", addedAt="2026-10-26"),                       # no: el robot aún tiene tiempo
            dict(base, id="lejos", date="2027-01-10", addedAt="2026-10-01"),                       # no: no es próxima
            dict(base, id="hecha", date="2026-11-05", addedAt="2026-10-01", banner="b", km="10 km", route="r", inscripcion="abierta"),
            dict(base, id="preguntada", date="2026-11-05", addedAt="2026-10-01", iaAt="2026-10-25"),
        ]}
        self.assertEqual([r["id"] for r in ia.candidatas(db, hoy)], ["vieja"])
        r = dict(db["races"][0])
        mat = {"imagenes": [{"u": "https://x.es/cartel.jpg", "alt": ""}], "enlaces": [{"u": "https://x.es/recorrido.gpx", "t": "Track"}]}
        puesto = ia._aplica(r, {"km": "10 km", "inscripcion": "abierta", "cartel": 0, "recorrido": 0}, mat, hoy)
        self.assertEqual(sorted(puesto), ["banner", "inscripcion", "km", "route"])
        r2 = dict(db["races"][0])
        self.assertEqual(ia._aplica(r2, {"km": "27 km · 22 km · 16 km · 3 km", "inscripcion": "quizás", "cartel": 7, "recorrido": None}, mat, hoy), [])


if __name__ == "__main__":
    unittest.main()
