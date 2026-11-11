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
MAX_FOTOS_POR_EJECUCION = 60   # páginas de noticias que se abren para buscar foto
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

# Hashtags: el primero que calce de cada línea; se muestran hasta 3 por noticia.
# Formato: "Etiqueta": [patrones]. Se buscan en el título sin tildes.
HASHTAGS = {
    "Fondecyt": [r"fondecyt"], "Fondef": [r"fondef"], "ANID": [r"\banid\b"],
    "Corfo": [r"\bcorfo\b"], "VIU": [r"\bviu\b"], "Patentes": [r"\bpatent", r"\binapi\b"],
    "PropiedadIntelectual": [r"propiedad intelectual"],
    "TransferenciaTecnológica": [r"transferencia tecnologica", r"\blicenci", r"spin.?off"],
    "Startups": [r"start.?up", r"\bpitch\b", r"aceleradora", r"incubadora"],
    "Emprendimiento": [r"\bemprend"],
    "IA": [r"inteligencia artificial", r"\bia\b", r"machine learning"],
    "Minería": [r"\bminer", r"\bcobre\b", r"relave", r"\blitio\b"],
    "Energía": [r"energia", r"hidrogeno", r"\bsolar\b", r"\bh2v\b"],
    "Agua": [r"\bagua", r"hidric", r"desalad"],
    "Salud": [r"\bsalud\b", r"\bcancer", r"\bmedic", r"\bclinic", r"vacuna"],
    "Biotecnología": [r"biotecnolog", r"\bgenom", r"microorganism", r"\bbacteri"],
    "MedioAmbiente": [r"ambient", r"biodiversidad", r"cambio climatico", r"sustentab", r"sostenib", r"residuo"],
    "Alimentos": [r"aliment", r"agricol", r"agro", r"\bvin(o|edo)", r"fruta"],
    "Mar": [r"\bmar\b", r"marin", r"oceano", r"acuicultura", r"pesca", r"costera"],
    "Forestal": [r"forestal", r"\bmadera", r"\bbosque"],
    "Incendios": [r"incendio"],
    "Astronomía": [r"astronom", r"telescopio", r"galaxia", r"espacial"],
    "Construcción": [r"construccion", r"vivienda"],
    "Educación": [r"\beducacion", r"escolar", r"docente"],
    "Biobío": [r"biobio", r"concepcion", r"talcahuano", r"\bpenco\b"],
}
_TAG_RE = {t: [re.compile(p) for p in ps] for t, ps in HASHTAGS.items()}


TAG_CATEGORIA = {"I+D": "Investigación", "Innovación y transferencia": "Innovación",
                 "Emprendimiento": "Emprendimiento"}


def hashtags(titulo, categorias=(), max_tags=3):
    """Hasta 3 hashtags: temas del título y, si faltan, el de la categoría."""
    t = normalizar(titulo)
    tags = [tag for tag, regs in _TAG_RE.items() if any(r.search(t) for r in regs)][:max_tags]
    for c in categorias:
        extra = TAG_CATEGORIA.get(c)
        if extra and extra not in tags and len(tags) < max_tags:
            tags.append(extra)
    return tags


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
        items.append({"titulo": titulo, "url": enlace, "fecha": fecha, "imagen": imagen_de_entrada(e, enlace)})
    return items


def imagen_de_entrada(e, base):
    """Busca una foto en la entrada RSS: media, enclosure o primer <img> del contenido."""
    for campo in ("media_content", "media_thumbnail"):
        for m in e.get(campo) or []:
            if m.get("url"):
                return urljoin(base, m["url"])
    for enc in e.get("enclosures") or []:
        if str(enc.get("type", "")).startswith("image") and enc.get("href"):
            return urljoin(base, enc["href"])
    html = " ".join([c.get("value", "") for c in e.get("content") or []] + [e.get("summary", "")])
    m = re.search(r'<img[^>]+src=["\']([^"\']+)', html)
    return urljoin(base, m.group(1)) if m else None


def imagen_de_pagina(url):
    """Abre la noticia y toma la foto de portada (og:image o twitter:image)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        for attr, nombre in (("property", "og:image"), ("name", "twitter:image"), ("property", "og:image:url")):
            tag = soup.find("meta", attrs={attr: nombre})
            if tag and tag.get("content"):
                return urljoin(url, tag["content"].strip())
    except requests.RequestException:
        pass
    return None


def leer_html(contenido, url_base):
    """Extrae enlaces que parecen titulares: mismo dominio y texto largo."""
    soup = BeautifulSoup(contenido, "html.parser")
    dominio = ".".join(urlparse(url_base).netloc.split(".")[-2:])  # p. ej. udec.cl
    vistos, items = set(), []
    for a in soup.find_all("a", href=True):
        texto = " ".join(a.get_text(" ", strip=True).split())
        # Un titular de noticia es una frase larga (no un ítem de menú)
        if not (45 <= len(texto) <= 220) or len(texto.split()) < 6:
            continue
        enlace = urljoin(url_base, a["href"])
        p = urlparse(enlace)
        if p.scheme not in ("http", "https") or not p.netloc.endswith(dominio):
            continue
        partes = [s for s in p.path.split("/") if s]
        # La dirección de una noticia suele terminar en un "slug" largo: palabras-con-guiones
        if not partes or partes[-1].count("-") < 4 or enlace in vistos:
            continue
        vistos.add(enlace)
        items.append({"titulo": texto, "url": enlace, "fecha": None, "imagen": None})
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
                # Descarta titulares viejos que en realidad eran ítems de menú
                if not it.get("fecha") and len(it.get("titulo", "")) < 45:
                    continue
                previas[it["id"]] = it
        except (json.JSONDecodeError, KeyError):
            previas = {}

    estado = []
    fotos_buscadas = 0
    for f in FUENTES:
        items, metodo, url_ok, error = recolectar(f)
        n = 0
        for it in items:
            cats = clasificar(it["titulo"])
            if not cats:
                continue
            k = clave(it["url"])
            previa = previas.get(k, {})
            imagen = it.get("imagen") or previa.get("imagen")
            if not imagen and not previa.get("foto_buscada") and fotos_buscadas < MAX_FOTOS_POR_EJECUCION:
                imagen = imagen_de_pagina(it["url"])
                fotos_buscadas += 1
            previas[k] = {
                "id": k,
                "titulo": it["titulo"],
                "url": it["url"],
                "sigla": f["sigla"],
                "universidad": f["nombre"],
                "conce": f["conce"],
                "categorias": cats,
                "hashtags": hashtags(it["titulo"], cats),
                "imagen": imagen.replace("http://", "https://", 1) if imagen else None,
                "foto_buscada": True,
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
