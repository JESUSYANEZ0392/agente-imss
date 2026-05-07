"""
Cálculo de Prima de Riesgo de Trabajo (PRT)
Art. 74 LSS — Se presenta en febrero de cada año.
Período: 1 oct (año anterior) al 30 sep (año en curso).
"""

# Primas medias, mínimas y máximas por clase de riesgo (Art. 73 LSS Tabla)
CLASES_RIESGO = {
    1: {"nombre": "Clase I",   "prima_media": 0.54355, "prima_min": 0.50000, "prima_max": 1.50000},
    2: {"nombre": "Clase II",  "prima_media": 1.13065, "prima_min": 1.00000, "prima_max": 2.59000},
    3: {"nombre": "Clase III", "prima_media": 2.59840, "prima_min": 2.00000, "prima_max": 4.65000},
    4: {"nombre": "Clase IV",  "prima_media": 4.65325, "prima_min": 4.00000, "prima_max": 7.58000},
    5: {"nombre": "Clase V",   "prima_media": 7.58875, "prima_min": 7.00000, "prima_max": 10.00000},
}

# Constantes de la fórmula Art. 74 LSS
F = 2.9          # Factor de prima
N = 365          # Días del período


def calcular_prima_riesgo(
    clase: int,
    trabajadores_promedio: float,
    dias_subsidiados: float = 0.0,
    dias_incap_permanente: float = 0.0,
    defunciones: int = 0,
    prima_anterior: float | None = None,
) -> dict:
    """
    Fórmula LSS Art. 74:
    Prima = ((S/365) + V*M) * (1 + H) * 100 / N + mínima de clase

    Simplificada a la fórmula oficial:
    Prima = (Σ(dias_subsidiados) / (trabajadores_promedio * N) + V * M) * F + prima_min

    Donde:
      V = (días_incapacidad_permanente + 1460*defunciones) / trabajadores_promedio
      M = 28 (constante)
      S = días subsidiados
    """
    if clase not in CLASES_RIESGO:
        raise ValueError(f"Clase de riesgo inválida: {clase}. Debe ser 1-5.")

    clase_info = CLASES_RIESGO[clase]
    pm = clase_info["prima_media"] / 100
    pmin = clase_info["prima_min"] / 100
    pmax = clase_info["prima_max"] / 100

    n = trabajadores_promedio
    if n <= 0:
        raise ValueError("Trabajadores promedio debe ser mayor a 0.")

    # Siniestralidad
    s = dias_subsidiados
    v = (dias_incap_permanente + 1460 * defunciones) / n
    m = 28  # Constante LSS

    # Fórmula Art. 74
    prima_calculada = ((s / (n * N)) + (v * m / N)) * F + pmin

    # Limitar entre min y max de la clase
    prima_final = max(pmin, min(prima_calculada, pmax))

    # Variación vs prima anterior — Art. 74 LSS: máximo ±1 punto porcentual
    # Las primas están en decimal (0.01 = 1 punto porcentual)
    if prima_anterior is not None:
        limite_sup = prima_anterior + 0.01   # Máximo sube 1 punto porcentual
        limite_inf = prima_anterior - 0.01   # Máximo baja 1 punto porcentual
        prima_final = max(limite_inf, min(prima_final, limite_sup))
        prima_final = max(pmin, min(prima_final, pmax))
        variacion = prima_final - prima_anterior
    else:
        variacion = None

    return {
        "clase": clase,
        "nombre_clase": clase_info["nombre"],
        "trabajadores_promedio": round(n, 4),
        "dias_subsidiados": dias_subsidiados,
        "dias_incap_permanente": dias_incap_permanente,
        "defunciones": defunciones,
        "prima_media_clase_pct": clase_info["prima_media"],
        "prima_minima_pct": clase_info["prima_min"],
        "prima_maxima_pct": clase_info["prima_max"],
        "prima_calculada_pct": round(prima_calculada * 100, 5),
        "prima_final_pct": round(prima_final * 100, 5),
        "prima_anterior_pct": round(prima_anterior * 100, 5) if prima_anterior else None,
        "variacion_pct": round(variacion * 100, 5) if variacion is not None else None,
        "nota_variacion": "Limitada a ±1% respecto a prima anterior" if variacion is not None and abs(variacion) >= 0.01 else None,
    }


def trabajadores_promedio(altas_bajas_por_mes: list[dict]) -> float:
    """
    Calcula trabajadores promedio del período (oct–sep).
    Cada elemento: {"mes": int, "trabajadores_activos": int}
    """
    if not altas_bajas_por_mes:
        return 0.0
    total = sum(m["trabajadores_activos"] for m in altas_bajas_por_mes)
    return total / len(altas_bajas_por_mes)
