"""
=====================================================================
  SCHEDULER AUTOMÁTICO — Scraper Inteligencia Competitiva
=====================================================================
  Ejecuta el scraper todos los días a la hora configurada.
  Envía resumen por email al equipo comercial.

  Uso:
    python scheduler.py                  # corre ahora y cada día
    python scheduler.py --hora 07:00     # ejecutar a las 7am
    python scheduler.py --una-vez        # ejecutar una sola vez ya
=====================================================================
"""

import argparse
import logging
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

import schedule

# Importar el scraper
from scraper_competencia import scrape_casarica, scrape_stock, guardar_csv, comparar_precios

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scheduler")

# ── Configuración de email ─────────────────────────────────────────
# Editar con los datos reales del equipo
CONFIG_EMAIL = {
    "smtp_server":   "smtp.gmail.com",
    "smtp_port":     587,
    "usuario":       "tu_email@empresa.com.py",      # ← cambiar
    "password":      "TU_APP_PASSWORD",               # ← cambiar (App Password de Gmail)
    "destinatarios": [                                # ← cambiar
        "equipo.comercial@empresa.com.py",
        "direccion@empresa.com.py",
    ],
}

OUTPUT_DIR = Path("resultados")


def ejecutar_scan():
    """Corre el scraping completo y genera resumen."""
    log.info("=" * 60)
    log.info(f"INICIANDO SCAN PROGRAMADO — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    log.info("=" * 60)

    fecha = datetime.now().strftime("%Y%m%d_%H%M")
    archivos_generados = []

    try:
        # Scrapear ambos sitios
        prods_cr  = scrape_casarica()
        prods_st  = scrape_stock()

        # Guardar CSV individuales
        if prods_cr:
            f = guardar_csv(prods_cr, f"casarica_{fecha}.csv")
            archivos_generados.append(f)

        if prods_st:
            f = guardar_csv(prods_st, f"stock_{fecha}.csv")
            archivos_generados.append(f)

        # Comparación
        df_comp = pd.DataFrame()
        if prods_cr and prods_st:
            df_comp = comparar_precios(pd.DataFrame(prods_cr), pd.DataFrame(prods_st))
            if not df_comp.empty:
                f = guardar_csv(df_comp.to_dict("records"), f"comparacion_{fecha}.csv")
                archivos_generados.append(f)

        # Resumen para email
        resumen = generar_resumen(prods_cr, prods_st, df_comp)

        # Enviar email
        enviar_email(
            asunto=f"📊 Inteligencia Competitiva — {datetime.now().strftime('%d/%m/%Y')}",
            cuerpo_html=resumen,
            adjuntos=archivos_generados,
        )

        log.info("✅  Scan completado y email enviado")

    except Exception as e:
        log.error(f"Error en scan: {e}", exc_info=True)
        enviar_email(
            asunto=f"⚠️ Error en scan — {datetime.now().strftime('%d/%m/%Y')}",
            cuerpo_html=f"<p>Error durante el scan: <code>{e}</code></p>",
            adjuntos=[],
        )


def generar_resumen(
    prods_cr: list,
    prods_st: list,
    df_comp: pd.DataFrame,
) -> str:
    """Genera HTML del resumen para el email."""

    cr_total    = len(prods_cr)
    st_total    = len(prods_st)
    cr_ofertas  = sum(1 for p in prods_cr if p.get("en_oferta"))
    st_ofertas  = sum(1 for p in prods_st if p.get("en_oferta"))

    # Top diferencias de precio
    tabla_comp = ""
    if not df_comp.empty:
        top10 = df_comp.head(10)
        filas = ""
        for _, r in top10.iterrows():
            color = "#c62828" if r["diferencia_gs"] > 0 else "#2e7d32"
            signo = "+" if r["diferencia_gs"] > 0 else ""
            filas += f"""
            <tr>
              <td style="padding:6px 10px">{r['nombre']}</td>
              <td style="padding:6px 10px;text-align:right">₲ {r['precio_gs_casarica']:,.0f}</td>
              <td style="padding:6px 10px;text-align:right">₲ {r['precio_gs_stock']:,.0f}</td>
              <td style="padding:6px 10px;text-align:right;color:{color};font-weight:bold">
                {signo}{r['diferencia_pct']:.1f}%
              </td>
            </tr>"""

        tabla_comp = f"""
        <h3 style="color:#333;margin-top:24px">Diferencias de precio (Casa Rica vs Stock)</h3>
        <table style="border-collapse:collapse;width:100%;font-size:13px">
          <thead>
            <tr style="background:#f5f5f5">
              <th style="padding:8px 10px;text-align:left">Producto</th>
              <th style="padding:8px 10px;text-align:right">Casa Rica</th>
              <th style="padding:8px 10px;text-align:right">Stock</th>
              <th style="padding:8px 10px;text-align:right">Diferencia</th>
            </tr>
          </thead>
          <tbody>{filas}</tbody>
        </table>"""

    return f"""
    <html><body style="font-family:sans-serif;color:#333;max-width:700px;margin:auto">
      <h2 style="color:#1a237e">📊 Inteligencia Competitiva — {datetime.now().strftime('%d de %B, %Y')}</h2>

      <table style="width:100%;border-collapse:collapse;margin-bottom:20px">
        <tr>
          <td style="padding:12px;background:#e3f2fd;border-radius:8px;text-align:center;width:33%">
            <div style="font-size:28px;font-weight:bold;color:#1565c0">{cr_total:,}</div>
            <div style="font-size:12px;color:#555">productos Casa Rica</div>
          </td>
          <td style="padding:12px;background:#e8f5e9;border-radius:8px;text-align:center;width:33%">
            <div style="font-size:28px;font-weight:bold;color:#2e7d32">{st_total:,}</div>
            <div style="font-size:12px;color:#555">productos Stock / S6</div>
          </td>
          <td style="padding:12px;background:#fff3e0;border-radius:8px;text-align:center;width:33%">
            <div style="font-size:28px;font-weight:bold;color:#e65100">{cr_ofertas + st_ofertas}</div>
            <div style="font-size:12px;color:#555">productos en oferta</div>
          </td>
        </tr>
      </table>

      <p style="font-size:13px;color:#666">
        Scan ejecutado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')} hs.
        Los archivos CSV completos se adjuntan a este correo.
      </p>

      {tabla_comp}

      <hr style="margin:24px 0;border:none;border-top:1px solid #eee">
      <p style="font-size:11px;color:#999">
        Sistema de Inteligencia Competitiva — Retail S.A.<br>
        Este email es generado automáticamente.
      </p>
    </body></html>
    """


def enviar_email(asunto: str, cuerpo_html: str, adjuntos: list):
    """Envía email con adjuntos al equipo comercial."""
    cfg = CONFIG_EMAIL

    if not cfg["usuario"] or cfg["usuario"] == "tu_email@empresa.com.py":
        log.warning("Email no configurado — omitiendo envío. Editar CONFIG_EMAIL en scheduler.py")
        return

    msg = MIMEMultipart("mixed")
    msg["From"]    = cfg["usuario"]
    msg["To"]      = ", ".join(cfg["destinatarios"])
    msg["Subject"] = asunto

    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

    # Adjuntar CSVs
    for ruta in adjuntos:
        if ruta and Path(ruta).exists():
            with open(ruta, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={Path(ruta).name}"
            )
            msg.attach(part)

    try:
        with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"]) as server:
            server.starttls()
            server.login(cfg["usuario"], cfg["password"])
            server.sendmail(cfg["usuario"], cfg["destinatarios"], msg.as_string())
        log.info(f"  Email enviado a: {', '.join(cfg['destinatarios'])}")
    except Exception as e:
        log.error(f"  Error enviando email: {e}")


def main():
    parser = argparse.ArgumentParser(description="Scheduler de scraping")
    parser.add_argument("--hora", default="07:00", help="Hora de ejecución diaria (HH:MM)")
    parser.add_argument("--una-vez", action="store_true", help="Ejecutar una sola vez inmediatamente")
    args = parser.parse_args()

    if args.una_vez:
        ejecutar_scan()
        return

    log.info(f"Scheduler iniciado. Scan diario a las {args.hora} hs.")
    schedule.every().day.at(args.hora).do(ejecutar_scan)

    # Ejecutar inmediatamente la primera vez también
    ejecutar_scan()

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
