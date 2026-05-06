"""
Automatización del portal IDSE (IMSS Desde Su Empresa).
Usa Playwright en modo headless.
Funciones: consultar movimientos, descargar acuses, verificar estatus.
"""
import asyncio
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PWTimeout

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
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    async def _iniciar_browser(self, playwright):
        self._browser = await playwright.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
        )
        self._page = await context.new_page()
        self._page.set_default_timeout(self.timeout_ms)

    async def _login(self):
        """Inicia sesión en el portal IDSE."""
        page = self._page
        await page.goto(URL_IDSE)

        # Seleccionar método de acceso: usuario y contraseña
        try:
            await page.click("text=Acceso con usuario y contraseña", timeout=5000)
        except PWTimeout:
            pass  # Algunos portales van directamente al formulario

        await page.fill("input[name='usuario'], #usuario, input[type='text']", self.usuario)
        await page.fill("input[name='password'], #password, input[type='password']", self.password)

        # Si requiere certificado IMSS (archivo .cer)
        if self.cert_path and os.path.exists(self.cert_path):
            cert_input = page.locator("input[type='file']")
            if await cert_input.count() > 0:
                await cert_input.set_input_files(self.cert_path)

        await page.click("button[type='submit'], input[type='submit'], #btnAcceder")
        await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)

        # Verificar login exitoso
        if "error" in page.url.lower() or await page.locator(".error, .alerta-error").count() > 0:
            raise RuntimeError("Error de autenticación en IDSE. Verifica usuario/contraseña.")

    async def consultar_movimientos(
        self,
        fecha_inicio: date,
        fecha_fin: date,
    ) -> list[dict]:
        """
        Consulta movimientos afiliatorios del período indicado.
        Retorna lista de movimientos con NSS, tipo, fecha y estado.
        """
        movimientos = []
        async with async_playwright() as pw:
            await self._iniciar_browser(pw)
            await self._login()

            page = self._page
            # Navegar a consulta de movimientos
            await page.goto(URL_IDSE + "?opcion=movimientos")
            await page.wait_for_load_state("networkidle")

            # Llenar fechas
            try:
                await page.fill("#fechaInicio, input[name='fechaInicio']",
                                fecha_inicio.strftime("%d/%m/%Y"))
                await page.fill("#fechaFin, input[name='fechaFin']",
                                fecha_fin.strftime("%d/%m/%Y"))
                await page.click("#btnConsultar, button:has-text('Consultar')")
                await page.wait_for_load_state("networkidle")

                # Extraer tabla de resultados
                filas = await page.query_selector_all("table tbody tr")
                for fila in filas:
                    celdas = await fila.query_selector_all("td")
                    if len(celdas) >= 5:
                        textos = [await c.inner_text() for c in celdas]
                        movimientos.append({
                            "nss": textos[0].strip(),
                            "nombre": textos[1].strip() if len(textos) > 1 else "",
                            "tipo_movimiento": textos[2].strip() if len(textos) > 2 else "",
                            "fecha": textos[3].strip() if len(textos) > 3 else "",
                            "estado": textos[4].strip() if len(textos) > 4 else "",
                            "folio": textos[5].strip() if len(textos) > 5 else "",
                        })
            except PWTimeout:
                pass  # Portal sin resultados o estructura diferente

            await self._browser.close()
        return movimientos

    async def descargar_acuse(self, folio: str, destino: Optional[str] = None) -> str:
        """Descarga el acuse de un movimiento por su folio IDSE."""
        destino = destino or REPORTS_DIR
        Path(destino).mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            await self._iniciar_browser(pw)
            await self._login()

            page = self._page
            try:
                async with page.expect_download() as dl:
                    await page.goto(f"{URL_IDSE}?opcion=acuse&folio={folio}")
                    download = await dl.value

                nombre = f"acuse_IDSE_{folio}_{datetime.now().strftime('%Y%m%d')}.pdf"
                ruta = os.path.join(destino, nombre)
                await download.save_as(ruta)
            finally:
                await self._browser.close()

        return ruta

    async def consultar_incapacidades(
        self,
        fecha_inicio: date,
        fecha_fin: date,
    ) -> list[dict]:
        """Consulta incapacidades registradas para el patrón."""
        incapacidades = []
        async with async_playwright() as pw:
            await self._iniciar_browser(pw)
            await self._login()

            page = self._page
            try:
                await page.goto(URL_IDSE + "?opcion=incapacidades")
                await page.wait_for_load_state("networkidle")
                await page.fill("#fechaInicio, input[name='fechaInicio']",
                                fecha_inicio.strftime("%d/%m/%Y"))
                await page.fill("#fechaFin, input[name='fechaFin']",
                                fecha_fin.strftime("%d/%m/%Y"))
                await page.click("#btnConsultar, button:has-text('Consultar')")
                await page.wait_for_load_state("networkidle")

                filas = await page.query_selector_all("table tbody tr")
                for fila in filas:
                    celdas = await fila.query_selector_all("td")
                    if len(celdas) >= 6:
                        textos = [await c.inner_text() for c in celdas]
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
                await self._browser.close()
        return incapacidades


# API síncrona para usar desde Streamlit
def consultar_movimientos_sync(registro: str, usuario: str, password: str,
                               cert_path: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
    scraper = IDSEScraper(registro, usuario, password, cert_path)
    return asyncio.run(scraper.consultar_movimientos(fecha_inicio, fecha_fin))


def consultar_incapacidades_sync(registro: str, usuario: str, password: str,
                                 cert_path: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
    scraper = IDSEScraper(registro, usuario, password, cert_path)
    return asyncio.run(scraper.consultar_incapacidades(fecha_inicio, fecha_fin))
