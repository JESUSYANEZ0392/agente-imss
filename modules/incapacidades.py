"""
Análisis de incapacidades IMSS.
- Tipos: Enfermedad General (EG), Maternidad, Riesgo de Trabajo (RT), Enfermedad Profesional (EP)
- Subsidios conforme Art. 98 y 101 LSS
- Detección de incapacidades que afectan prima de riesgo
"""
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Optional

# Porcentajes de subsidio por tipo (Art. 98, 101 LSS)
SUBSIDIO_POR_TIPO = {
    "01": {"nombre": "Enfermedad General",       "pct": 0.60, "espera_dias": 3},
    "02": {"nombre": "Maternidad",                "pct": 1.00, "espera_dias": 0},
    "03": {"nombre": "Riesgo de Trabajo",         "pct": 1.00, "espera_dias": 0},
    "04": {"nombre": "Enfermedad Profesional",    "pct": 1.00, "espera_dias": 0},
}

# EG: los primeros 3 días son a cargo del patrón (70% Art. 98 LSS)
# A partir del 4to día el IMSS paga 60% del SDI topado


@dataclass
class DetalleSubsidio:
    """Resultado del cálculo de subsidio de una incapacidad."""
    folio: str
    tipo: str
    nombre_tipo: str
    nss: str
    nombre_trabajador: str
    sdi_trabajador: float
    fecha_inicio: date
    fecha_fin: date
    dias_totales: int
    dias_pagan_patron: int       # Días de espera a cargo del patrón
    dias_pagan_imss: int
    pct_subsidio: float
    subsidio_diario_imss: float
    subsidio_total_imss: float
    impacto_prima_riesgo: bool   # True si es RT/EP y afecta prima
    alertas: list[str] = field(default_factory=list)


def calcular_subsidio(
    tipo: str,
    sdi: float,
    fecha_inicio: date,
    fecha_fin: date,
    folio: str = "",
    nss: str = "",
    nombre: str = "",
    sdi_topado: Optional[float] = None,
) -> DetalleSubsidio:
    """
    Calcula el subsidio de una incapacidad.

    Para EG: 3 días de espera a cargo patrón (60% SDI), después IMSS paga 60%.
    Para RT/EP/Maternidad: IMSS paga desde el 1er día al 100%.
    """
    if tipo not in SUBSIDIO_POR_TIPO:
        raise ValueError(f"Tipo de incapacidad desconocido: {tipo}")

    info = SUBSIDIO_POR_TIPO[tipo]
    dias_totales = (fecha_fin - fecha_inicio).days + 1
    dias_espera = info["espera_dias"]
    pct = info["pct"]

    # Base del subsidio: SDI topado a 25 UMAs (si viene el topado lo usamos)
    base = sdi_topado if sdi_topado else sdi

    dias_imss = max(0, dias_totales - dias_espera)
    subsidio_diario = round(base * pct, 2)
    subsidio_total = round(subsidio_diario * dias_imss, 2)

    alertas = []
    if dias_totales > 52 * 7:  # Más de 52 semanas → posible dictamen de invalidez
        alertas.append("Incapacidad supera 52 semanas — revisar dictamen de invalidez (Art. 119 LSS)")
    if tipo == "01" and dias_totales > 26 * 7:
        alertas.append("EG > 26 semanas: IMSS puede ampliar hasta 52 semanas")
    if tipo in ("03", "04"):
        alertas.append("Incapacidad RT/EP: notificar accidente/enfermedad al IMSS (ST-1 o ST-2)")

    return DetalleSubsidio(
        folio=folio,
        tipo=tipo,
        nombre_tipo=info["nombre"],
        nss=nss,
        nombre_trabajador=nombre,
        sdi_trabajador=sdi,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        dias_totales=dias_totales,
        dias_pagan_patron=min(dias_espera, dias_totales),
        dias_pagan_imss=dias_imss,
        pct_subsidio=pct,
        subsidio_diario_imss=subsidio_diario,
        subsidio_total_imss=subsidio_total,
        impacto_prima_riesgo=tipo in ("03", "04"),
        alertas=alertas,
    )


