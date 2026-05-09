"""
=====================================================================
  SCRAPER CASA RICA v6 — Fix precios y paginación scroll infinito
=====================================================================
  Fixes vs v5:
  - Parser de precios corregido (no concatena precio actual + anterior)
  - Paginación con scroll infinito via ?pagina=N
  - Detecta ofertas correctamente

  Uso:
    python3 scraper_casarica_v6.py
=====================================================================
"""

import csv
import logging
import time
import random
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("casarica_v6")

BASE = "https://www.casarica.com.py"
OUTPUT_DIR = Path("resultados")
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-PY,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.casarica.com.py",
}

CATEGORIAS = {
    "Aceite de Girasol":    "/catalogo/aceite-de-girasol-c2",
    "Aceite de Oliva":      "/catalogo/aceite-de-oliva-c3",
    "Aceite de Soja":       "/catalogo/aceite-de-soja-c4",
    "Aceite Mezcla":        "/catalogo/aceite-mezcla-c5",
    "Alimentos P/Preparar": "/catalogo/alimentos-p-preparar-c6",
    "Arroz":                "/catalogo/arroz-c7",
    "Azúcar":               "/catalogo/azucar-c8",
    "Bebidas c/Alcohol":    "/catalogo/bebidas-con-alcohol-c20",
    "Bebidas s/Alcohol":    "/catalogo/bebidas-sin-alcohol-c46",
    "Carnicería":           "/catalogo/carniceria-c60",
    "Chocolates":           "/catalogo/chocolates-y-golosinas-c350",
    "Congelados":           "/catalogo/congelados-c73",
    "Conservados":          "/catalogo/conservados-c80",
    "Cuidado Hogar":        "/catalogo/cuidado-del-hogar-c118",
    "Cuidado Personal":     "/catalogo/cuidado-personal-c143",
    "Desayuno":             "/catalogo/desayuno-c370",
    "Fiambrería":           "/catalogo/fiambres-c84",
    "Frutas y Verduras":    "/catalogo/frutas-y-verduras-c93",
    "Lácteos":              "/catalogo/lacteos-c104",
    "Mascotas":             "/catalogo/mascotas-c314",
    "Panadería":            "/catalogo/panaderia-c163",
    "Snacks":               "/catalogo/snacks-c360",
    "Saludables":           "/catalogo/saludables-c410",
    "Bazar":                "/catalogo/bazar-c342",
    "Bebés":                "/catalogo/bebes-c288",
}

def extraer_primer_precio(texto: str) -> float | None:
    """Extrae el PRIMER precio válido de un texto que puede tener varios precios."""
    if not texto:
        return None
    # Buscar todos los precios con formato paraguayo: 1.000 a 9.999.999
    matches = re.findall(r'\d{1,3}(?:\.\d{3})+', str(texto))
    for m in matches:
        try:
            val = float(m.replace('.', ''))
            if 500 <= val <= 9999999:
                return val
        except:
            pass
    # Si no hay formato con puntos, buscar número simple de 4-7 dígitos
    matches2 = re.findall(r'\d{4,7}', str(texto))
    for m in matches2:
        try:
            val = float(m)
            if 500 <= val <= 9999999:
                return val
        except:
            pass
    return None

def extraer_todos_precios(texto: str) -> list[float]:
    """Extrae todos los precios válidos de un texto."""
    if not texto:
        return []
    resultado = []
    matches = re.findall(r'\d{1,3}(?:\.\d{3})+', str(texto))
    for m in matches:
        try:
            val = float(m.replace('.', ''))
            if 500 <= val <= 9999999:
                resultado.append(val)
        except:
            pass
    return resultado

def get(url: str, session: requests.Session) -> BeautifulSoup | None:
    for attempt in range(1, 4):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            time.sleep(random.uniform(1.0, 2.0))
            return BeautifulSoup(resp.text, "lxml")
        except requests.RequestException as e:
            wait = 2 ** attempt
            log.warning(f"Intento {attempt}/3: {e}. Esperando {wait}s…")
            time.sleep(wait)
    return None

