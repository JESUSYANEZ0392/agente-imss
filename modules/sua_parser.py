"""
Parser de archivos .SUA — basado en el formato REAL observado en producción.

Estructura de registros (prefijo de 2 dígitos + RP):
  02 = Patrón (encabezado + totales de cuotas)
  03 = Trabajador
  04 = Movimientos afiliatorios
  05 = Resumen de cuotas por ramo
  06 = Datos de pago (SIPARE / línea de captura)

Los valores monetarios se almacenan en CENTAVOS (entero / 100 = pesos).
Las cuotas se calculan desde los SDIs de los trabajadores usando tarifas LSS 2025.
"""
import calendar
import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

# Tarifas IMSS 2025 (LSS Arts. 106-168)
UMA_DIARIA_2025   = 117.31
UMA_MENSUAL_2025  = UMA_DIARIA_2025 * 30.4   # 3,300.53
TOPE_SDI_25_UMAS  = UMA_DIARIA_2025 * 25      # 2,714.25

# Tasas patronales por ramo (como decimal)
_TASA_EMYM_CF      = 0.2040   # Cuota fija EyM: 20.40% de UMA mensual por trabajador/mes
_TASA_EMYM_EXC_PAT = 0.0110   # EyM excedente 3 UMAs: patronal
_TASA_EMYM_EXC_OBR = 0.0040   # EyM excedente 3 UMAs: obrera
_TASA_PREST_PAT    = 0.0070   # Prestaciones en dinero: patronal
_TASA_PREST_OBR    = 0.0025   # Prestaciones en dinero: obrera
_TASA_IV_PAT       = 0.0175   # Invalidez y Vida: patronal
_TASA_IV_OBR       = 0.00625  # Invalidez y Vida: obrera
_TASA_GUARD        = 0.0100   # Guarderías: patronal
_TASA_RETIRO       = 0.0200   # Retiro: patronal
_TASA_CES_PAT      = 0.03150  # Cesantía y Vejez: patronal
_TASA_CES_OBR      = 0.01125  # Cesantía y Vejez: obrera
_TASA_INFONAVIT    = 0.0500   # INFONAVIT: patronal


# ── Modelos de datos ─────────────────────────────────────────────────────────

@dataclass
class DatosPatronSUA:
    registro_patronal: str
    razon_social: str = ""
    rfc: str = ""
    periodo: str = ""          # YYYYMM
    folio: str = ""
    clase_riesgo: str = ""
    actividad: str = ""


@dataclass
class TrabajadorSUA:
    nss: str
    rfc: str
    curp: str
    nombre: str
    tipo_trabajador: str       # 01=Alta/Permanente, 02=Baja/Variable
    salario_diario: float      # SDI en pesos
    fecha_baja: Optional[date] = None
    movimiento: str = ""
    departamento: str = ""


@dataclass
class MovimientoSUA:
    nss: str
    tipo: str                  # 01=Alta, 02=Baja, etc.
    fecha: Optional[date] = None
    salario: float = 0.0


@dataclass
class CuotasTotalesSUA:
    """Totales del bimestre extraídos del registro 06."""
    masa_salarial: float = 0.0
    cuotas_imss: float = 0.0
    cuotas_infonavit: float = 0.0
    fecha_limite_pago: str = ""
    linea_captura: str = ""
    total_pagar: float = 0.0

    # Desglose del registro 05
    emym_patronal: float = 0.0
    riesgo_trabajo: float = 0.0
    invalidez_vida: float = 0.0
    guarderias: float = 0.0
    cesantia_vejez: float = 0.0
    retiro: float = 0.0


@dataclass
class ResultadoSUA:
    patron: Optional[DatosPatronSUA] = None
    trabajadores: list[TrabajadorSUA] = field(default_factory=list)
    movimientos: list[MovimientoSUA] = field(default_factory=list)
    cuotas: Optional[CuotasTotalesSUA] = None
    errores: list[str] = field(default_factory=list)
    hash_archivo: str = ""
    nombre_archivo: str = ""


# ── Utilidades ────────────────────────────────────────────────────────────────