def analizar_incapacidades(lista: list[dict]) -> dict:
    """
    Analiza una lista de incapacidades y regresa resumen estadístico.
    Cada elemento del dict debe tener: tipo, sdi, fecha_inicio, fecha_fin, nss, nombre, folio.
    """
    detalles = []
    total_dias_eg = 0
    total_dias_rt = 0
    total_subsidio = 0.0
    alertas_globales = []

    for inc in lista:
        try:
            d = calcular_subsidio(
                tipo=inc.get("tipo", "01"),
                sdi=inc.get("sdi", 0),
                fecha_inicio=inc["fecha_inicio"],
                fecha_fin=inc["fecha_fin"],
                folio=inc.get("folio", ""),
                nss=inc.get("nss", ""),
                nombre=inc.get("nombre", ""),
                sdi_topado=inc.get("sdi_topado"),
            )
            detalles.append(d)
            total_subsidio += d.subsidio_total_imss
            if d.tipo == "01":
                total_dias_eg += d.dias_pagan_imss
            elif d.tipo in ("03", "04"):
                total_dias_rt += d.dias_pagan_imss
        except Exception as e:
            alertas_globales.append(f"Error en folio {inc.get('folio', '?')}: {e}")

    # Trabajadores con más de 3 incapacidades en el año → revisar
    nss_count: dict[str, int] = {}
    for d in detalles:
        nss_count[d.nss] = nss_count.get(d.nss, 0) + 1
    for nss, cnt in nss_count.items():
        if cnt >= 3:
            alertas_globales.append(
                f"NSS {nss}: {cnt} incapacidades en el período — revisar reincidencia"
            )

    return {
        "total_incapacidades": len(detalles),
        "total_dias_eg": total_dias_eg,
        "total_dias_rt_ep": total_dias_rt,
        "total_subsidio_imss": round(total_subsidio, 2),
        "incapacidades_rt_ep": sum(1 for d in detalles if d.impacto_prima_riesgo),
        "alertas": alertas_globales,
        "detalles": detalles,
    }


def dias_rt_para_prima(detalles: list[DetalleSubsidio]) -> float:
    """Suma días de RT/EP subsidiados para el cálculo de prima de riesgo."""
    return sum(d.dias_pagan_imss for d in detalles if d.tipo in ("03", "04"))


# ── Impacto en Prima de Riesgo ────────────────────────────────────────────────

