"""
Recolecta noticias de universidades y se queda con las de I+D,
innovación / transferencia tecnológica y emprendimiento.

Lo ejecuta GitHub Actions. Escribe noticias.json en la raíz del repo.
Para agregar una universidad, añade una entrada a FUENTES.
"""

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

SALIDA = Path("noticias.json")
DIAS_A_GUARDAR = 120
MAX_NOTICIAS = 800
TIMEOUT = 25
HEADERS = {"User-Agent": "Mozilla/5.0 (agregador I+D universidades; contacto: rormenom)"}

# Cada fuente prueba sus URLs en orden: primero un feed RSS, si no hay,
# lee la página HTML del listado y extrae los títulos enlazados.
FUENTES = [
    {"sigla": "UdeC", "nombre": "Universidad de Concepción", "conce": True,
     "urls": ["https://noticias.udec.cl/feed/", "https://noticias.udec.cl/"]},
    {"sigla": "UBB", "nombre": "Universidad del Bío-Bío", "conce": True,
     "urls": ["https://noticias.ubiobio.cl/feed/", "https://noticias.ubiobio.cl/"]},
    {"sigla": "UCSC", "nombre": "Universidad Católica de la Santísima Concepción", "conce": True,
     "urls": ["https://ucsc.cl/medios-ucsc/noticias/feed/", "https://ucsc.cl/medios-ucsc/noticias/"]},
    {"sigla": "UDD", "nombre": "Universidad del Desarrollo", "conce": True,
     "urls": ["https://www.udd.cl/feed/", "https://www.udd.cl/noticias/"]},
    {"sigla": "USS", "nombre": "Universidad San Sebastián", "conce": True,
     "urls": ["https://www.uss.cl/feed/", "https://www.uss.cl/noticias/"]},
    {"sigla": "UNAB", "nombre": "Universidad Andrés Bello", "conce": True,
     "urls": ["https://noticias.unab.cl/feed/", "https://noticias.unab.cl/noticias"]},
    {"sigla": "UST", "nombre": "Universidad Santo Tomás", "conce": True,
     "urls": ["https://ust.cl/feed/", "https://ust.cl/formacion-e-identidad/noticias"]},
    {"sigla": "UDLA", "nombre": "Universidad de Las Américas", "conce": True,
     "urls": ["https://actualidad.udla.cl/feed/", "https://actualidad.udla.cl/"]},
    {"sigla": "USM", "nombre": "Universidad Técnica Federico Santa María", "conce": True,
     "urls": ["https://usm.cl/feed/", "https://usm.cl/noticias/"]},
    {"sigla": "3IE-USM", "nombre": "Instituto 3IE (incubadora USM)", "conce": False,
     "urls": ["https://3ie.usm.cl/feed/", "https://3ie.usm.cl/noticias/"]},
    {"sigla": "UCT-DIRITT", "nombre": "UCT, Innovación y Transferencia Tecnológica", "conce": False,
     "urls": ["https://diritt.uct.cl/feed/", "https://diritt.uct.cl/noticias/"]},
]

# Palabras clave (se comparan sin tildes y en minúsculas, solo en el título).
CATEGORIAS = {
    "I+D": [
        r"fondecyt", r"fondef", r"\banid\b", r"fondequip", r"milenio",
        r"(?<!\w)i\s?\+\s?d(\s?\+\s?i)?(?!\w)", r"\binvestigacion(es)?\b",
        r"\binvestigador(a|as|es)?\b", r"\bcientific", r"\bdoctorado",
    ],
    "Innovación y transferencia": [
        r"\bpatent", r"\binapi\b", r"propiedad intelectual", r"transferencia tecnologica",
        r"\blicenci", r"spin.?off", r"\bcorfo\b", r"\bviu\b", r"\binnovacion",
        r"\bprototipo", r"\bfiut?\b", r"base cientifico.?tecnologica", r"\bebct\b",
    ],
    "Emprendimiento": [
        r"start.?up", r"\bemprend", r"\bincubadora", r"\baceleradora", r"\bpitch\b",
        r"\b3ie\b", r"capital semilla", r"\bventure", r"\binversionistas?\b",
    ],
}
EXCLUIR = [r"\badmision\b", r"\bmatricula", r"\bpaes\b", r"\bpostulantes?\b"]

_CAT_RE = {c: [re.compile(p) for p in ps] for c, ps in CATEGORIAS.items()}
_EXC_RE = [re.compile(p) for p in EXCLUIR]


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", texto).strip().lower()


