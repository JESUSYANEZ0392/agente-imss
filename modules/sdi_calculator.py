"""
Cálculo de Salario Diario Integrado (SDI) conforme a:
- Art. 27 LSS: conceptos integrantes
- Art. 76 LFT (reforma 2023): tabla de vacaciones
- Art. 87 LFT: aguinaldo mínimo 15 días
- Art. 80 LFT: prima vacacional mínima 25%
"""
from dataclasses import dataclass, field
from typing import Optional


# Tabla de vacaciones LFT 2023 (reforma DOF 27-dic-2022)
_TABLA_VAC = {
    1: 12, 2: 14, 3: 16, 4: 18,
    5: 20, 6: 20, 7: 20, 8: 20, 9: 20,
    10: 22, 11: 22, 12: 22, 13: 22, 14: 22,
    15: 24, 16: 24, 17: 24, 18: 24, 19: 24,
    20: 26, 21: 26, 22: 26, 23: 26, 24: 26,
    25: 28, 26: 28, 27: 28, 28: 28, 29: 28,
}


def dias_vacaciones_lft(anios_servicio: int) -> int:
    """Devuelve días de vacaciones conforme a tabla LFT 2023."""
    if anios_servicio <= 0:
        return 12
    if anios_servicio >= 30:
        return 30
    return _TABLA_VAC.get(anios_servicio, 30)


@dataclass
class Prestaciones:
    """Define las prestaciones del trabajador para calcular SDI."""
    salario_diario: float

    # Antigüedad
    anios_servicio: int = 1

    # Prestaciones de ley (mínimos LFT)
    dias_aguinaldo: float = 15.0          # Art. 87 LFT mínimo 15 días
    prima_vacacional_pct: float = 0.25    # Art. 80 LFT mínimo 25%

    # Prestaciones adicionales (si son superiores a ley, indicar aquí)
    vale_despensa_diario: float = 0.0     # Solo parte exenta IMSS (hasta 40% UMA)
    fondo_ahorro_pct: float = 0.0         # Solo si no supera 13% del SD se excluye
    bono_productividad_diario: float = 0.0
    otros_conceptos_diarios: float = 0.0

    # Tipo de prestaciones
    tipo: str = "ley"                     # "ley" o "superiores"

    # UMA vigente (actualizar cada año)
    uma_diaria: float = 108.57            # UMA 2024
    limite_veces_uma: float = 25.0        # Tope IMSS = 25 UMAs


def calcular_sdi(p: Prestaciones) -> dict:
    """
    Calcula el SDI y regresa un dict con el desglose completo.

    SDI = SD + Σ(partes proporcionales de prestaciones / 365)

    Las prestaciones que integran son: aguinaldo, prima vacacional,
    vales de despensa (parte gravable), fondo de ahorro (parte gravable),
    y demás conceptos en efectivo ordinarios y permanentes.
    """
    sd = p.salario_diario
    anios = max(1, p.anios_servicio)

    dias_vac = dias_vacaciones_lft(anios)

    # Partes proporcionales diarias
    aguinaldo_pp = (p.dias_aguinaldo * sd) / 365
    prima_vac_pp = (dias_vac * sd * p.prima_vacacional_pct) / 365

    # Vales de despensa: solo integran la parte que excede el 40% de la UMA diaria
    # Si el vale es ≤ 40% UMA → no integra. Si excede → integra el excedente.
    limite_vales = p.uma_diaria * 0.40
    vales_integrables = max(0.0, p.vale_despensa_diario - limite_vales)

    # Fondo de ahorro: si la aportación patronal no excede 13% del SD → no integra
    limite_fa = sd * 0.13
    fa_diario = (sd * p.fondo_ahorro_pct / 100)
    fa_integrable = max(0.0, fa_diario - limite_fa)

    otros = p.bono_productividad_diario + p.otros_conceptos_diarios

    total_pp = aguinaldo_pp + prima_vac_pp + vales_integrables + fa_integrable + otros
    sdi = sd + total_pp
    fi = round(sdi / sd, 6) if sd > 0 else 1.0

    # Tope IMSS: 25 UMAs diarias
    tope = p.uma_diaria * p.limite_veces_uma
    sdi_topado = min(sdi, tope)

    return {
        "salario_diario_base": round(sd, 2),
        "anios_servicio": anios,
        "dias_vacaciones": dias_vac,
        "dias_aguinaldo": p.dias_aguinaldo,
        "prima_vacacional_pct": p.prima_vacacional_pct,
        # Partes proporcionales
        "aguinaldo_pp": round(aguinaldo_pp, 6),
        "prima_vacacional_pp": round(prima_vac_pp, 6),
        "vales_integrables_pp": round(vales_integrables, 6),
        "fondo_ahorro_integrable_pp": round(fa_integrable, 6),
        "otros_pp": round(otros, 6),
        "total_partes_proporcionales": round(total_pp, 6),
        # Resultado
        "factor_integracion": fi,
        "sdi": round(sdi, 2),
        "uma_diaria": p.uma_diaria,
        "tope_25_umas": round(tope, 2),
        "sdi_topado_imss": round(sdi_topado, 2),
        "tipo_prestaciones": p.tipo,
    }


def calcular_sdi_batch(trabajadores: list[dict]) -> list[dict]:
    """
    Calcula SDI para una lista de trabajadores.
    Cada elemento debe tener al menos: nombre, nss, salario_diario, anios_servicio.
    """
    resultados = []
    for t in trabajadores:
        p = Prestaciones(
            salario_diario=t.get("salario_diario", 0),
            anios_servicio=t.get("anios_servicio", 1),
            dias_aguinaldo=t.get("dias_aguinaldo", 15),
            prima_vacacional_pct=t.get("prima_vacacional_pct", 0.25),
            vale_despensa_diario=t.get("vale_despensa_diario", 0),
            fondo_ahorro_pct=t.get("fondo_ahorro_pct", 0),
            bono_productividad_diario=t.get("bono_productividad_diario", 0),
            otros_conceptos_diarios=t.get("otros_conceptos_diarios", 0),
            tipo=t.get("tipo_prestaciones", "ley"),
            uma_diaria=t.get("uma_diaria", 108.57),
        )
        resultado = calcular_sdi(p)
        resultado["nss"] = t.get("nss", "")
        resultado["nombre"] = t.get("nombre", "")
        resultados.append(resultado)
    return resultados