def calcular_impacto_prima(
    tipo_incapacidad: str,
    dias_subsidiados_nuevos: int,
    trabajadores_promedio: float,
    prima_actual_pct: float,
    clase: int,
    masa_salarial_anual: float,
    dias_subsidiados_acumulados: int = 0,
    dias_incap_permanente: float = 0.0,
    defunciones: int = 0,
) -> dict:
    """
    Calcula si una incapacidad afecta la Prima de Riesgo y cuánto dinero representa.

    Retorna un dict con:
    - afecta_prima: bool
    - explicacion: texto en lenguaje de negocio
    - prima_actual_pct: prima vigente
    - prima_nueva_pct: prima proyectada
    - diferencia_pct: cambio
    - costo_anual_extra: pesos adicionales por año
    - semaforo: "verde" | "amarillo" | "rojo"
    - recomendaciones: lista de acciones concretas
    """
    from modules.prima_riesgo import calcular_prima_riesgo, CLASES_RIESGO
    NO_AFECTA = tipo_incapacidad not in ("03", "04")

    if NO_AFECTA:
        tipo_nombre = {
            "01": "Enfermedad General",
            "02": "Maternidad",
        }.get(tipo_incapacidad, "desconocido")

        return {
            "afecta_prima": False,
            "semaforo": "verde",
            "explicacion": (
                f"✅ Esta incapacidad por **{tipo_nombre}** "
                f"**NO afecta tu Prima de Riesgo de Trabajo.**\n\n"
                f"Solo las incapacidades por **Accidente de Trabajo** o "
                f"**Enfermedad Profesional** entran al cálculo de la prima anual. "
                f"Las enfermedades generales y maternidad son riesgo compartido con "
                f"el IMSS y no penalizan a tu empresa."
            ),
            "prima_actual_pct": prima_actual_pct,
            "prima_nueva_pct": prima_actual_pct,
            "diferencia_pct": 0.0,
            "costo_anual_extra": 0.0,
            "recomendaciones": [
                "No se requiere ninguna acción relacionada con la prima de riesgo.",
                "Lleva el control de estas incapacidades para el SIPARE bimestral.",
            ],
        }

    # Es RT o EP — calcula impacto
    tipo_nombre = "Riesgo de Trabajo" if tipo_incapacidad == "03" else "Enfermedad Profesional"
    dias_total = dias_subsidiados_acumulados + dias_subsidiados_nuevos

    # Prima SIN esta incapacidad
    r_sin = calcular_prima_riesgo(
        clase=clase,
        trabajadores_promedio=trabajadores_promedio,
        dias_subsidiados=float(dias_subsidiados_acumulados),
        dias_incap_permanente=dias_incap_permanente,
        defunciones=defunciones,
        prima_anterior=prima_actual_pct / 100,
    )

    # Prima CON esta incapacidad
    r_con = calcular_prima_riesgo(
        clase=clase,
        trabajadores_promedio=trabajadores_promedio,
        dias_subsidiados=float(dias_total),
        dias_incap_permanente=dias_incap_permanente,
        defunciones=defunciones,
        prima_anterior=prima_actual_pct / 100,
    )

    prima_sin = r_sin["prima_final_pct"]
    prima_con = r_con["prima_final_pct"]

    # Garantizar cap ±1 punto porcentual respecto a prima ACTUAL del usuario (Art. 74 LSS)
    prima_con = min(prima_con, prima_actual_pct + 1.0)
    prima_con = max(prima_con, prima_actual_pct - 1.0)
    clase_info_local = CLASES_RIESGO[clase]
    prima_con = max(clase_info_local["prima_min"], min(prima_con, clase_info_local["prima_max"]))

    diferencia = round(prima_con - prima_sin, 5)
    costo_extra = round((diferencia / 100) * masa_salarial_anual, 2)

    # Semáforo
    if diferencia <= 0:
        semaforo = "verde"
    elif diferencia < 0.5:
        semaforo = "amarillo"
    else:
        semaforo = "rojo"

    # Explicación en lenguaje de negocio
    clase_nombre = CLASES_RIESGO[clase]["nombre"]

    if diferencia <= 0:
        explicacion = (
            f"⚠️ Esta incapacidad es por **{tipo_nombre}** — SÍ entra al cálculo de tu prima.\n\n"
            f"**Buenas noticias:** Con {dias_subsidiados_nuevos} días adicionales, "
            f"tu prima de riesgo **se mantiene en {prima_sin:.3f}%** porque ya estás "
            f"en el límite mínimo de tu clase ({clase_nombre}) "
            f"o la variación permitida por ley (±1% anual) te protege.\n\n"
            f"Registra correctamente el accidente con el formato ST-7 del IMSS "
            f"para que quede documentado."
        )
    else:
        explicacion = (
            f"🔴 Esta incapacidad es por **{tipo_nombre}** — **SÍ afecta tu Prima de Riesgo.**\n\n"
            f"**¿Qué significa esto para tu negocio?**\n\n"
            f"Tu prima actual es **{prima_sin:.3f}%**. "
            f"Con esta incapacidad de {dias_subsidiados_nuevos} días, "
            f"tu prima del próximo ejercicio podría subir a **{prima_con:.3f}%**.\n\n"
            f"En dinero: si tu masa salarial anual es de "
            f"**${masa_salarial_anual:,.2f}**, "
            f"pagarías **${costo_extra:,.2f} pesos más al año** en cuotas IMSS.\n\n"
            f"La ley limita el aumento a máximo **1% por año**, así que no puede "
            f"subir más de eso de un ejercicio a otro."
        )

    # Recomendaciones concretas
    recomendaciones = [
        "Presenta el aviso de accidente de trabajo al IMSS (formato ST-7) dentro de los 3 días siguientes al accidente.",
        "Investiga la causa del accidente y documenta las medidas preventivas tomadas — esto te puede ayudar a reducir la prima en el siguiente ejercicio.",
        "Revisa tu programa de seguridad e higiene con tu médico o enfermera de empresa.",
    ]
    if dias_subsidiados_nuevos >= 30:
        recomendaciones.append(
            "Con más de 30 días de incapacidad por RT considera contratar un asesor en "
            "seguridad industrial — reducir accidentes baja la prima a largo plazo."
        )
    if diferencia > 0:
        recomendaciones.append(
            f"En febrero del próximo año declara tu prima correctamente en el SUA. "
            f"Si no tuviste más accidentes el resto del año, el impacto real puede ser menor."
        )

    return {
        "afecta_prima": True,
        "semaforo": semaforo,
        "explicacion": explicacion,
        "prima_actual_pct": prima_sin,
        "prima_nueva_pct": prima_con,
        "diferencia_pct": diferencia,
        "costo_anual_extra": costo_extra,
        "dias_rt_acumulados": dias_total,
        "recomendaciones": recomendaciones,
    }