def clasificar(titulo):
    t = normalizar(titulo)
    if any(r.search(t) for r in _EXC_RE):
        return []
    return [c for c, regs in _CAT_RE.items() if any(r.search(t) for r in regs)]


def clave(url):
    return hashlib.sha1(url.split("#")[0].rstrip("/").encode()).hexdigest()[:16]


def leer_feed(contenido, url_base):
    feed = feedparser.parse(contenido)
    items = []
    for e in feed.entries:
        titulo = (e.get("title") or "").strip()
        enlace = urljoin(url_base, e.get("link") or "")
        if not titulo or not enlace:
            continue
        fecha = None
        st = e.get("published_parsed") or e.get("updated_parsed")
        if st:
            fecha = datetime(*st[:6], tzinfo=timezone.utc).isoformat()
        items.append({"titulo": titulo, "url": enlace, "fecha": fecha})
    return items


def leer_html(contenido, url_base):
    """Extrae enlaces que parecen titulares: mismo dominio y texto largo."""
    soup = BeautifulSoup(contenido, "html.parser")
    dominio = ".".join(urlparse(url_base).netloc.split(".")[-2:])  # p. ej. udec.cl
    vistos, items = set(), []
    for a in soup.find_all("a", href=True):
        texto = " ".join(a.get_text(" ", strip=True).split())
        if not (30 <= len(texto) <= 220):
            continue
        enlace = urljoin(url_base, a["href"])
        p = urlparse(enlace)
        if p.scheme not in ("http", "https") or not p.netloc.endswith(dominio):
            continue
        if not [s for s in p.path.split("/") if s] or enlace in vistos:
            continue
        vistos.add(enlace)
        items.append({"titulo": texto, "url": enlace, "fecha": None})
    return items


def recolectar(fuente):
    ultimo_error = "sin respuesta"
    for url in fuente["urls"]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as err:
            ultimo_error = f"{type(err).__name__}"
            continue
        if r.status_code != 200:
            ultimo_error = f"HTTP {r.status_code}"
            continue
        tipo = r.headers.get("content-type", "")
        es_feed = "xml" in tipo or "rss" in tipo or r.text.lstrip().startswith("<?xml")
        items = leer_feed(r.content, url) if es_feed else leer_html(r.text, url)
        if items:
            return items, ("RSS" if es_feed else "HTML"), url, None
        ultimo_error = "sin titulares"
    return [], None, None, ultimo_error


def main():
    ahora = datetime.now(timezone.utc)
    previas = {}
    if SALIDA.exists():
        try:
            for it in json.loads(SALIDA.read_text(encoding="utf-8")).get("noticias", []):
                previas[it["id"]] = it
        except (json.JSONDecodeError, KeyError):
            previas = {}

    estado = []
    for f in FUENTES:
        items, metodo, url_ok, error = recolectar(f)
        n = 0
        for it in items:
            cats = clasificar(it["titulo"])
            if not cats:
                continue
            k = clave(it["url"])
            previa = previas.get(k, {})
            previas[k] = {
                "id": k,
                "titulo": it["titulo"],
                "url": it["url"],
                "sigla": f["sigla"],
                "universidad": f["nombre"],
                "conce": f["conce"],
                "categorias": cats,
                "fecha": it["fecha"] or previa.get("fecha"),
                "visto": previa.get("visto", ahora.isoformat()),
            }
            n += 1
        estado.append({"sigla": f["sigla"], "ok": bool(items), "metodo": metodo,
                       "url": url_ok, "revisadas": len(items), "filtradas": n, "error": error})
        print(f"{f['sigla']:<11} {metodo or '-':<5} revisadas={len(items):<4} I+D={n}  {error or ''}")

    limite = ahora - timedelta(days=DIAS_A_GUARDAR)

    def fecha_orden(it):
        return it.get("fecha") or it["visto"]

    noticias = [it for it in previas.values() if fecha_orden(it) >= limite.isoformat()]
    noticias.sort(key=fecha_orden, reverse=True)
    noticias = noticias[:MAX_NOTICIAS]

    SALIDA.write_text(json.dumps({
        "actualizado": ahora.isoformat(),
        "categorias": list(CATEGORIAS),
        "fuentes": estado,
        "noticias": noticias,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Total guardadas: {len(noticias)}")


if __name__ == "__main__":
    main()