def extraer_productos(soup: BeautifulSoup, categoria: str) -> list[dict]:
    productos = []

    items = (
        soup.select("div.product") or
        soup.select("li.product") or
        soup.select("[class*='LoopProduct']") or
        soup.select("article.product")
    )

    for item in items:
        # Nombre
        nombre_el = (
            item.select_one("h2.ecommercepro-loop-product__title") or
            item.select_one("[class*='loop-product__title']") or
            item.select_one("h2") or
            item.select_one("h3")
        )

        # Precios — separar precio actual de precio anterior
        precio_num = None
        precio_ant = None

        # Buscar precio anterior (tachado) primero
        del_el = item.select_one("del")
        if del_el:
            precio_ant = extraer_primer_precio(del_el.get_text())
            del_el.decompose()  # Remover del DOM para no confundir el precio actual

        # Precio actual — después de remover el tachado
        precio_el = (
            item.select_one("ins span.price") or
            item.select_one("span.price") or
            item.select_one(".woocommerce-Price-amount")
        )
        if precio_el:
            precio_num = extraer_primer_precio(precio_el.get_text())

        # Si no encontró con ins, buscar en todo el item
        if not precio_num:
            texto_precios = item.get_text()
            todos = extraer_todos_precios(texto_precios)
            if todos:
                precio_num = todos[0]

        # Link
        link_el = (
            item.select_one("a.ecommercepro-LoopProduct-link") or
            item.select_one("a[class*='LoopProduct']") or
            item.select_one("a[href*='/producto/']") or
            item.select_one("a[href]")
        )

        # Imagen
        img_el = item.select_one("img.wp-post-image, img[class*='wp-post-image'], img")

        nombre = nombre_el.get_text(strip=True) if nombre_el else ""
        if not nombre and img_el:
            nombre = img_el.get("alt", "").strip()

        url_prod = ""
        if link_el:
            href = link_el.get("href", "")
            url_prod = href if href.startswith("http") else BASE + href

        img_url = ""
        if img_el:
            img_url = (img_el.get("src") or img_el.get("data-src") or
                      img_el.get("data-lazy-src") or "")

        if not nombre or len(nombre) < 3:
            continue

        en_oferta = precio_ant is not None and precio_ant > (precio_num or 0)

        productos.append({
            "fuente":             "Casa Rica",
            "categoria":          categoria,
            "nombre":             nombre,
            "precio_gs":          precio_num,
            "precio_anterior_gs": precio_ant,
            "en_oferta":          en_oferta,
            "url_producto":       url_prod,
            "imagen_url":         img_url,
            "fecha_scan":         datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

    return productos


def scrape_categoria(session: requests.Session, categoria: str, path: str) -> list[dict]:
    productos = []
    vistos = set()
    pagina = 1
    max_sin_nuevos = 2

    while True:
        url = f"{BASE}{path}" if pagina == 1 else f"{BASE}{path}?pagina={pagina}"
        log.info(f"  {categoria} | p{pagina} → {url}")

        soup = get(url, session)
        if not soup:
            break

        nuevos_pagina = extraer_productos(soup, categoria)
        nuevos = 0
        for p in nuevos_pagina:
            key = f"{p['nombre']}"
            if key not in vistos:
                vistos.add(key)
                productos.append(p)
                nuevos += 1

        log.info(f"    → {nuevos} nuevos | Total: {len(productos)}")

        if nuevos == 0:
            max_sin_nuevos -= 1
            if max_sin_nuevos <= 0:
                break
        else:
            max_sin_nuevos = 2

        # Verificar si hay más páginas
        # Casa Rica usa ?pagina=N — probar hasta que no haya más productos
        pagina += 1
        if pagina > 100:  # tope de seguridad
            break

    return productos


def main():
    log.info("=" * 60)
    log.info("SCRAPER CASA RICA v6")
    log.info("=" * 60)

    session = requests.Session()
    todos = []
    fecha = datetime.now().strftime("%Y%m%d_%H%M")
    archivo = OUTPUT_DIR / f"casarica_v6_{fecha}.csv"

    for categoria, path in CATEGORIAS.items():
        log.info(f"\n{'─'*50}")
        log.info(f"CATEGORÍA: {categoria}")

        prods = scrape_categoria(session, categoria, path)
        todos.extend(prods)
        log.info(f"✓ {categoria}: {len(prods)} productos")

        if todos:
            with open(archivo, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=todos[0].keys())
                writer.writeheader()
                writer.writerows(todos)
            log.info(f"  💾 {len(todos)} productos guardados")

        time.sleep(random.uniform(2, 3))

    log.info(f"\n{'='*60}")
    log.info(f"TOTAL: {len(todos):,} productos")
    log.info(f"Archivo: {archivo}")
    log.info("✅ COMPLETADO")


if __name__ == "__main__":
    main()
EOF
