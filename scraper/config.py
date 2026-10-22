"""Configuración del robot de RunningSpain."""

# Días hacia delante que se recogen (la web muestra 3 meses; se recoge algo más
# para que las carreras aparezcan con los datos ya completos).
DAYS_AHEAD = 110
# Las carreras pasadas se borran tras este número de días.
KEEP_PAST_DAYS = 7

# Límites por ejecución, para ser respetuosos con las webs y no alargar el robot.
MAX_EVENT_PAGES = 700      # fichas de calendario abiertas por ejecución
MAX_ENRICH = 180           # webs oficiales revisadas por ejecución
RECHECK_DAYS = 7           # una ficha sin web oficial se vuelve a intentar pasados N días
REQUEST_DELAY = 1.2        # segundos entre peticiones al mismo dominio
TIMEOUT = 25

USER_AGENT = (
    "RunningSpainBot/1.0 (+https://github.com/alexample/RunningSpain; "
    "calendario gratuito de carreras populares)"
)

# Páginas de calendario por provincia en sportplan.es (cada una cubre su zona).
SPORTPLAN_REGIONS = [
    "madrid", "barcelona", "valencia", "sevilla", "malaga", "cordoba", "cadiz",
    "granada", "almeria", "jaen", "huelva", "zaragoza", "huesca", "teruel",
    "asturias", "santander", "pamplona", "la-rioja", "bilbao", "san-sebastian",
    "vitoria", "badajoz", "caceres", "palma", "ibiza", "menorca", "tenerife",
    "gran-canaria", "murcia", "alicante", "castellon", "girona", "tarragona",
    "lleida", "valladolid", "salamanca", "leon", "burgos", "palencia", "zamora",
    "segovia", "avila", "soria", "toledo", "ciudad-real", "albacete", "cuenca",
    "guadalajara", "a-coruna", "vigo", "ourense", "lugo", "santiago-de-compostela",
    "ceuta", "melilla",
]
SPORTPLAN_REGION_URL = "https://sportplan.es/es/regions/{slug}"
SPORTPLAN_SERIES = ["https://sportplan.es/es/series/san-silvestre"]

# Calendarios por distancia de running.life (paginados con ?page=N).
RUNNINGLIFE_LISTS = [
    "https://running.life/half-marathons/spain",
    "https://running.life/marathon-calendar/spain",
    "https://running.life/10k-races/spain",
]
RUNNINGLIFE_MAX_PAGES = 25

# Dominios que NO son webs oficiales (calendarios, agregadores, redes sociales).
NOT_OFFICIAL = {
    "sportplan.es", "running.life", "haid.app", "finishers.com", "correrjuntos.com",
    "trainerday.com", "ahotu.com", "worldsmarathons.com", "planomato.com",
    "festivalesdeespana.com", "endorphinsrunning.com", "runnea.com", "marathons.com",
    "hdsports.org", "milesrepublic.com", "gotrail.run", "runningcoach.me",
    "clubrunning.es", "corredorespopulares.es", "carrerasdemontana.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "tiktok.com", "linkedin.com", "wa.me", "whatsapp.com", "t.me", "google.com",
    "goo.gl", "maps.app.goo.gl", "apple.com", "strava.com", "wikipedia.org",
    "wikiloc.com", "booking.com", "hostelworld.com", "intervals.icu",
    "marathon-index.com", "runabc.co.uk", "mybestruns.com", "watchathletics.com",
    "trainerday.com", "events-app.eu.trainerday.com",
}

# Plataformas de inscripción que valen como página oficial de la carrera.
SIGNUP_PLATFORMS = {
    "rockthesport.com", "runrunsports.com", "deporticket.com", "sportmaniacs.com",
    "timingsys.com", "championchip.com", "championchipnorte.com", "xipgroc.cat",
    "lineadesalida.net", "evedeport.es", "youevent.es", "cronochip.com",
    "mychip.es", "chiptiming.es", "orycronsport.com", "crono4sports.es",
    "sportchip.net", "empa-t.com", "321go.es", "dorsalchip.es", "gesconchip.es",
    "toprun.es", "inscripcions.cat", "runatica.com", "global-tempo.com",
    "rfea.es", "masatletismo.com", "eventbrite.es", "eventbrite.com",
}

# Palabras que indican que NO es una carrera de asfalto.
NOT_ROAD = [
    "trail", "montaña", "montana", "muntanya", "mendi", "skyrace", "ultra trail",
    "cross", "obstacul", "obstácul", "ocr", "spartan", "triatl", "duatl",
    "acuatl", "swimrun", "btt", "bike", "bici", "ciclis", "marcha nórdica",
    "marcha nordica", "senderis", "vertical", "kv ", "backyard", "hyrox",
    "orientaci", "canicross", "infantil", "kids", "mini ", "caminata",
]

