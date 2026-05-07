"""
Confronta SUA vs Cédula de Determinación (XLS del IMSS).
Compara trabajadores, salarios y cuotas entre ambos documentos.
Emite alarmas cuando hay diferencias superiores a la tolerancia de redondeo.
"""
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

TOLERANCIA = 1.0  # Diferencia máxima en pesos considerada "igual" (redondeo)


@dataclass
class DiferenciaWorker:
    nss: str
    nombre: str
    campo: str
    valor_sua: float | str
    valor_xls: float | str
    diferencia: float
    nivel: str  # "ok", "alerta", "error"
    mensaje: str


@dataclass
class ResultadoConfronta:
    total_trabajadores_sua: int = 0
    total_trabajadores_xls: int = 0
    trabajadores_solo_sua: list[str] = field(default_factory=list)
    trabajadores_solo_xls: list[str] = field(default_factory=list)
    diferencias: list[DiferenciaWorker] = field(default_factory=list)
    resumen_totales: dict = field(default_factory=dict)

    @property
    def tiene_errores(self):
        return any(d.nivel == "error" for d in self.diferencias)

    @property
    def tiene_alertas(self):
        return any(d.nivel == "alerta" for d in self.diferencias)

    @property
    def todo_ok(self):
        return not self.diferencias and not self.trabajadores_solo_sua and not self.trabajadores_solo_xls


def _limpiar_nss(nss) -> str:
    """Normaliza NSS a 11 dígitos string."""
    return str(nss).strip().zfill(11)


def _limpiar_nombre(nombre: str) -> str:
    return str(nombre).strip().upper()


def _leer_ema(ruta_xls: str) -> pd.DataFrame:
    """Lee la hoja EMA (cuotas IMSS por trabajador)."""
    xl = pd.ExcelFile(ruta_xls)
    # Buscar hoja que contenga "EMA" o "Movimientos"
    hoja_ema = next(
        (s for s in xl.sheet_names if "EMA" in s.upper() or ("MOVIM" in s.upper() and "EBA" not in s.upper())),
        xl.sheet_names[1] if len(xl.sheet_names) > 1 else xl.sheet_names[0]
    )
    df = pd.read_excel(ruta_xls, sheet_name=hoja_ema, header=None)

    # Encontrar fila de encabezados (contiene "NSS")
    header_row = None
    for i, row in df.iterrows():
        if any(str(v).strip().upper() == "NSS" for v in row if pd.notna(v)):
            header_row = i
            break

    if header_row is None:
        raise ValueError("No se encontró la fila de encabezados en la hoja EMA.")

    df.columns = [str(v).strip() if pd.notna(v) else f"col_{i}" for i, v in enumerate(df.iloc[header_row])]
    df = df.iloc[header_row + 1:].reset_index(drop=True)
    df = df[df["NSS"].notna() & (df["NSS"] != "NSS")]

    # Normalizar NSS
    df["NSS"] = df["NSS"].apply(_limpiar_nss)

    # Renombrar columnas a nombres estándar
    rename = {}
    for col in df.columns:
        cu = col.upper()
        if "SALARIO" in cu and "DIARIO" in cu:
            rename[col] = "salario_diario"
        elif "CUOTA" in cu and "FIJA" in cu:
            rename[col] = "cuota_fija"
        elif "EXCEDENTE" in cu and "PATRON" in cu:
            rename[col] = "excedente_patronal"
        elif "EXCEDENTE" in cu and "OBRERO" in cu:
            rename[col] = "excedente_obrero"
        elif "PRESTACIONES" in cu and "DINERO" in cu and "PATRON" in cu:
            rename[col] = "prest_dinero_pat"
        elif "PRESTACIONES" in cu and "DINERO" in cu and "OBRERO" in cu:
            rename[col] = "prest_dinero_obr"
        elif ("GASTOS" in cu or "GMP" in cu) and "PATRON" in cu:
            rename[col] = "gmp_patronal"
        elif ("GASTOS" in cu or "GMP" in cu) and "OBRERO" in cu:
            rename[col] = "gmp_obrero"
        elif "RIESGOS" in cu or "RIESGO" in cu:
            rename[col] = "riesgo_trabajo"
        elif "INVALIDEZ" in cu and "VIDA" in cu and "PATRON" in cu:
            rename[col] = "inv_vida_pat"
        elif "INVALIDEZ" in cu and "VIDA" in cu and "OBRERO" in cu:
            rename[col] = "inv_vida_obr"
        elif "GUARDER" in cu:
            rename[col] = "guarderias"
        elif col.upper() == "TOTAL":
            rename[col] = "total_imss"
        elif "D" in cu and "AS" in cu and len(col) < 6:
            rename[col] = "dias"
        elif "NOMBRE" in cu:
            rename[col] = "nombre"

    df = df.rename(columns=rename)
    return df


