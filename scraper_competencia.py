"""
=====================================================================
  SCRAPER DE INTELIGENCIA COMPETITIVA — Casa Rica & Stock (S6)
  Retail S.A. — Equipo Comercial
=====================================================================
  Extrae surtido completo: nombre, precio, categoría, URL, fecha.
  Guarda en CSV local + opcionalmente sube a Google Sheets.

  Instalación (una sola vez):
    pip install requests beautifulsoup4 lxml gspread google-auth pandas

  Uso rápido:
    python scraper_competencia.py                  # ambos sitios
    python scraper_competencia.py --sitio casarica  # solo Casa Rica
    python scraper_competencia.py --sitio stock     # solo Stock/S6

  Para subir a Google Sheets agregar: --sheets
=====================================================================
"""

import argparse
import csv
import json
import logging
import os
import time
import random
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import pandas as pd

# ── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper")

# ── Constantes ─────────────────────────────────────────────────────
OUTPUT_DIR = Path("resultados")
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-PY,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Pausa entre requests (segundos) — ser respetuoso con el servidor
DELAY_MIN = 1.2
DELAY_MAX = 2.8


# ═══════════════════════════════════════════════════════════════════
#  UTILIDADES COMUNES
# ═══════════════════════════════════════════════════════════════════

def get(url: str, session: requests.Session, retries: int = 3) -> BeautifulSoup | None:
    """GET con reintentos y backoff exponencial."""
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            return BeautifulSoup(resp.text, "lxml")
        except requests.RequestException as e:
            wait = 2 ** attempt
            log.warning(f"Intento {attempt}/{retries} fallido para {url}: {e}. Esperando {wait}s…")
            time.sleep(wait)
    log.error(f"No se pudo obtener: {url}")
    return None


def precio_a_numero(texto: str) -> float | None:
    """Convierte '₲ 12.500' o 'Gs. 12.500' o '12500' → 12500.0"""
    if not texto:
        return None
    limpio = (
        texto.replace("₲", "").replace("Gs.", "").replace("Gs", "")
             .replace(".", "").replace(",", ".").strip()
    )
    try:
        return float(limpio)
    except ValueError:
        return None


def guardar_csv(productos: list[dict], nombre_archivo: str):
    """Guarda lista de dicts como CSV."""
    if not productos:
        log.warning("Sin productos para guardar.")
        return
    ruta = OUTPUT_DIR / nombre_archivo
    df = pd.DataFrame(productos)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")
    log.info(f"✅  {len(productos):,} productos → {ruta}")
    return ruta


# ═══════════════════════════════════════════════════════════════════
#  SCRAPER: CASA RICA (casarica.com.py)
# ═══════════════════════════════════════════════════════════════════
#
#  Estructura del sitio:
#    /catalogo/almacen-c1        → listado con paginación ?pagina=N
#    Cada producto: <div class="product-item"> con nombre, precio, URL
#
#  Las categorías principales se obtienen del menú de navegación.
# ─────────────────────────────────────────────────────────────────

BASE_CASARICA = "https://www.casarica.com.py"

# Categorías principales extraídas del menú (ID numérico al final del slug)
CATEGORIAS_CASARICA = {
    "Almacén":              "/catalogo/almacen-c1",
    "Bebidas con Alcohol":  "/catalogo/bebidas-con-alcohol-c20",
    "Bebidas sin Alcohol":  "/catalogo/bebidas-sin-alcohol-c46",
    "Carnicería":           "/catalogo/carniceria-c60",
    "Congelados":           "/catalogo/congelados-c73",
    "Fiambrería":           "/catalogo/fiambres-c84",
    "Frutas y Verduras":    "/catalogo/frutas-y-verduras-c93",
    "Lácteos":              "/catalogo/lacteos-c104",
    "Limpieza":             "/catalogo/limpieza-c118",
    "Perfumería":           "/catalogo/perfumeria-c143",
    "Panadería":            "/catalogo/panaderia-c163",
    "Bebes":                "/catalogo/bebes-c288",
    "Mascotas":             "/catalogo/mascotas-c314",
    "Bazar":                "/catalogo/bazar-c342",
}


