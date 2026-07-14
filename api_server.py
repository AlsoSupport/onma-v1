"""
anim3 API server
-----------------
Envuelve la librería `filoani` (JKAnime V2 + AnimeFLV) en una API HTTP simple,
para que la app PHP (en InfinityFree) consuma esto por fetch/cURL.

Deploy: bot-hosting.net (proceso Python 24/7)
Run:    uvicorn api_server:app --host 0.0.0.0 --port $PORT

Endpoints:
  GET /health
  GET /search?q=tokyo ghoul
  GET /latest
  GET /alphabet?letter=A
  GET /schedule
  GET /top?season=Invierno&year=2020
  GET /filter?genre=isekai&year=2024
  GET /anime/{slug}                     -> getExtraInfo
  GET /servers/{slug}/{episode}         -> getAnimeServers (con fallback)
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("anim3-api")

app = FastAPI(title="anim3 unified anime API", version="0.1.0")

# CORS abierto: InfinityFree consume esto server-side (PHP cURL) pero
# lo dejamos abierto por si en algún momento se llama desde el navegador.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Import perezoso de filoani con manejo de fallas ------------------------
# La librería es muy nueva (v0.1.1), así que probamos varios posibles nombres
# de import/función y degradamos con claridad si algo no existe.

_jk = None
_flv = None
_import_error = None

try:
    from filoani import JkAnime, UnifiedAnimeAPI
    _jk_cls = JkAnime
    _unified_cls = UnifiedAnimeAPI
except Exception as e:  # pragma: no cover
    _jk_cls = None
    _unified_cls = None
    _import_error = str(e)
    log.error(f"No pude importar filoani: {e}")

try:
    from filoani.providers.animeflv import AnimeFLV  # nombre tentativo
    _flv_cls = AnimeFLV
except Exception:
    _flv_cls = None


def get_jk():
    global _jk
    if _jk is None and _jk_cls:
        _jk = _jk_cls()
    return _jk


def get_flv():
    global _flv
    if _flv is None and _flv_cls:
        try:
            _flv = _flv_cls()
        except Exception as e:
            log.warning(f"AnimeFLV no disponible: {e}")
    return _flv


@app.on_event("startup")
async def startup():
    if _import_error:
        log.error(f"filoani no se pudo cargar en absoluto: {_import_error}")


@app.get("/health")
async def health():
    return {
        "status": "ok" if _jk_cls else "degraded",
        "jkanime": bool(_jk_cls),
        "animeflv": bool(_flv_cls),
        "import_error": _import_error,
    }


def _safe_call(fn, *args, **kwargs):
    """Ejecuta fn devolviendo (resultado, error) sin tirar excepción cruda."""
    try:
        result = fn(*args, **kwargs)
        return result, None
    except Exception as e:
        log.warning(f"Fallo llamando {fn}: {e}")
        return None, str(e)


@app.get("/search")
async def search(q: str = Query(..., min_length=1)):
    """Busca en JKAnime primero; si no hay resultados, intenta AnimeFLV."""
    jk = get_jk()
    if not jk:
        raise HTTPException(503, "Proveedor JKAnime no disponible en el servidor")

    result, err = _safe_call(jk.search, q)
    if result and (result.get("animes") if isinstance(result, dict) else result):
        return {"provider": "jkanime", "data": result}

    flv = get_flv()
    if flv:
        result2, err2 = _safe_call(flv.search, q)
        if result2:
            return {"provider": "animeflv", "data": result2}
        return {"provider": None, "data": None, "error": err2 or err}

    return {"provider": None, "data": None, "error": err or "Sin resultados"}


@app.get("/latest")
async def latest():
    jk = get_jk()
    if not jk:
        raise HTTPException(503, "Proveedor no disponible")
    result, err = _safe_call(jk.latestAnimeAdded)
    if err:
        raise HTTPException(502, f"Error consultando proveedor: {err}")
    return {"provider": "jkanime", "data": result}


@app.get("/alphabet")
async def alphabet(letter: str = Query(..., min_length=1, max_length=1)):
    jk = get_jk()
    if not jk:
        raise HTTPException(503, "Proveedor no disponible")
    result, err = _safe_call(jk.byAlphabet, letter.upper())
    if err:
        raise HTTPException(502, f"Error consultando proveedor: {err}")
    return {"provider": "jkanime", "data": result}


@app.get("/schedule")
async def schedule():
    jk = get_jk()
    if not jk:
        raise HTTPException(503, "Proveedor no disponible")
    result, err = _safe_call(jk.schedule)
    if err:
        raise HTTPException(502, f"Error consultando proveedor: {err}")
    return {"provider": "jkanime", "data": result}


@app.get("/top")
async def top(season: str = Query(...), year: Optional[str] = Query(None)):
    jk = get_jk()
    if not jk:
        raise HTTPException(503, "Proveedor no disponible")
    result, err = _safe_call(jk.top, season, year)
    if err:
        raise HTTPException(502, f"Error consultando proveedor: {err}")
    return {"provider": "jkanime", "data": result}


@app.get("/filter")
async def filter_anime(
    genre: Optional[str] = None,
    demography: Optional[str] = None,
    category: Optional[str] = None,
    type: Optional[str] = None,
    state: Optional[str] = None,
    year: Optional[str] = None,
    season: Optional[str] = None,
    orderBy: Optional[str] = None,
):
    jk = get_jk()
    if not jk:
        raise HTTPException(503, "Proveedor no disponible")
    query = {k: v for k, v in {
        "genre": genre, "demography": demography, "category": category,
        "type": type, "state": state, "year": year, "season": season,
        "orderBy": orderBy,
    }.items() if v is not None}
    result, err = _safe_call(jk.filter, query=query)
    if err:
        raise HTTPException(502, f"Error consultando proveedor: {err}")
    return {"provider": "jkanime", "data": result}


@app.get("/anime/{slug}")
async def anime_info(slug: str):
    """Info extendida (géneros, episodios, estudio, etc)."""
    jk = get_jk()
    if not jk:
        raise HTTPException(503, "Proveedor no disponible")
    result, err = _safe_call(jk.getExtraInfo, slug)
    if err or not result:
        raise HTTPException(404, f"No se encontró info para '{slug}': {err or 'vacío'}")
    return {"provider": "jkanime", "slug": slug, "data": result}


@app.get("/servers/{slug}/{episode}")
async def servers(slug: str, episode: int):
    """
    Links de reproducción para un episodio. Usa la API unificada si está
    disponible (valida embeds cross-provider); si no, cae a JkAnime directo.
    """
    if _unified_cls:
        result, err = _safe_call(
            lambda: _unified_cls("jkanime").unified_servers(slug, episode, validate=True)
        )
        if result:
            return {"provider": "unified", "slug": slug, "episode": episode, "servers": result}

    jk = get_jk()
    if not jk:
        raise HTTPException(503, "Proveedor no disponible")
    result, err = _safe_call(jk.getAnimeServers, slug, episode)
    if err or not result:
        raise HTTPException(404, f"No hay servidores para '{slug}' ep {episode}: {err or 'vacío'}")
    return {"provider": "jkanime", "slug": slug, "episode": episode, "servers": result}
