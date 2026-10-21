# RunningSpain

Calendario de carreras de running en asfalto de toda España para los próximos 3 meses. Un robot gratuito de GitHub lo actualiza cada día.

**Web:** https://alexample.github.io/RunningSpain/

Cada ficha muestra el día, el lugar, la hora de salida, los km, el precio, el reglamento, la web oficial de la carrera y su cartel (cuando el robot los encuentra).

## Cómo funciona

1. Cada día a las 03:17 UTC, GitHub Actions ejecuta `python -m scraper.main`.
2. El robot busca carreras nuevas en calendarios públicos y descarta las de trail, cross y obstáculos.
3. Para cada carrera busca su **web oficial** y, en ella, el reglamento (PDF o página), el cartel, el precio, la hora y los km.
4. Guarda el resultado en `docs/data/carreras.json` y la web (`docs/index.html`) lo muestra.

Las carreras que ya han pasado se borran solas. Si quieres que una ficha no se toque, añade `"locked": true` en el JSON.

## Puesta en marcha

1. **Activar la web:** Settings → Pages → Source: *Deploy from a branch* → Branch: `main`, carpeta `/docs` → Save.
2. **Lanzar el robot a mano la primera vez:** pestaña Actions → *Actualizar carreras* → *Run workflow*.
3. **(Opcional) Lectura de reglamentos con IA:** Settings → Secrets and variables → Actions → *New repository secret* con el nombre `ANTHROPIC_API_KEY`. Sin este secreto el robot funciona igual, solo con reglas de texto.

## Ajustes

Todo está en `scraper/config.py`: días vista, comunidades, límites de páginas por ejecución y la lista de webs que no cuentan como oficiales.

## Pruebas

```bash
pip install -r requirements.txt
python -m unittest discover -s tests
```
