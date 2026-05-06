"""
Automatización del portal SIPARE (Sistema de Pago Referenciado - IMSS).
Descarga líneas de captura y comprobantes de pago bimestral.
"""
import asyncio
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PWTimeout

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
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    async def _iniciar_browser(self, playwright):
        self._browser = await playwright.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox"],
        )
        context = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            accept_downloads=True,
        )
        self._page = await context.new_page()
        self._page.set_default_timeout(self.timeout_ms)

    async def _login(self):
        page = self._page
        await page.goto(URL_SIPARE)
        await page.wait_for_load_state("networkidle")

        # Llenar RFC/usuario y contraseña
        await page.fill("input[name='usuario'], #rfc, input[type='text']", self.usuario)
        await page.fill("input[name='password'], #password, input[type='password']", self.password)

        if self.cert_path and os.path.exists(self.cert_path):
            cert_input = page.locator("input[type='file']")
            if await cert_input.count() > 0:
                await cert_input.set_input_files(self.cert_path)

        await page.click("button[type='submit'], input[type='submit'], #btnEntrar")
        await page.wait_for_load_state("networkidle")

        if "error" in page.url.lower():
            raise RuntimeError("Error de autenticación en SIPARE.")

    async def obtener_referencia_pago(self, anio: int, bimestre: int) -> dict:
        """
        Genera/consulta la línea de captura para el bimestre indicado.
        Retorna dict con línea de captura, monto, fecha límite.
        """
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

        async with async_playwright() as pw:
            await self._iniciar_browser(pw)
            try:
                await self._login()
                page = self._page

                # Navegar a generación de referencia
                await page.goto(URL_SIPARE + "generarReferencia")
                await page.wait_for_load_state("networkidle")

                # Seleccionar año
                anio_sel = page.locator("select[name='anio'], #anio")
                if await anio_sel.count() > 0:
                    await anio_sel.select_option(str(anio))

                # Seleccionar bimestre
                bim_sel = page.locator("select[name='bimestre'], #bimestre")
                if await bim_sel.count() > 0:
                    await bim_sel.select_option(str(bimestre))

                await page.click("#btnGenerar, button:has-text('Generar')")
                await page.wait_for_load_state("networkidle")

                # Extraer línea de captura y monto
                lc_elem = page.locator("#lineaCaptura, .linea-captura, td:has-text('Línea de captura') + td")
                if await lc_elem.count() > 0:
                    resultado["linea_captura"] = (await lc_elem.first.inner_text()).strip()

                monto_elem = page.locator("#montoTotal, .monto-total")
                if await monto_elem.count() > 0:
                    monto_str = (await monto_elem.first.inner_text()).strip()
                    monto_str = monto_str.replace("$", "").replace(",", "").strip()
                    try:
                        resultado["monto_total"] = float(monto_str)
                    except ValueError:
                        pass

                fecha_elem = page.locator("#fechaLimite, .fecha-limite")
                if await fecha_elem.count() > 0:
                    resultado["fecha_limite"] = (await fecha_elem.first.inner_text()).strip()

            except Exception as e:
                resultado["error"] = str(e)
            finally:
                await self._browser.close()

        return resultado

    async def descargar_sipare_pdf(self, anio: int, bimestre: int,
                                   destino: Optional[str] = None) -> str:
        """Descarga el PDF SIPARE del bimestre indicado."""
        destino = destino or REPORTS_DIR
        Path(destino).mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            await self._iniciar_browser(pw)
            await self._login()
            page = self._page

            try:
                async with page.expect_download(timeout=60000) as dl:
                    await page.goto(URL_SIPARE + f"descargar?anio={anio}&bimestre={bimestre}")
                    download = await dl.value

                nombre = (f"SIPARE_{self.registro_patronal}_{anio}_B{bimestre}_"
                          f"{datetime.now().strftime('%Y%m%d')}.pdf")
                ruta = os.path.join(destino, nombre)
                await download.save_as(ruta)
            finally:
                await self._browser.close()

        return ruta

    async def consultar_historico_pagos(self, anio_inicio: int, anio_fin: int) -> list[dict]:
        """Consulta el histórico de pagos bimestrales en el rango de años."""
        pagos = []
        async with async_playwright() as pw:
            await self._iniciar_browser(pw)
            await self._login()
            page = self._page

            try:
                await page.goto(URL_SIPARE + "historicoPagos")
                await page.wait_for_load_state("networkidle")

                await page.fill("#anioInicio", str(anio_inicio))
                await page.fill("#anioFin", str(anio_fin))
                await page.click("#btnConsultar, button:has-text('Consultar')")
                await page.wait_for_load_state("networkidle")

                filas = await page.query_selector_all("table tbody tr")
                for fila in filas:
                    celdas = await fila.query_selector_all("td")
                    if len(celdas) >= 5:
                        textos = [await c.inner_text() for c in celdas]
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
                await self._browser.close()

        return pagos


# API síncrona
def obtener_referencia_sync(registro: str, usuario: str, password: str,
                            cert_path: str, anio: int, bimestre: int) -> dict:
    scraper = SIPAREScraper(registro, usuario, password, cert_path)
    return asyncio.run(scraper.obtener_referencia_pago(anio, bimestre))


def descargar_sipare_sync(registro: str, usuario: str, password: str,
                          cert_path: str, anio: int, bimestre: int,
                          destino: Optional[str] = None) -> str:
    scraper = SIPAREScraper(registro, usuario, password, cert_path)
    return asyncio.run(scraper.descargar_sipare_pdf(anio, bimestre, destino))
