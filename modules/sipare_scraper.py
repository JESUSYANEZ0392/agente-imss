"""
Automatización del portal SIPARE (Sistema de Pago Referenciado - IMSS).
Descarga líneas de captura y comprobantes de pago bimestral.
Usa la API SÍNCRONA de Playwright (compatible con Streamlit en Windows).
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import URL_SIPARE, SCRAPING_TIMEOUT, HEADLESS, REPORTS_DIR

BIMESTRES = {
    1: "Enero-Febrero",
    2: "Marzo-Abril",
    3: "Mayo-Junio",
    4: "Julio-Agosto",
    5: "Septiembre-Octubre",
    6: "Noviembre-Diciembre",
}


class SIPAREScraper:
    """Automatiza la descarga de referencias y comprobantes del portal SIPARE."""

    def __init__(self, registro_patronal: str, usuario: str, password: str,
                 cert_path: Optional[str] = None):
        self.registro_patronal = registro_patronal
        self.usuario = usuario
        self.password = password
        self.cert_path = cert_path
        self.timeout_ms = SCRAPING_TIMEOUT * 1000

    def _iniciar_browser(self, playwright):
        try:
            browser = playwright.chromium.launch(
                channel="chrome",
                headless=HEADLESS,
                args=["--no-sandbox"],
            )
        except Exception:
            browser = playwright.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox"],
            )
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            accept_downloads=True,
        )
        page = context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return browser, page

    def _login(self, page):
        page.goto(URL_SIPARE)
        page.wait_for_load_state("networkidle", timeout=self.timeout_ms)

        page.fill(
            "input[name='j_username'], input[name='usuario'], #usuario, input[type='text']:first-of-type",
            self.usuario
        )
        page.fill(
            "input[name='j_password'], input[name='password'], #password, input[type='password']",
            self.password
        )
        page.click(
            "input[type='submit'], button[type='submit'], #btnEntrar, button:has-text('Entrar'), button:has-text('Iniciar')"
        )
        page.wait_for_load_state("networkidle", timeout=self.timeout_ms)

        if page.locator(".error, .mensajeError, #mensajeError").count() > 0:
            msg = page.locator(".error, .mensajeError, #mensajeError").first.inner_text()
            raise RuntimeError(f"Error de autenticación SIPARE: {msg}")

    def obtener_referencia_pago(self, anio: int, bimestre: int) -> dict:
        resultado = {
            "registro_patronal": self.registro_patronal,
            "anio": anio,
            "bimestre": bimestre,
            "periodo_label": BIMESTRES.get(bimestre, ""),
            "linea_captura": "",
            "monto_total": 0.0,
            "fecha_limite": "",
            "error": None,
        }

        with sync_playwright() as pw:
            browser, page = self._iniciar_browser(pw)
            try:
                self._login(page)

                page.goto(URL_SIPARE.replace("index.jsp", "generarReferencia.jsp"))
                page.wait_for_load_state("networkidle")

                anio_sel = page.locator("select[name='anio'], #anio")
                if anio_sel.count() > 0:
                    anio_sel.select_option(str(anio))

                bim_sel = page.locator("select[name='bimestre'], #bimestre")
                if bim_sel.count() > 0:
                    bim_sel.select_option(str(bimestre))

                page.click("#btnGenerar, button:has-text('Generar')")
                page.wait_for_load_state("networkidle")

                lc_elem = page.locator("#lineaCaptura, .linea-captura, td:has-text('Línea de captura') + td")
                if lc_elem.count() > 0:
                    resultado["linea_captura"] = lc_elem.first.inner_text().strip()

                monto_elem = page.locator("#montoTotal, .monto-total")
                if monto_elem.count() > 0:
                    monto_str = monto_elem.first.inner_text().strip().replace("$", "").replace(",", "")
                    try:
                        resultado["monto_total"] = float(monto_str)
                    except ValueError:
                        pass

                fecha_elem = page.locator("#fechaLimite, .fecha-limite")
                if fecha_elem.count() > 0:
                    resultado["fecha_limite"] = fecha_elem.first.inner_text().strip()

            except Exception as e:
                resultado["error"] = str(e)
            finally:
                browser.close()

        return resultado

    def descargar_sipare_pdf(self, anio: int, bimestre: int,
                             destino: Optional[str] = None) -> str:
        destino = destino or REPORTS_DIR
        Path(destino).mkdir(parents=True, exist_ok=True)

        with sync_playwright() as pw:
            browser, page = self._iniciar_browser(pw)
            try:
                self._login(page)

                with page.expect_download(timeout=60000) as dl:
                    page.goto(URL_SIPARE.replace("index.jsp", f"descargar?anio={anio}&bimestre={bimestre}"))
                download = dl.value

                nombre = (f"SIPARE_{self.registro_patronal}_{anio}_B{bimestre}_"
                          f"{datetime.now().strftime('%Y%m%d')}.pdf")
                ruta = os.path.join(destino, nombre)
                download.save_as(ruta)
            finally:
                browser.close()

        return ruta

    def consultar_historico_pagos(self, anio_inicio: int, anio_fin: int) -> list[dict]:
        pagos = []
        with sync_playwright() as pw:
            browser, page = self._iniciar_browser(pw)
            try:
                self._login(page)
                page.goto(URL_SIPARE + "historicoPagos")
                page.wait_for_load_state("networkidle")

                page.fill("#anioInicio", str(anio_inicio))
                page.fill("#anioFin", str(anio_fin))
                page.click("#btnConsultar, button:has-text('Consultar')")
                page.wait_for_load_state("networkidle")

                filas = page.query_selector_all("table tbody tr")
                for fila in filas:
                    celdas = fila.query_selector_all("td")
                    if len(celdas) >= 5:
                        textos = [c.inner_text() for c in celdas]
                        pagos.append({
                            "periodo": textos[0].strip(),
                            "linea_captura": textos[1].strip() if len(textos) > 1 else "",
                            "monto": textos[2].strip() if len(textos) > 2 else "",
                            "fecha_pago": textos[3].strip() if len(textos) > 3 else "",
                            "estado": textos[4].strip() if len(textos) > 4 else "",
                        })
            except PWTimeout:
                pass
            finally:
                browser.close()

        return pagos


# API directa para Streamlit (sin asyncio)
def obtener_referencia_sync(registro: str, usuario: str, password: str,
                            cert_path: str, anio: int, bimestre: int) -> dict:
    return SIPAREScraper(registro, usuario, password, cert_path).obtener_referencia_pago(anio, bimestre)


def descargar_sipare_sync(registro: str, usuario: str, password: str,
                          cert_path: str, anio: int, bimestre: int,
                          destino: Optional[str] = None) -> str:
    return SIPAREScraper(registro, usuario, password, cert_path).descargar_sipare_pdf(anio, bimestre, destino)