def _to_pesos(s: str) -> float:
    """Convierte cadena de centavos a pesos (divide entre 100)."""
    try:
        val = s.strip().lstrip("0") or "0"
        return int(val) / 100
    except (ValueError, AttributeError):
        return 0.0


def _parse_fecha(s: str) -> Optional[date]:
    s = (s or "").strip()
    if not s or s == "00000000" or len(s) < 8:
        return None
    try:
        return datetime.strptime(s[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _limpiar_nombre(nombre_sua: str) -> str:
    """'MATA$ALCANTARA$MANUEL' → 'MATA ALCANTARA MANUEL'"""
    return nombre_sua.replace("$", " ").strip()


# ── Parser principal ──────────────────────────────────────────────────────────

class SUAParser:
    """
    Parser del formato SUA real (observado en W2506461.SUA de MULTISERVICIOS LEMESA).
    Divide el contenido en registros por el patrón: NN + RP conocido.
    """

    def parse_file(self, filepath: str) -> ResultadoSUA:
        resultado = ResultadoSUA()
        resultado.nombre_archivo = os.path.basename(filepath)

        if not os.path.exists(filepath):
            resultado.errores.append(f"Archivo no encontrado: {filepath}")
            return resultado

        with open(filepath, "rb") as f:
            raw = f.read()
        resultado.hash_archivo = hashlib.sha256(raw).hexdigest()

        # Decodificar (SUA usa latin-1)
        try:
            contenido = raw.decode("latin-1")
        except UnicodeDecodeError:
            contenido = raw.decode("utf-8", errors="replace")

        # Paso 1: detectar el Registro Patronal desde el primer "02"
        rp = self._detectar_rp(contenido)
        if not rp:
            resultado.errores.append("No se pudo detectar el Registro Patronal en el archivo.")
            return resultado

        # Paso 2: dividir en registros usando el RP como ancla
        registros = self._dividir_registros(contenido, rp)

        for tipo, datos in registros:
            try:
                if tipo == "02":
                    resultado.patron = self._parse_patron(datos, rp)
                elif tipo == "03":
                    trab = self._parse_trabajador(datos)
                    if trab:
                        resultado.trabajadores.append(trab)
                elif tipo == "04":
                    movs = self._parse_movimientos(datos)
                    resultado.movimientos.extend(movs)
                elif tipo == "05":
                    if resultado.cuotas is None:
                        resultado.cuotas = CuotasTotalesSUA()
                    self._parse_cuotas_05(datos, resultado.cuotas)
                elif tipo == "06":
                    if resultado.cuotas is None:
                        resultado.cuotas = CuotasTotalesSUA()
                    self._parse_cuotas_06(datos, resultado.cuotas)
            except Exception as e:
                resultado.errores.append(f"Error en registro {tipo}: {e}")

        # Calcular cuotas desde SDIs si el archivo no las proporcionó correctamente
        if resultado.trabajadores:
            periodo = resultado.patron.periodo if resultado.patron else ""
            cuotas_calc = self._calcular_cuotas_trabajadores(resultado.trabajadores, periodo)
            if resultado.cuotas is None:
                resultado.cuotas = cuotas_calc
            else:
                # Reemplazar montos solo si los del archivo parecen incorrectos
                masa = cuotas_calc.masa_salarial
                imss_archivo = resultado.cuotas.cuotas_imss
                # IMSS real nunca puede superar el 50% de la masa salarial
                if imss_archivo == 0 or (masa > 0 and imss_archivo > masa * 0.50):
                    resultado.cuotas.cuotas_imss      = cuotas_calc.cuotas_imss
                    resultado.cuotas.cuotas_infonavit = cuotas_calc.cuotas_infonavit
                    resultado.cuotas.total_pagar      = cuotas_calc.total_pagar
                    resultado.cuotas.masa_salarial    = cuotas_calc.masa_salarial
                    resultado.cuotas.emym_patronal    = cuotas_calc.emym_patronal
                    resultado.cuotas.riesgo_trabajo   = cuotas_calc.riesgo_trabajo
                    resultado.cuotas.invalidez_vida   = cuotas_calc.invalidez_vida
                    resultado.cuotas.guarderias       = cuotas_calc.guarderias
                    resultado.cuotas.cesantia_vejez   = cuotas_calc.cesantia_vejez
                    resultado.cuotas.retiro           = cuotas_calc.retiro

        return resultado

    # ── Detección de RP ───────────────────────────────────────────────────────

    def _detectar_rp(self, contenido: str) -> str:
        """Extrae el registro patronal del primer registro '02'."""
        m = re.search(r"02([A-Z0-9]{11})", contenido)
        return m.group(1) if m else ""

    # ── División de registros ─────────────────────────────────────────────────

    def _dividir_registros(self, contenido: str, rp: str) -> list[tuple[str, str]]:
        """
        Divide el contenido en lista de (tipo_registro, datos_completos).
        Busca el patrón NN + RP donde NN es 02-09.
        """
        patron = re.compile(r"(0[2-9])" + re.escape(rp))
        matches = list(patron.finditer(contenido))
        registros = []
        for i, m in enumerate(matches):
            tipo = m.group(1)
            inicio = m.start()
            fin = matches[i + 1].start() if i + 1 < len(matches) else len(contenido)
            registros.append((tipo, contenido[inicio:fin]))
        return registros

    # ── Registro 02: Patrón ───────────────────────────────────────────────────

    def _parse_patron(self, datos: str, rp: str) -> DatosPatronSUA:
        """
        Formato observado:
        02{RP}(espacio){NRP(12)}{YYYYMM}{Folio(6)}...{RazonSocial}...{Actividad}
        """
        patron = DatosPatronSUA(registro_patronal=rp)
        try:
            patron.periodo = datos[14:20].strip()
            patron.folio   = datos[20:26].strip()

            # Razón social: buscar texto mayúsculas de longitud razonable
            m_rs = re.search(r"[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\s,\.]{10,80}(?:SC|SA|SAS|CV|SRL)?", datos[30:])
            if m_rs:
                patron.razon_social = m_rs.group(0).strip()

            # Actividad: suele aparecer después de la razón social
            partes = re.findall(r"[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\s]{15,80}", datos[100:])
            if len(partes) >= 2:
                patron.actividad = partes[-1].strip()

        except Exception:
            pass
        return patron

    # ── Registro 03: Trabajador ───────────────────────────────────────────────

    def _parse_trabajador(self, datos: str) -> Optional[TrabajadorSUA]:
        """
        Posiciones fijas en el registro 03 (observadas en el archivo real):
        0-1   : "03"
        2-12  : RP (11)
        13    : espacio
        14-25 : NRP (12)
        26-31 : periodo YYYYMM (6)
        32-42 : NSS (11)
        43-55 : RFC (13)
        56-73 : CURP (18)
        74-91 : padding (18)
        92-93 : tipo_trabajador
        94-143: nombre con $ (50)
        144+  : datos numéricos (SDI en primeros 7 chars)
        """
        if len(datos) < 150:
            return None

        nss  = datos[32:43].strip()
        rfc  = datos[43:56].strip()
        curp = datos[56:74].strip()
        tipo = datos[92:94].strip()
        nombre_raw = datos[94:144].strip()
        nombre = _limpiar_nombre(nombre_raw)

        # SDI: primeros 7 dígitos de la sección numérica (centavos → pesos)
        num = datos[144:]
        sdi = 0.0
        m_num = re.match(r"(\d{7})", num)
        if m_num:
            sdi = int(m_num.group(1)) / 100  # e.g. 0029380 → 293.80

        if not nss:
            return None

        return TrabajadorSUA(
            nss=nss,
            rfc=rfc,
            curp=curp,
            nombre=nombre,
            tipo_trabajador=tipo,
            salario_diario=sdi,
        )

    # ── Registro 04: Movimientos ──────────────────────────────────────────────

    def _parse_movimientos(self, datos: str) -> list[MovimientoSUA]:
        """
        El registro 04 contiene múltiples altas/bajas concatenadas.
        Patrón: NSS(11) + TipoMov(2) + Fecha(8) + espacios + Salario(9)
        """
        movimientos = []
        # Cada entrada tiene NSS de 11 dígitos seguido de tipo movimiento
        patron_mov = re.compile(r"(\d{11})(\d{2})(\d{8})\s+(\d{9})")
        for m in patron_mov.finditer(datos[13:]):  # saltar "04" + RP
            movimientos.append(MovimientoSUA(
                nss=m.group(1),
                tipo=m.group(2),
                fecha=_parse_fecha(m.group(3)),
                salario=int(m.group(4)) / 100,
            ))
        return movimientos

    # ── Cálculo de cuotas desde SDIs ─────────────────────────────────────────

    def _calcular_cuotas_trabajadores(
        self,
        trabajadores: list,
        periodo: str = "",
        prima_rt: float = 0.0054355,  # Clase I default
    ) -> "CuotasTotalesSUA":
        """
        Calcula cuotas IMSS e INFONAVIT desde los SDIs de los trabajadores.
        Exactamente la misma fórmula que usa el SUA internamente (LSS 2025).
        """
        dias = self._dias_bimestre(periodo)
        cuotas = CuotasTotalesSUA()

        imss_patron = 0.0
        imss_obrero = 0.0
        infonavit   = 0.0
        masa        = 0.0

        for t in trabajadores:
            sdi  = min(t.salario_diario, TOPE_SDI_25_UMAS)
            m    = sdi * dias           # masa salarial individual
            masa += m

            # Cuota fija EyM (20.40% UMA mensual, por trabajador, × 2 meses)
            cf  = _TASA_EMYM_CF * UMA_MENSUAL_2025 * 2

            # EyM adicional sobre excedente de 3 UMAs
            exc = max(0.0, sdi - UMA_DIARIA_2025 * 3) * dias
            emym_pat = cf + exc * _TASA_EMYM_EXC_PAT
            emym_obr = exc * _TASA_EMYM_EXC_OBR

            # Prestaciones en dinero
            prest_pat = m * _TASA_PREST_PAT
            prest_obr = m * _TASA_PREST_OBR

            # Invalidez y Vida
            iv_pat = m * _TASA_IV_PAT
            iv_obr = m * _TASA_IV_OBR

            # Guarderías
            guard = m * _TASA_GUARD

            # Riesgo de Trabajo
            rt = m * prima_rt

            # Retiro
            retiro = m * _TASA_RETIRO

            # Cesantía y Vejez
            ces_pat = m * _TASA_CES_PAT
            ces_obr = m * _TASA_CES_OBR

            imss_patron += emym_pat + prest_pat + iv_pat + guard + rt + retiro + ces_pat
            imss_obrero += emym_obr + prest_obr + iv_obr + ces_obr
            infonavit   += sdi * dias * _TASA_INFONAVIT

        cuotas.masa_salarial      = round(masa, 2)
        cuotas.cuotas_imss        = round(imss_patron + imss_obrero, 2)
        cuotas.cuotas_infonavit   = round(infonavit, 2)
        cuotas.total_pagar        = round(cuotas.cuotas_imss + cuotas.cuotas_infonavit, 2)

        # Desglose aproximado por ramo (patronal)
        if trabajadores:
            dias_t = dias
            s_avg = masa / len(trabajadores) / dias_t if dias_t else 0
            cuotas.emym_patronal  = round(len(trabajadores) * (_TASA_EMYM_CF * UMA_MENSUAL_2025 * 2), 2)
            cuotas.riesgo_trabajo = round(masa * prima_rt, 2)
            cuotas.invalidez_vida = round(masa * _TASA_IV_PAT, 2)
            cuotas.guarderias     = round(masa * _TASA_GUARD, 2)
            cuotas.cesantia_vejez = round(masa * _TASA_CES_PAT, 2)
            cuotas.retiro         = round(masa * _TASA_RETIRO, 2)

        return cuotas

    def _dias_bimestre(self, periodo: str) -> int:
        """Devuelve los días del bimestre para el período YYYYMM."""
        try:
            if len(periodo) >= 6:
                year  = int(periodo[:4])
                month = int(periodo[4:6])
                d1 = calendar.monthrange(year, month)[1]
                m2 = month + 1 if month < 12 else 1
                y2 = year if month < 12 else year + 1
                d2 = calendar.monthrange(y2, m2)[1]
                return d1 + d2
        except Exception:
            pass
        return 61   # default: enero-febrero

    # ── Registro 05: Desglose de cuotas ──────────────────────────────────────

    def _parse_cuotas_05(self, datos: str, cuotas: CuotasTotalesSUA):
        """
        El registro 05 tiene los subtotales por ramo de seguro.
        Orden observado: EMyM, RT, IV, Guarderías, Cesantía, Obrero, Retiro (13 dígitos c/u)
        Luego: MasaSalarial (15 dígitos), IMSS total (13), INFONAVIT total (13).
        """
        num = datos[36:]
        nums = re.findall(r"\d{13}", num)

        try:
            if len(nums) >= 1: cuotas.emym_patronal  = int(nums[0]) / 100
            if len(nums) >= 2: cuotas.riesgo_trabajo = int(nums[1]) / 100
            if len(nums) >= 3: cuotas.invalidez_vida = int(nums[2]) / 100
            if len(nums) >= 4: cuotas.guarderias     = int(nums[3]) / 100
            if len(nums) >= 5: cuotas.cesantia_vejez = int(nums[4]) / 100
            if len(nums) >= 7: cuotas.retiro         = int(nums[6]) / 100

            # Masa salarial: campo de 15 dígitos exactos
            m_masa = re.search(r"(?<!\d)(\d{15})(?!\d)", num)
            if m_masa:
                cuotas.masa_salarial = int(m_masa.group(1)) / 100
                # Después de masa salarial vienen IMSS total e INFONAVIT
                resto = num[m_masa.end():]
                totales = re.findall(r"\d{13}", resto)
                if len(totales) >= 1:
                    cuotas.cuotas_imss = int(totales[0]) / 100
                if len(totales) >= 2:
                    cuotas.cuotas_infonavit = int(totales[1]) / 100

            # Fallback: si no se encontraron totales, sumar los ramos
            if cuotas.cuotas_imss == 0:
                cuotas.cuotas_imss = round(
                    cuotas.emym_patronal + cuotas.riesgo_trabajo +
                    cuotas.invalidez_vida + cuotas.guarderias +
                    cuotas.cesantia_vejez + cuotas.retiro, 2
                )

            if cuotas.cuotas_imss > 0 or cuotas.cuotas_infonavit > 0:
                cuotas.total_pagar = round(cuotas.cuotas_imss + cuotas.cuotas_infonavit, 2)

        except Exception:
            pass

    # ── Registro 06: Metadatos de pago (SIPARE) ───────────────────────────────

    def _parse_cuotas_06(self, datos: str, cuotas: CuotasTotalesSUA):
        """
        Registro 06 — solo extrae fecha límite y línea de captura.
        Los montos se leen desde el registro 05 para evitar confundir
        la línea de captura SIPARE (20+ dígitos) con campos monetarios.
        """
        num = datos[36:]

        # Fecha límite de pago (YYYYMMDD)
        m_fecha = re.search(r"(202[0-9][0-1][0-9][0-3][0-9])", num)
        if m_fecha:
            f = m_fecha.group(1)
            cuotas.fecha_limite_pago = f"{f[6:8]}/{f[4:6]}/{f[:4]}"

        # Línea de captura SIPARE (20-25 dígitos)
        m_lc = re.search(r"(?<!\d)(\d{20,25})(?!\d)", num)
        if m_lc:
            cuotas.linea_captura = m_lc.group(1)


# ── API pública ───────────────────────────────────────────────────────────────

def parse_sua(filepath: str) -> ResultadoSUA:
    return SUAParser().parse_file(filepath)


def sua_a_dict(resultado: ResultadoSUA) -> list[dict]:
    filas = []
    rp = resultado.patron.registro_patronal if resultado.patron else ""
    periodo = resultado.patron.periodo if resultado.patron else ""
    for t in resultado.trabajadores:
        filas.append({
            "Registro Patronal": rp,
            "Período": periodo,
            "NSS": t.nss,
            "RFC": t.rfc,
            "CURP": t.curp,
            "Nombre": t.nombre,
            "Tipo": "Alta/Activo" if t.tipo_trabajador == "01" else "Baja/Variable",
            "SDI ($)": t.salario_diario,
        })
    return filas