def scrape_casarica_categoria(
    session: requests.Session, categoria: str, url_base: str
) -> list[dict]:
    """Scrapea todas las páginas de una categoría de Casa Rica."""
    productos = []
    pagina = 1

    while True:
        url = f"{BASE_CASARICA}{url_base}" if pagina == 1 else f"{BASE_CASARICA}{url_base}?pagina={pagina}"
        log.info(f"  Casa Rica | {categoria} | página {pagina} → {url}")
        soup = get(url, session)

        if not soup:
            break

        # ── Tarjetas de producto ────────────────────────────────
        # Casa Rica usa <div class="product-box"> o <article class="product-item">
        items = soup.select("div.product-box, article.product-item, .product")

        if not items:
            # Intentar selector alternativo
            items = soup.select("[class*='product']")

        if not items:
            log.debug(f"  Sin más productos en página {pagina} — fin de categoría")
            break

        nuevos = 0
        for item in items:
            nombre_el = (
                item.select_one(".product-name, .nombre, h2, h3, .title, [class*='name']")
            )
            precio_el = (
                item.select_one(".price, .precio, [class*='price'], [class*='precio']")
            )
            link_el = item.select_one("a[href]")
            img_el = item.select_one("img[src]")

            # Precio en oferta (tachado = precio anterior)
            precio_oferta_el = item.select_one(
                ".price-sale, .oferta, .descuento, [class*='sale'], del, s"
            )

            nombre = nombre_el.get_text(strip=True) if nombre_el else "SIN NOMBRE"
            precio_texto = precio_el.get_text(strip=True) if precio_el else ""
            precio_num = precio_a_numero(precio_texto)
            precio_oferta = precio_a_numero(
                precio_oferta_el.get_text(strip=True)
            ) if precio_oferta_el else None

            url_producto = ""
            if link_el:
                href = link_el.get("href", "")
                url_producto = href if href.startswith("http") else BASE_CASARICA + href

            imagen = img_el.get("src", "") if img_el else ""

            if nombre == "SIN NOMBRE" and not precio_num:
                continue  # elemento vacío, skip

            productos.append({
                "fuente":          "Casa Rica",
                "categoria":       categoria,
                "nombre":          nombre,
                "precio_gs":       precio_num,
                "precio_oferta_gs": precio_oferta,
                "en_oferta":       precio_oferta is not None,
                "url_producto":    url_producto,
                "imagen_url":      imagen,
                "fecha_scan":      datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
            nuevos += 1

        log.info(f"    → {nuevos} productos encontrados")

        if nuevos == 0:
            break

        # ── Verificar si hay página siguiente ──────────────────
        next_page = soup.select_one("a.next, a[rel='next'], .paginacion a:last-child, [class*='next']")
        if not next_page:
            # Verificar por número de página en URL
            paginacion = soup.select(".paginacion a, .pagination a")
            nums = [a.get_text(strip=True) for a in paginacion if a.get_text(strip=True).isdigit()]
            if not nums or pagina >= max(int(n) for n in nums if n.isdigit()):
                break
        pagina += 1

    return productos


def scrape_casarica(categorias_filtro: list[str] | None = None) -> list[dict]:
    """Scrapea el catálogo completo de Casa Rica."""
    log.info("━" * 60)
    log.info("INICIANDO SCRAPING: CASA RICA")
    log.info("━" * 60)

    session = requests.Session()
    todos = []
    cats = CATEGORIAS_CASARICA

    if categorias_filtro:
        cats = {k: v for k, v in cats.items() if k in categorias_filtro}

    for categoria, url in cats.items():
        prods = scrape_casarica_categoria(session, categoria, url)
        todos.extend(prods)
        log.info(f"  ✓ {categoria}: {len(prods)} productos")

    log.info(f"\n  TOTAL CASA RICA: {len(todos):,} productos")
    return todos


# ═══════════════════════════════════════════════════════════════════
#  SCRAPER: STOCK / S6 (stock.com.py)
# ═══════════════════════════════════════════════════════════════════
#
#  Estructura del sitio:
#    /category/ID-nombre.aspx?pageindex=N
#    Productos en <div class="product-box"> (similar a Casa Rica)
#    La paginación usa ?pageindex=N
#
#  Nota: El sitio usa ASP.NET WebForms. Los productos se renderizan
#  server-side, por lo que BeautifulSoup es suficiente (no JS).
# ─────────────────────────────────────────────────────────────────

BASE_STOCK = "https://www.stock.com.py"

# Categorías de Stock con sus IDs (verificados desde el sitio)
CATEGORIAS_STOCK = {
    "Almacén":              "/category/100-almacen.aspx",
    "Bebidas":              "/category/101-bebidas.aspx",
    "Carnicería":           "/category/102-carniceria.aspx",
    "Congelados":           "/category/103-congelados.aspx",
    "Fiambrería":           "/category/104-fiambres-y-lacteos.aspx",
    "Frutas y Verduras":    "/category/105-frutas-y-verduras.aspx",
    "Limpieza":             "/category/106-limpieza.aspx",
    "Perfumería":           "/category/107-perfumeria.aspx",
    "Panadería":            "/category/108-panaderia.aspx",
    "Mascotas":             "/category/109-mascotas.aspx",
    "Ofertas":              "/Ofertas.aspx?CategoryId=865",
}


def scrape_stock_categoria(
    session: requests.Session, categoria: str, url_base: str
) -> list[dict]:
    """Scrapea todas las páginas de una categoría de Stock."""
    productos = []
    pagina = 1
    max_paginas = 200  # tope de seguridad

    while pagina <= max_paginas:
        if pagina == 1:
            url = f"{BASE_STOCK}{url_base}"
        else:
            # Stock usa pageindex como query param
            sep = "&" if "?" in url_base else "?"
            url = f"{BASE_STOCK}{url_base}{sep}pageindex={pagina}"

        log.info(f"  Stock | {categoria} | página {pagina} → {url}")
        soup = get(url, session)

        if not soup:
            break

        # ── Tarjetas de producto ────────────────────────────────
        # Stock usa estructura similar: div.product-box o similar
        items = soup.select(
            "div.product-box, div.product-item, "
            ".ProductsContainer .product, "
            "table.ProductsTable td"
        )

        if not items:
            items = soup.select("[class*='product-']")

        if not items:
            log.debug(f"  Sin productos en página {pagina}")
            break

        nuevos = 0
        for item in items:
            nombre_el = item.select_one(
                ".product-name, .ProductName, h2, h3, .name, [class*='Name']"
            )
            # Stock muestra precio con y sin oferta
            precio_normal_el = item.select_one(
                ".product-price, .Price, .precio, [class*='Price']:not([class*='Old'])"
            )
            precio_viejo_el = item.select_one(
                ".OldPrice, .price-old, del, s, [class*='Old']"
            )
            link_el = item.select_one("a[href]")
            img_el  = item.select_one("img[src]")

            nombre = nombre_el.get_text(strip=True) if nombre_el else "SIN NOMBRE"
            precio_texto = precio_normal_el.get_text(strip=True) if precio_normal_el else ""
            precio_num = precio_a_numero(precio_texto)
            precio_viejo = precio_a_numero(
                precio_viejo_el.get_text(strip=True)
            ) if precio_viejo_el else None

            url_producto = ""
            if link_el:
                href = link_el.get("href", "")
                url_producto = href if href.startswith("http") else BASE_STOCK + href

            imagen = img_el.get("src", "") if img_el else ""

            if nombre == "SIN NOMBRE" and not precio_num:
                continue

            en_oferta = precio_viejo is not None and precio_viejo > (precio_num or 0)

            productos.append({
                "fuente":           "Stock / S6",
                "categoria":        categoria,
                "nombre":           nombre,
                "precio_gs":        precio_num,
                "precio_normal_gs": precio_viejo,   # precio sin descuento
                "en_oferta":        en_oferta,
                "url_producto":     url_producto,
                "imagen_url":       imagen,
                "fecha_scan":       datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
            nuevos += 1

        log.info(f"    → {nuevos} productos encontrados")

        if nuevos == 0:
            break

        # ── Paginación ─────────────────────────────────────────
        # Stock: buscar link "Siguiente" o última página numerada
        siguiente = soup.select_one(
            "a.nextPage, a[title='Siguiente'], a[aria-label='Next'], "
            ".pagination a:contains('Siguiente'), .paging a:last-child"
        )
        if siguiente and siguiente.get("href"):
            pagina += 1
        else:
            # Buscar números de página
            nums_links = soup.select(".pagination a, .paging a")
            nums = [a.get_text(strip=True) for a in nums_links if a.get_text(strip=True).isdigit()]
            if nums and pagina < max(int(n) for n in nums):
                pagina += 1
            else:
                break

    return productos


def scrape_stock(categorias_filtro: list[str] | None = None) -> list[dict]:
    """Scrapea el catálogo completo de Stock."""
    log.info("━" * 60)
    log.info("INICIANDO SCRAPING: STOCK / S6")
    log.info("━" * 60)

    session = requests.Session()
    todos = []
    cats = CATEGORIAS_STOCK

    if categorias_filtro:
        cats = {k: v for k, v in cats.items() if k in categorias_filtro}

    for categoria, url in cats.items():
        prods = scrape_stock_categoria(session, categoria, url)
        todos.extend(prods)
        log.info(f"  ✓ {categoria}: {len(prods)} productos")

    log.info(f"\n  TOTAL STOCK: {len(todos):,} productos")
    return todos


# ═══════════════════════════════════════════════════════════════════
#  COMPARADOR DE PRECIOS
# ═══════════════════════════════════════════════════════════════════

def comparar_precios(df_casarica: pd.DataFrame, df_stock: pd.DataFrame) -> pd.DataFrame:
    """
    Cruza productos de ambos sitios por nombre (fuzzy simple).
    Devuelve DataFrame con columnas: nombre, precio_casarica, precio_stock, diferencia_gs, diferencia_pct
    """
    if df_casarica.empty or df_stock.empty:
        return pd.DataFrame()

    # Normalizar nombres para comparación
    def normalizar(s):
        return s.lower().strip()

    df_cr = df_casarica[["nombre", "precio_gs"]].copy()
    df_cr["_key"] = df_cr["nombre"].apply(normalizar)

    df_st = df_stock[["nombre", "precio_gs"]].copy()
    df_st["_key"] = df_st["nombre"].apply(normalizar)

    merged = df_cr.merge(df_st, on="_key", suffixes=("_casarica", "_stock"))
    merged = merged[merged["precio_gs_casarica"].notna() & merged["precio_gs_stock"].notna()]

    merged["diferencia_gs"] = merged["precio_gs_casarica"] - merged["precio_gs_stock"]
    merged["diferencia_pct"] = (
        (merged["diferencia_gs"] / merged["precio_gs_stock"]) * 100
    ).round(1)

    resultado = merged[[
        "nombre_casarica", "precio_gs_casarica", "precio_gs_stock",
        "diferencia_gs", "diferencia_pct"
    ]].rename(columns={"nombre_casarica": "nombre"})

    return resultado.sort_values("diferencia_pct", ascending=False)


# ═══════════════════════════════════════════════════════════════════
#  GOOGLE SHEETS (OPCIONAL)
# ═══════════════════════════════════════════════════════════════════

def subir_a_sheets(df: pd.DataFrame, nombre_hoja: str, credenciales_json: str):
    """
    Sube DataFrame a Google Sheets.
    Requiere: pip install gspread google-auth
    credenciales_json: ruta al archivo JSON de Service Account descargado de Google Cloud.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(credenciales_json, scopes=scopes)
        gc = gspread.authorize(creds)

        # Abrir o crear spreadsheet
        try:
            sh = gc.open("Inteligencia Competitiva — Retail")
        except gspread.SpreadsheetNotFound:
            sh = gc.create("Inteligencia Competitiva — Retail")
            log.info("Spreadsheet creada en Google Drive")

        # Abrir o crear hoja
        try:
            ws = sh.worksheet(nombre_hoja)
            ws.clear()
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=nombre_hoja, rows=50000, cols=20)

        # Subir datos
        ws.update([df.columns.tolist()] + df.fillna("").values.tolist())
        log.info(f"✅  Datos subidos a Google Sheets → hoja '{nombre_hoja}'")
        log.info(f"    URL: {sh.url}")

    except ImportError:
        log.error("Instalar: pip install gspread google-auth")
    except Exception as e:
        log.error(f"Error al subir a Sheets: {e}")


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Scraper de surtido competitivo")
    parser.add_argument(
        "--sitio",
        choices=["casarica", "stock", "ambos"],
        default="ambos",
        help="Sitio a scrapear (default: ambos)"
    )
    parser.add_argument(
        "--sheets",
        action="store_true",
        help="Subir resultados a Google Sheets"
    )
    parser.add_argument(
        "--creds",
        default="credenciales_google.json",
        help="Ruta al JSON de credenciales de Service Account"
    )
    parser.add_argument(
        "--categoria",
        nargs="*",
        help="Filtrar por categoría(s) específicas, ej: --categoria Almacén Bebidas"
    )
    args = parser.parse_args()

    fecha = datetime.now().strftime("%Y%m%d_%H%M")
    productos_casarica = []
    productos_stock    = []

    # ── Scrapear ──────────────────────────────────────────────
    if args.sitio in ("casarica", "ambos"):
        productos_casarica = scrape_casarica(args.categoria)
        archivo_cr = guardar_csv(productos_casarica, f"casarica_{fecha}.csv")

    if args.sitio in ("stock", "ambos"):
        productos_stock = scrape_stock(args.categoria)
        archivo_st = guardar_csv(productos_stock, f"stock_{fecha}.csv")

    # ── Comparación de precios ─────────────────────────────────
    if productos_casarica and productos_stock:
        df_cr = pd.DataFrame(productos_casarica)
        df_st = pd.DataFrame(productos_stock)
        df_comp = comparar_precios(df_cr, df_st)
        if not df_comp.empty:
            guardar_csv(df_comp.to_dict("records"), f"comparacion_{fecha}.csv")
            log.info(f"\n  TOP 10 diferencias de precio encontradas:")
            log.info(df_comp.head(10).to_string(index=False))

    # ── Google Sheets ──────────────────────────────────────────
    if args.sheets:
        if not os.path.exists(args.creds):
            log.error(f"Archivo de credenciales no encontrado: {args.creds}")
            log.info("Ver README para configurar Google Sheets.")
        else:
            if productos_casarica:
                subir_a_sheets(
                    pd.DataFrame(productos_casarica),
                    "Casa Rica",
                    args.creds
                )
            if productos_stock:
                subir_a_sheets(
                    pd.DataFrame(productos_stock),
                    "Stock S6",
                    args.creds
                )

    log.info("\n✅  SCRAPING COMPLETADO")
    log.info(f"   Resultados en: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
