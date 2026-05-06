"""
Comparación histórica de períodos (mensual y bimestral).
Detecta variaciones en: cuotas IMSS, SDI, número de trabajadores, incapacidades.
"""
import pandas as pd
from datetime import date
from sqlalchemy.orm import Session
from database.models import (
    Patron, Trabajador, RegistroSalario, PagoSIPARE,
    Incapacidad, ArchivoSUA
)


# ── Comparación de cuotas bimestrales ──────────────────────────────────────

def comparar_sipare(session: Session, patron_id: int,
                    anio: int, bimestre: int) -> dict:
    """
    Compara el bimestre actual vs el anterior para el mismo patrón.
    Retorna variaciones absolutas y porcentuales.
    """
    bim_actual = session.query(PagoSIPARE).filter_by(
        patron_id=patron_id, anio=anio, bimestre=bimestre
    ).first()

    # Período anterior
    bim_ant, anio_ant = (bimestre - 1, anio) if bimestre > 1 else (6, anio - 1)
    bim_anterior = session.query(PagoSIPARE).filter_by(
        patron_id=patron_id, anio=anio_ant, bimestre=bim_ant
    ).first()

    if not bim_actual:
        return {"error": f"No hay datos para B{bimestre}-{anio}"}

    def var(actual, anterior):
        if not anterior or anterior == 0:
            return None
        return round(((actual - anterior) / anterior) * 100, 2)

    return {
        "anio": anio,
        "bimestre": bimestre,
        "periodo_label": bim_actual.periodo_label,
        "monto_actual": bim_actual.monto_total,
        "monto_anterior": bim_anterior.monto_total if bim_anterior else None,
        "variacion_pct": var(
            bim_actual.monto_total,
            bim_anterior.monto_total if bim_anterior else None
        ),
        "cuotas_obrero_actual": bim_actual.monto_cuotas_obrero,
        "cuotas_patronal_actual": bim_actual.monto_cuotas_patronal,
        "retiro_actual": bim_actual.monto_retiro,
        "estado_actual": bim_actual.estado,
        "fecha_limite": str(bim_actual.fecha_limite_pago) if bim_actual.fecha_limite_pago else None,
    }


# ── Comparación de plantilla ────────────────────────────────────────────────

def comparar_plantilla(session: Session, patron_id: int,
                       periodo_actual: str, periodo_anterior: str) -> dict:
    """
    Compara número de trabajadores activos y masa salarial entre dos períodos.
    periodo format: "YYYY-MM" o "YYYY-B1"
    """
    def trajs_periodo(periodo: str) -> pd.DataFrame:
        salarios = (
            session.query(RegistroSalario)
            .join(Trabajador)
            .filter(
                Trabajador.patron_id == patron_id,
                RegistroSalario.periodo == periodo,
            )
            .all()
        )
        if not salarios:
            return pd.DataFrame()
        return pd.DataFrame([{
            "nss": s.trabajador.nss,
            "nombre": s.trabajador.nombre,
            "sdi": s.salario_diario_integrado,
            "sd": s.salario_diario_base,
            "periodo": s.periodo,
        } for s in salarios])

    df_actual = trajs_periodo(periodo_actual)
    df_ant = trajs_periodo(periodo_anterior)

    if df_actual.empty:
        return {"error": f"Sin datos para período {periodo_actual}"}

    resultado = {
        "periodo_actual": periodo_actual,
        "periodo_anterior": periodo_anterior,
        "trabajadores_actual": len(df_actual),
        "trabajadores_anterior": len(df_ant) if not df_ant.empty else None,
        "masa_salarial_actual": round(df_actual["sdi"].sum(), 2),
        "masa_salarial_anterior": round(df_ant["sdi"].sum(), 2) if not df_ant.empty else None,
        "sdi_promedio_actual": round(df_actual["sdi"].mean(), 2),
    }

    if not df_ant.empty:
        # Altas (en actual pero no en anterior)
        nss_actual = set(df_actual["nss"])
        nss_ant = set(df_ant["nss"])
        resultado["altas"] = list(nss_actual - nss_ant)
        resultado["bajas"] = list(nss_ant - nss_actual)
        resultado["var_trabajadores"] = len(df_actual) - len(df_ant)
        var_masa = resultado["masa_salarial_actual"] - resultado["masa_salarial_anterior"]
        resultado["var_masa_salarial"] = round(var_masa, 2)
        resultado["var_masa_pct"] = round(
            (var_masa / resultado["masa_salarial_anterior"]) * 100, 2
        ) if resultado["masa_salarial_anterior"] else None

        # SDI que cambiaron (posibles errores o sin modificación afiliatoria)
        df_merged = df_actual.merge(df_ant, on="nss", suffixes=("_act", "_ant"))
        cambios_sdi = df_merged[df_merged["sdi_act"] != df_merged["sdi_ant"]]
        resultado["cambios_sdi"] = cambios_sdi[[
            "nss", "nombre_act", "sdi_ant", "sdi_act"
        ]].rename(columns={"nombre_act": "nombre"}).to_dict(orient="records")

    return resultado


# ── Tendencia histórica ─────────────────────────────────────────────────────

def tendencia_cuotas(session: Session, patron_id: int,
                     anios: int = 2) -> list[dict]:
    """Devuelve el histórico de pagos SIPARE para graficar tendencia."""
    pagos = (
        session.query(PagoSIPARE)
        .filter_by(patron_id=patron_id)
        .order_by(PagoSIPARE.anio, PagoSIPARE.bimestre)
        .all()
    )
    return [{
        "anio": p.anio,
        "bimestre": p.bimestre,
        "periodo_label": p.periodo_label,
        "monto_total": p.monto_total,
        "estado": p.estado,
    } for p in pagos]


def tendencia_incapacidades(session: Session, patron_id: int) -> list[dict]:
    """Días de incapacidad agrupados por mes para detectar tendencias."""
    incs = (
        session.query(Incapacidad)
        .join(Trabajador)
        .filter(Trabajador.patron_id == patron_id)
        .all()
    )
    if not incs:
        return []

    data = []
    for i in incs:
        if i.fecha_inicio:
            data.append({
                "mes": i.fecha_inicio.strftime("%Y-%m"),
                "tipo": i.tipo,
                "dias": i.dias or 0,
                "subsidio": i.monto_total_subsidio or 0,
            })
    if not data:
        return []

    df = pd.DataFrame(data)
    resumen = df.groupby(["mes", "tipo"]).agg(
        total_dias=("dias", "sum"),
        total_subsidio=("subsidio", "sum"),
        cantidad=("dias", "count"),
    ).reset_index()
    return resumen.to_dict(orient="records")


def alerta_pagos_vencidos(session: Session) -> list[dict]:
    """Devuelve todos los pagos SIPARE vencidos o próximos a vencer (7 días)."""
    from datetime import timedelta
    hoy = date.today()
    vencimiento_prox = hoy + timedelta(days=7)

    pagos = (
        session.query(PagoSIPARE)
        .join(Patron)
        .filter(
            PagoSIPARE.estado == "pendiente",
            PagoSIPARE.fecha_limite_pago <= vencimiento_prox,
        )
        .all()
    )
    return [{
        "patron": p.patron.razon_social,
        "registro_patronal": p.patron.registro_patronal,
        "periodo": p.periodo_label,
        "monto": p.monto_total,
        "fecha_limite": str(p.fecha_limite_pago),
        "dias_restantes": (p.fecha_limite_pago - hoy).days if p.fecha_limite_pago else None,
        "vencido": p.fecha_limite_pago < hoy if p.fecha_limite_pago else False,
    } for p in pagos]