def _leer_eba(ruta_xls: str) -> pd.DataFrame:
    """Lee la hoja EBA (RCV + INFONAVIT por trabajador)."""
    xl = pd.ExcelFile(ruta_xls)
    hoja_eba = next(
        (s for s in xl.sheet_names if "EBA" in s.upper()),
        xl.sheet_names[2] if len(xl.sheet_names) > 2 else xl.sheet_names[0]
    )
    df = pd.read_excel(ruta_xls, sheet_name=hoja_eba, header=None)

    header_row = None
    for i, row in df.iterrows():
        if any(str(v).strip().upper() == "NSS" for v in row if pd.notna(v)):
            header_row = i
            break

    if header_row is None:
        raise ValueError("No se encontró la fila de encabezados en la hoja EBA.")

    df.columns = [str(v).strip() if pd.notna(v) else f"col_{i}" for i, v in enumerate(df.iloc[header_row])]
    df = df.iloc[header_row + 1:].reset_index(drop=True)
    df = df[df["NSS"].notna() & (df["NSS"] != "NSS")]
    df["NSS"] = df["NSS"].apply(_limpiar_nss)

    rename = {}
    for col in df.columns:
        cu = col.upper()
        if "SALARIO" in cu and "DIARIO" in cu:
            rename[col] = "salario_diario"
        elif "RETIRO" in cu:
            rename[col] = "retiro"
        elif "CESANT" in cu and "PATRON" in cu:
            rename[col] = "cesantia_pat"
        elif "CESANT" in cu and "OBRERO" in cu:
            rename[col] = "cesantia_obr"
        elif "SUBTOTAL" in cu and "RCV" in cu:
            rename[col] = "subtotal_rcv"
        elif "APORTACI" in cu and "PATRON" in cu:
            rename[col] = "aportacion_infonavit"
        elif "AMORTIZ" in cu:
            rename[col] = "amortizacion"
        elif "SUBTOTAL" in cu and "INFO" in cu:
            rename[col] = "subtotal_infonavit"
        elif col.upper() == "TOTAL":
            rename[col] = "total_eba"
        elif "NOMBRE" in cu:
            rename[col] = "nombre"

    df = df.rename(columns=rename)
    return df


def _to_float(val) -> float:
    try:
        if pd.isna(val):
            return 0.0
        return float(str(val).replace(",", "").replace("$", "").strip() or 0)
    except Exception:
        return 0.0


