"""
Automatización del portal IDSE (IMSS Desde Su Empresa).
Usa la API SÍNCRONA de Playwright (compatible con Streamlit en Windows).
Funciones: consultar movimientos, descargar acuses, verificar estatus.
"""
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import URL_IDSE, SCRAPING_TIMEOUT, HEADLESS, REPORTS_DIR


class IDSEScraper:
    """Automatiza consultas y descargas del portal IDSE del IMSS."""

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
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
        except Exception:
            browser = playwright.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
        )
        page = context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return browser, page

    def _login(self, page):
        page.goto(URL_IDSE)

        try:
            page.click("text=Acceso con usuario y contraseña", timeout=5000)
        except PWTimeout:
            pass

        page.fill("input[name='usuario'], #usuario, input[type='text']", self.usuario)
        page.fill("input[name='password'], #password, input[type='password']", self.password)

        if self.cert_path and os.path.exists(self.cert_path):
            cert_input = page.locator("input[type='file']")
            if cert_input.count() > 0:
                cert_input.set_input_files(self.cert_path)

        page.click("button[type='submit'], input[type='submit'], #btnAcceder")
        page.wait_for_load_state("networkidle", timeout=self.timeout_ms)

        if "error" in page.url.lower() or page.locator(".error, .alerta-error").count() > 0:
            raise RuntimeError("Error de autenticación en IDSE. Verifica usuario/contraseña.")

    def consultar_movimientos(self, fecha_inicio: date, fecha_fin: date) -> list[dict]:
        movimientos = []
        with sync_playwright() as pw:
            browser, page = self._iniciar_browser(pw)
            try:
                self._login(page)
                page.goto(URL_IDSE + "?opcion=movimientos")
                page.wait_for_load_state("networkidle")

                try:
                    page.fill("#fechaInicio, input[name='fechaInicio']",
                              fecha_inicio.strftime("%d/%m/%Y"))
                    page.fill("#fechaFin, input[name='fechaFin']",
                              fecha_fin.strftime("%d/%m/%Y"))
                    page.click("#btnConsultar, button:has-text('Consultar')")
                    page.wait_for_load_state("networkidle")

                    filas = page.query_selector_all("table tbody tr")
                    for fila in filas:
                        celdas = fila.query_selector_all("td")
                        if len(celdas) >= 5:
                            textos = [c.inner_text() for c in celdas]
                            movimientos.append({
                                "nss": textos[0].strip(),
                                "nombre": textos[1].strip() if len(textos) > 1 else "",
                                "tipo_movimiento": textos[2].strip() if len(textos) > 2 else "",
                                "fecha": textos[3].strip() if len(textos) > 3 else "",
                                "estado": textos[4].strip() if len(textos) > 4 else "",
                                "folio": textos[5].strip() if len(textos) > 5 else "",
                            })
                except PWTimeout:
                    pass
            finally:
                browser.close()
        return movimientos

    def descargar_acuse(self, folio: str, destino: Optional[str] = None) -> str:
        destino = destino or REPORTS_DIR
        Path(destino).mkdir(parents=True, exist_ok=True)

        with sync_playwright() as pw:
            browser, page = self._iniciar_browser(pw)
            try:
                self._login(page)
                with page.expect_download() as dl:
                    page.goto(f"{URL_IDSE}?opcion=acuse&folio={folio}")
                download = dl.value

                nombre = f"acuse_IDSE_{folio}_{datetime.now().strftime('%Y%m%d')}.pdf"
                ruta = os.path.join(destino, nombre)
                download.save_as(ruta)
            finally:
                browser.close()

        return ruta

    def consultar_incapacidades(self, fecha_inicio: date, fecha_fin: date) -> list[dict]:
        incapacidades = []
        with sync_playwright() as pw:
            browser, page = self._iniciar_browser(pw)
            try:
                self._login(page)
                page.goto(URL_IDSE + "?opcion=incapacidades")
                page.wait_for_load_state("networkidle")

                try:
                    page.fill("#fechaInicio, input[name='fechaInicio']",
                              fecha_inicio.strftime("%d/%m/%Y"))
                    page.fill("#fechaFin, input[name='fechaFin']",
                              fecha_fin.strftime("%d/%m/%Y"))
                    page.click("#btnConsultar, button:has-text('Consultar')")
                    page.wait_for_load_state("networkidle")

                    filas = page.query_selector_all("table tbody tr")
                    for fila in filas:
                        celdas = fila.query_selector_all("td")
                        if len(celdas) >= 6:
                            textos = [c.inner_text() for c in celdas]
                            incapacidades.append({
                                "nss": textos[0].strip(),
                                "nombre": textos[1].strip() if len(textos) > 1 else "",
                                "folio": textos[2].strip() if len(textos) > 2 else "",
                                "tipo": textos[3].strip() if len(textos) > 3 else "",
                                "fecha_inicio": textos[4].strip() if len(textos) > 4 else "",
                                "dias": textos[5].strip() if len(textos) > 5 else "",
                                "estado": textos[6].strip() if len(textos) > 6 else "",
                            })
                except PWTimeout:
                    pass
            finally:
                browser.close()
        return incapacidades


# API directa para Streamlit (sin asyncio)
def consultar_movimientos_sync(registro: str, usuario: str, password: str,
                               cert_path: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
    return IDSEScraper(registro, usuario, password, cert_path).consultar_movimientos(fecha_inicio, fecha_fin)


def consultar_incapacidades_sync(registro: str, usuario: str, password: str,
                                 cert_path: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
    return IDSEScraper(registro, usuario, password, cert_path).consultar_incapacidades(fecha_inicio, fecha_fin)