PROVINCE_TO_REGION = {
    "almería": "Andalucía", "almeria": "Andalucía", "cádiz": "Andalucía", "cadiz": "Andalucía",
    "córdoba": "Andalucía", "cordoba": "Andalucía", "granada": "Andalucía",
    "huelva": "Andalucía", "jaén": "Andalucía", "jaen": "Andalucía",
    "málaga": "Andalucía", "malaga": "Andalucía", "sevilla": "Andalucía",
    "huesca": "Aragón", "teruel": "Aragón", "zaragoza": "Aragón",
    "asturias": "Asturias", "illes balears": "Islas Baleares", "islas baleares": "Islas Baleares",
    "baleares": "Islas Baleares", "mallorca": "Islas Baleares", "menorca": "Islas Baleares",
    "ibiza": "Islas Baleares", "eivissa": "Islas Baleares",
    "las palmas": "Canarias", "santa cruz de tenerife": "Canarias", "tenerife": "Canarias",
    "gran canaria": "Canarias", "lanzarote": "Canarias", "fuerteventura": "Canarias",
    "la palma": "Canarias", "cantabria": "Cantabria",
    "albacete": "Castilla-La Mancha", "ciudad real": "Castilla-La Mancha",
    "cuenca": "Castilla-La Mancha", "guadalajara": "Castilla-La Mancha",
    "toledo": "Castilla-La Mancha",
    "ávila": "Castilla y León", "avila": "Castilla y León", "burgos": "Castilla y León",
    "león": "Castilla y León", "leon": "Castilla y León", "palencia": "Castilla y León",
    "salamanca": "Castilla y León", "segovia": "Castilla y León", "soria": "Castilla y León",
    "valladolid": "Castilla y León", "zamora": "Castilla y León",
    "barcelona": "Cataluña", "girona": "Cataluña", "gerona": "Cataluña",
    "lleida": "Cataluña", "lérida": "Cataluña", "tarragona": "Cataluña",
    "alicante": "Comunidad Valenciana", "alacant": "Comunidad Valenciana",
    "castellón": "Comunidad Valenciana", "castellon": "Comunidad Valenciana",
    "castelló": "Comunidad Valenciana", "valencia": "Comunidad Valenciana",
    "valència": "Comunidad Valenciana",
    "badajoz": "Extremadura", "cáceres": "Extremadura", "caceres": "Extremadura",
    "a coruña": "Galicia", "coruña": "Galicia", "lugo": "Galicia", "ourense": "Galicia",
    "pontevedra": "Galicia",
    "madrid": "Comunidad de Madrid", "murcia": "Región de Murcia",
    "navarra": "Navarra", "nafarroa": "Navarra",
    "álava": "País Vasco", "alava": "País Vasco", "araba": "País Vasco",
    "bizkaia": "País Vasco", "vizcaya": "País Vasco", "gipuzkoa": "País Vasco",
    "guipúzcoa": "País Vasco", "la rioja": "La Rioja", "rioja": "La Rioja",
    "ceuta": "Ceuta", "melilla": "Melilla",
}

# Región por defecto de cada página de sportplan (si la ficha no trae provincia).
SLUG_REGION = {
    "madrid": "Comunidad de Madrid", "barcelona": "Cataluña", "valencia": "Comunidad Valenciana",
    "sevilla": "Andalucía", "malaga": "Andalucía", "cordoba": "Andalucía", "cadiz": "Andalucía",
    "granada": "Andalucía", "almeria": "Andalucía", "jaen": "Andalucía", "huelva": "Andalucía",
    "zaragoza": "Aragón", "huesca": "Aragón", "teruel": "Aragón", "asturias": "Asturias",
    "santander": "Cantabria", "pamplona": "Navarra", "la-rioja": "La Rioja",
    "bilbao": "País Vasco", "san-sebastian": "País Vasco", "vitoria": "País Vasco",
    "badajoz": "Extremadura", "caceres": "Extremadura", "palma": "Islas Baleares",
    "ibiza": "Islas Baleares", "menorca": "Islas Baleares", "tenerife": "Canarias",
    "gran-canaria": "Canarias", "murcia": "Región de Murcia",
    "alicante": "Comunidad Valenciana", "castellon": "Comunidad Valenciana",
    "girona": "Cataluña", "tarragona": "Cataluña", "lleida": "Cataluña",
    "valladolid": "Castilla y León", "salamanca": "Castilla y León", "leon": "Castilla y León",
    "burgos": "Castilla y León", "palencia": "Castilla y León", "zamora": "Castilla y León",
    "segovia": "Castilla y León", "avila": "Castilla y León", "soria": "Castilla y León",
    "toledo": "Castilla-La Mancha", "ciudad-real": "Castilla-La Mancha",
    "albacete": "Castilla-La Mancha", "cuenca": "Castilla-La Mancha",
    "guadalajara": "Castilla-La Mancha", "a-coruna": "Galicia", "vigo": "Galicia",
    "ourense": "Galicia", "lugo": "Galicia", "santiago-de-compostela": "Galicia",
    "ceuta": "Ceuta", "melilla": "Melilla",
}

# Modelo opcional para leer reglamentos (solo si existe el secreto ANTHROPIC_API_KEY).
LLM_MODEL = "claude-haiku-5-5"
LLM_MAX_CALLS = 120

# --- Publicación en X (scraper/xpost.py) ---
# Solo publica si existen los secretos X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN y X_ACCESS_SECRET.
X_DESDE = "2026-10-22"     # solo se publican carreras añadidas desde esta fecha (no el atrasado)
X_MAX_POR_EJECUCION = 10   # tope de publicaciones cada vez que pasa el robot
X_CON_ENLACE = False       # True añade el enlace a la web: cada publicación cuesta ~0,20 $ en vez de ~0,015 $
X_WEB = "https://alexample.github.io/RunningSpain/#nuevas"
# Envío a MacroDroid (secreto MACRODROID_WEBHOOK = URL del disparador Webhook de la macro).
# Si existe, el robot NO usa la API de X: manda cada texto al móvil en la variable "tweet".
MACRO_CON_ENLACE = True    # publicando desde la app de X el enlace no cuesta nada
MACRO_PAUSA = 90           # segundos entre un envío y el siguiente (tiempo para publicar cada uno)
# Parámetros que se envían al webhook. Cada uno necesita una variable con el MISMO nombre en la macro,
# o MacroDroid puede ignorar el aviso. Posibles: tweet, carrera, enlace, orden, total, fecha.
MACRO_PARAMS = ["tweet"]