def confrontar(ruta_sua: str, ruta_xls: str) -> ResultadoConfronta:
    """
    Confronta el archivo SUA con la cédula XLS del IMSS.
    Retorna ResultadoConfronta con todas las diferencias encontradas.
    """
    from modules.sua_parser import parse_sua

    resultado = ResultadoConfronta()

    # ── Leer SUA ─────────────────────────────────────────────────────────────
    sua = parse_sua(ruta_sua)
    workers_sua = {_limpiar_nss(w.nss): w for w in sua.trabajadores}
    resultado.total_trabajadores_sua = len(workers_sua)

    # ── Leer XLS ─────────────────────────────────────────────────────────────
    ema = _leer_ema(ruta_xls)
    eba = _leer_eba(ruta_xls)

    # Solo filas con días > 0 (ignorar movimientos de baja sin cuotas)
    if "dias" in ema.columns:
        ema_activos = ema[ema["dias"].apply(_to_float) > 0].copy()
    else:
        ema_activos = ema.copy()

    # Agrupar por NSS sumando cuotas (puede haber 2 filas por trabajador con movimiento)
    cuotas_ema = {}
    for _, row in ema_activos.iterrows():
        nss = _limpiar_nss(row["NSS"])
        if nss not in cuotas_ema:
            cuotas_ema[nss] = {
                "nombre": _limpiar_nombre(row.get("nombre", "")),
                "salario_diario": _to_float(row.get("salario_diario", 0)),
                "cuota_fija": _to_float(row.get("cuota_fija", 0)),
                "excedente_patronal": _to_float(row.get("excedente_patronal", 0)),
                "excedente_obrero": _to_float(row.get("excedente_obrero", 0)),
                "prest_dinero_pat": _to_float(row.get("prest_dinero_pat", 0)),
                "prest_dinero_obr": _to_float(row.get("prest_dinero_obr", 0)),
                "gmp_patronal": _to_float(row.get("gmp_patronal", 0)),
                "gmp_obrero": _to_float(row.get("gmp_obrero", 0)),
                "riesgo_trabajo": _to_float(row.get("riesgo_trabajo", 0)),
                "inv_vida_pat": _to_float(row.get("inv_vida_pat", 0)),
                "inv_vida_obr": _to_float(row.get("inv_vida_obr", 0)),
                "guarderias": _to_float(row.get("guarderias", 0)),
                "total_imss": _to_float(row.get("total_imss", 0)),
                "dias": _to_float(row.get("dias", 0)),
            }
        else:
            # Sumar cuotas de filas múltiples del mismo trabajador
            for k in ["cuota_fija","excedente_patronal","excedente_obrero",
                      "prest_dinero_pat","prest_dinero_obr","gmp_patronal",
                      "gmp_obrero","riesgo_trabajo","inv_vida_pat","inv_vida_obr",
                      "guarderias","total_imss","dias"]:
                cuotas_ema[nss][k] += _to_float(row.get(k, 0))

    cuotas_eba = {}
    for _, row in eba.iterrows():
        nss = _limpiar_nss(row["NSS"])
        sd = _to_float(row.get("salario_diario", 0))
        if sd == 0:
            continue
        if nss not in cuotas_eba:
            cuotas_eba[nss] = {
                "retiro": _to_float(row.get("retiro", 0)),
                "cesantia_pat": _to_float(row.get("cesantia_pat", 0)),
                "cesantia_obr": _to_float(row.get("cesantia_obr", 0)),
                "subtotal_rcv": _to_float(row.get("subtotal_rcv", 0)),
                "aportacion_infonavit": _to_float(row.get("aportacion_infonavit", 0)),
                "total_eba": _to_float(row.get("total_eba", 0)),
            }
        else:
            for k in ["retiro","cesantia_pat","cesantia_obr","subtotal_rcv",
                      "aportacion_infonavit","total_eba"]:
                cuotas_eba[nss][k] += _to_float(row.get(k, 0))

    nss_xls = set(cuotas_ema.keys())
    resultado.total_trabajadores_xls = len(nss_xls)

    # ── Trabajadores solo en un lado ─────────────────────────────────────────
    resultado.trabajadores_solo_sua = [
        f"{nss} — {w.nombre}" for nss, w in workers_sua.items() if nss not in nss_xls
    ]
    resultado.trabajadores_solo_xls = [
        f"{nss} — {cuotas_ema[nss]['nombre']}" for nss in nss_xls if nss not in workers_sua
    ]

    # ── Comparar por trabajador ───────────────────────────────────────────────
    for nss in sorted(set(workers_sua.keys()) & nss_xls):
        w = workers_sua[nss]
        ema_w = cuotas_ema[nss]
        eba_w = cuotas_eba.get(nss, {})
        nombre = ema_w["nombre"] or _limpiar_nombre(w.nombre)

        def _check(campo, val_sua, val_xls, etiqueta):
            diff = abs(val_sua - val_xls)
            if diff <= TOLERANCIA:
                nivel = "ok"
                msg = f"✅ {etiqueta}: SUA ${val_sua:,.2f} | XLS ${val_xls:,.2f}"
            elif diff <= TOLERANCIA * 5:
                nivel = "alerta"
                msg = f"⚠️ {etiqueta}: SUA ${val_sua:,.2f} | XLS ${val_xls:,.2f} | Diferencia ${diff:,.2f}"
            else:
                nivel = "error"
                msg = f"🔴 {etiqueta}: SUA ${val_sua:,.2f} | XLS ${val_xls:,.2f} | Diferencia ${diff:,.2f}"

            if nivel != "ok":
                resultado.diferencias.append(DiferenciaWorker(
                    nss=nss, nombre=nombre, campo=campo,
                    valor_sua=round(val_sua, 2), valor_xls=round(val_xls, 2),
                    diferencia=round(diff, 2), nivel=nivel, mensaje=msg
                ))

        # Salario Diario
        _check("salario_diario", w.salario_diario, ema_w["salario_diario"], "Salario Diario")

        # Cuotas IMSS (si el SUA tiene cuotas calculadas, usamos los datos del parser)
        # Las cuotas en SUA están codificadas; comparamos total_imss si está disponible
        if hasattr(sua, "cuotas") and sua.cuotas:
            pass  # Los totales globales se comparan abajo

    # ── Totales globales ─────────────────────────────────────────────────────
    total_xls_imss = sum(v["total_imss"] for v in cuotas_ema.values())
    total_xls_infonavit = sum(v.get("aportacion_infonavit", 0) for v in cuotas_eba.values())
    total_xls_rcv = sum(v.get("subtotal_rcv", 0) for v in cuotas_eba.values())

    sua_cuotas = sua.cuotas
    if sua_cuotas:
        diff_imss = abs(sua_cuotas.cuotas_imss - total_xls_imss)
        diff_infonavit = abs(sua_cuotas.cuotas_infonavit - total_xls_infonavit)

        resultado.resumen_totales = {
            "sua_cuotas_imss": round(sua_cuotas.cuotas_imss, 2),
            "xls_cuotas_imss": round(total_xls_imss, 2),
            "diff_imss": round(diff_imss, 2),
            "sua_infonavit": round(sua_cuotas.cuotas_infonavit, 2),
            "xls_infonavit": round(total_xls_infonavit, 2),
            "diff_infonavit": round(diff_infonavit, 2),
            "xls_rcv": round(total_xls_rcv, 2),
            "match_imss": diff_imss <= TOLERANCIA,
            "match_infonavit": diff_infonavit <= TOLERANCIA,
        }
    else:
        resultado.resumen_totales = {
            "xls_cuotas_imss": round(total_xls_imss, 2),
            "xls_infonavit": round(total_xls_infonavit, 2),
            "xls_rcv": round(total_xls_rcv, 2),
        }

    return resultado


def confrontar_desde_bytes(sua_bytes: bytes, xls_bytes: bytes,
                            nombre_sua: str, nombre_xls: str) -> ResultadoConfronta:
    """Versión para Streamlit: recibe bytes en lugar de rutas de archivo."""
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".sua", delete=False) as f:
        f.write(sua_bytes)
        tmp_sua = f.name
    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as f:
        f.write(xls_bytes)
        tmp_xls = f.name
    try:
        return confrontar(tmp_sua, tmp_xls)
    finally:
        os.unlink(tmp_sua)
        os.unlink(tmp_xls)
