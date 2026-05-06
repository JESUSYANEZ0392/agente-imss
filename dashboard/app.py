"""
Dashboard IMSS — Agente Inteligente de Seguridad Social
Ejecutar con: streamlit run dashboard/app.py
"""
import os
import sys
import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Asegurar que el directorio raíz está en el path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import init_db, get_session
from database.models import Patron, Trabajador, RegistroSalario, PagoSIPARE, Incapacidad
from modules.sdi_calculator import Prestaciones, calcular_sdi, calcular_sdi_batch, dias_vacaciones_lft
from modules.sua_parser import parse_sua, sua_a_dict
from modules.prima_riesgo import calcular_prima_riesgo, CLASES_RIESGO
from modules.incapacidades import calcular_subsidio, analizar_incapacidades
from modules.comparador import (
    comparar_sipare, comparar_plantilla, tendencia_cuotas,
    tendencia_incapacidades, alerta_pagos_vencidos
)
from reports.exporter import (
    exportar_sdi_excel, exportar_comparativo_excel, exportar_incapacidades_excel
)

# ── Configuración página ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="Agente IMSS",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS personalizado
st.markdown("""
<style>
.metric-card {
    background: #f0f2f6; border-radius: 10px;
    padding: 15px; margin: 5px 0;
}
.alerta-roja { background-color: #ffcccc; border-left: 4px solid red; padding: 8px; border-radius: 4px; }
.alerta-amarilla { background-color: #fff3cd; border-left: 4px solid orange; padding: 8px; border-radius: 4px; }
.alerta-verde { background-color: #d4edda; border-left: 4px solid green; padding: 8px; border-radius: 4px; }
</style>
""", unsafe_allow_html=True)

# ── Inicializar BD ───────────────────────────────────────────────────────────
init_db()

# ── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/thumb/9/90/IMSS_logo.svg/200px-IMSS_logo.svg.png",
                 width=120)
st.sidebar.title("Agente IMSS")

menu = st.sidebar.radio("Módulo", [
    "🏠 Dashboard",
    "📁 Cargar SUA",
    "💰 Calcular SDI",
    "🌐 IDSE / SIPARE",
    "🏥 Incapacidades",
    "⚠️ Prima de Riesgo",
    "📊 Comparativos",
    "🏢 Patrones",
])

# Selector de patrón activo
with get_session() as s:
    patrones = s.query(Patron).filter_by(activo=True).all()
    patron_opts = {f"{p.registro_patronal} — {p.razon_social}": p.id for p in patrones}

patron_sel_label = st.sidebar.selectbox("Patrón activo", list(patron_opts.keys()) if patron_opts else ["Sin patrones"])
patron_id_activo = patron_opts.get(patron_sel_label)


# ═══════════════════════════════════════════════════════════════════════════
# 🏠 DASHBOARD PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════
if menu == "🏠 Dashboard":
    st.title("🏛️ Agente Inteligente IMSS")
    st.caption(f"Fecha: {date.today().strftime('%d/%m/%Y')}")

    if not patrones:
        st.warning("No hay patrones registrados. Ve a **Patrones** para agregar uno.")
        st.stop()

    with get_session() as s:
        # Alertas de pagos vencidos/próximos
        alertas_pago = alerta_pagos_vencidos(s)

    if alertas_pago:
        st.error(f"⚠️ {len(alertas_pago)} pago(s) SIPARE vencido(s) o próximos a vencer")
        with st.expander("Ver alertas de pago"):
            for a in alertas_pago:
                color = "alerta-roja" if a["vencido"] else "alerta-amarilla"
                st.markdown(
                    f'<div class="{color}"><b>{a["patron"]}</b> | {a["periodo"]} | '
                    f'${a["monto"]:,.2f} | Límite: {a["fecha_limite"]} | '
                    f'{"⛔ VENCIDO" if a["vencido"] else f"📅 {a["dias_restantes"]} días"}</div>',
                    unsafe_allow_html=True
                )

    # Métricas generales
    with get_session() as s:
        total_trajs = s.query(Trabajador).filter_by(patron_id=patron_id_activo, activo=True).count()
        total_incs = s.query(Incapacidad).join(Trabajador).filter(
            Trabajador.patron_id == patron_id_activo
        ).count()
        pagos = s.query(PagoSIPARE).filter_by(patron_id=patron_id_activo).order_by(
            PagoSIPARE.anio.desc(), PagoSIPARE.bimestre.desc()
        ).first()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Trabajadores activos", total_trajs)
    col2.metric("Incapacidades registradas", total_incs)
    col3.metric("Último pago SIPARE", f"${pagos.monto_total:,.2f}" if pagos else "—")
    col4.metric("Estado último bimestre", pagos.estado.upper() if pagos else "—")

    # Gráfica tendencia cuotas
    with get_session() as s:
        hist = tendencia_cuotas(s, patron_id_activo)
    if hist:
        df_hist = pd.DataFrame(hist)
        df_hist["etiqueta"] = df_hist["periodo_label"].fillna(
            df_hist["anio"].astype(str) + " B" + df_hist["bimestre"].astype(str)
        )
        fig = px.bar(df_hist, x="etiqueta", y="monto_total",
                     title="Cuotas SIPARE por Bimestre",
                     color="estado",
                     color_discrete_map={"pagado": "#2ecc71", "pendiente": "#f39c12", "vencido": "#e74c3c"})
        st.plotly_chart(fig, use_container_width=True)

    # Tendencia incapacidades
    with get_session() as s:
        tend_inc = tendencia_incapacidades(s, patron_id_activo)
    if tend_inc:
        df_inc = pd.DataFrame(tend_inc)
        fig2 = px.line(df_inc, x="mes", y="total_dias", color="tipo",
                       title="Días de Incapacidad por Mes y Tipo",
                       markers=True)
        st.plotly_chart(fig2, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# 📁 CARGAR SUA
# ═══════════════════════════════════════════════════════════════════════════
elif menu == "📁 Cargar SUA":
    st.title("📁 Cargar Archivo SUA")
    st.info("Carga el archivo `.SUA` exportado desde el software SUA del IMSS.")

    archivo = st.file_uploader("Seleccionar archivo .SUA", type=["sua", "SUA", "txt"])

    if archivo:
        # Guardar temporalmente
        tmp_path = os.path.join("uploads", archivo.name)
        with open(tmp_path, "wb") as f:
            f.write(archivo.read())

        with st.spinner("Procesando archivo SUA..."):
            resultado = parse_sua(tmp_path)

        if resultado.errores:
            st.warning(f"⚠️ {len(resultado.errores)} advertencias al parsear:")
            for e in resultado.errores[:10]:
                st.caption(e)

        if resultado.patron:
            st.success(f"✅ Patrón: {resultado.patron.razon_social} | RP: {resultado.patron.registro_patronal}")

        st.metric("Trabajadores encontrados", len(resultado.trabajadores))

        if resultado.trabajadores:
            df = pd.DataFrame(sua_a_dict(resultado))
            st.dataframe(df, use_container_width=True)

            if resultado.cuotas:
                st.divider()
                st.subheader("Cuotas del bimestre")
                col1, col2, col3 = st.columns(3)
                col1.metric("Masa Salarial", f"${resultado.cuotas.masa_salarial:,.2f}")
                col2.metric("Total Cuotas IMSS", f"${resultado.cuotas.cuotas_imss:,.2f}")
                col3.metric("Total Cuotas INFONAVIT", f"${resultado.cuotas.cuotas_infonavit:,.2f}")
                col4, col5 = st.columns(2)
                col4.metric("TOTAL A PAGAR", f"${resultado.cuotas.total_pagar:,.2f}")
                if resultado.cuotas.fecha_limite_pago:
                    col5.metric("Fecha límite de pago", resultado.cuotas.fecha_limite_pago)
                with st.expander("Desglose por ramo (aportación patronal)"):
                    st.table({
                        "Ramo": ["EyM (cuota fija)", "Riesgo de Trabajo", "Invalidez y Vida",
                                 "Guarderías", "Cesantía y Vejez", "Retiro"],
                        "Monto ($)": [
                            f"${resultado.cuotas.emym_patronal:,.2f}",
                            f"${resultado.cuotas.riesgo_trabajo:,.2f}",
                            f"${resultado.cuotas.invalidez_vida:,.2f}",
                            f"${resultado.cuotas.guarderias:,.2f}",
                            f"${resultado.cuotas.cesantia_vejez:,.2f}",
                            f"${resultado.cuotas.retiro:,.2f}",
                        ],
                    })

            # Botón guardar en BD
            periodo = st.text_input("Período (ej: 2024-B3)", placeholder="2024-B3")
            if st.button("💾 Guardar en base de datos") and periodo and patron_id_activo:
                from database.models import ArchivoSUA as ModelArchivoSUA, RegistroSalario as ModelSalario
                with get_session() as s:
                    # Registrar archivo
                    arch = ModelArchivoSUA(
                        patron_id=patron_id_activo,
                        nombre_archivo=archivo.name,
                        periodo=periodo,
                        registros_trabajadores=len(resultado.trabajadores),
                        total_cuotas_imss=resultado.cuotas.cuotas_imss if resultado.cuotas else 0,
                        total_cuotas_infonavit=resultado.cuotas.cuotas_infonavit if resultado.cuotas else 0,
                        hash_archivo=resultado.hash_archivo,
                        ruta_archivo=tmp_path,
                        procesado=True,
                    )
                    s.add(arch)

                    # Upsert trabajadores y salarios
                    for t in resultado.trabajadores:
                        trab = s.query(Trabajador).filter_by(
                            patron_id=patron_id_activo, nss=t.nss
                        ).first()
                        if not trab:
                            trab = Trabajador(
                                patron_id=patron_id_activo,
                                nss=t.nss, rfc=t.rfc, curp=t.curp,
                                nombre=t.nombre,
                                tipo_trabajador=t.tipo_trabajador,
                                fecha_baja=t.fecha_baja,
                                activo=t.fecha_baja is None,
                            )
                            s.add(trab)
                            s.flush()

                        sal = RegistroSalario(
                            trabajador_id=trab.id,
                            fecha_registro=date.today(),
                            periodo=periodo,
                            salario_diario_base=t.salario_diario,
                            salario_diario_integrado=t.salario_diario,
                        )
                        s.add(sal)

                st.success("✅ Datos guardados correctamente en la base de datos.")

            # Exportar Excel
            if st.button("📥 Exportar a Excel"):
                ruta = exportar_sdi_excel(
                    sua_a_dict(resultado),
                    patron=resultado.patron.razon_social if resultado.patron else "",
                    periodo=resultado.patron.periodo if resultado.patron else "",
                )
                with open(ruta, "rb") as f:
                    st.download_button("Descargar Excel", f, file_name=os.path.basename(ruta))


# ═══════════════════════════════════════════════════════════════════════════
# 💰 CALCULAR SDI
# ═══════════════════════════════════════════════════════════════════════════
elif menu == "💰 Calcular SDI":
    st.title("💰 Calculadora de Salario Diario Integrado")

    tab1, tab2 = st.tabs(["Individual", "Por lote (Excel/CSV)"])

    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            sd = st.number_input("Salario Diario Base ($)", min_value=0.0, value=500.0, step=10.0)
            anios = st.number_input("Años de Servicio", min_value=0, max_value=50, value=1)
            uma = st.number_input("UMA diaria vigente ($)", value=108.57, step=0.01)
        with col2:
            tipo = st.radio("Tipo de prestaciones", ["ley", "superiores"])
            dias_ag = st.number_input("Días de aguinaldo", min_value=15, value=15, step=1)
            pct_pv = st.slider("Prima vacacional %", min_value=25, max_value=100, value=25) / 100

        st.subheader("Prestaciones adicionales")
        col3, col4 = st.columns(2)
        with col3:
            vales = st.number_input("Vale despensa diario ($)", min_value=0.0, value=0.0)
            fa_pct = st.number_input("Fondo de ahorro % sobre SD", min_value=0.0, max_value=25.0, value=0.0)
        with col4:
            bono = st.number_input("Bono/Productividad diario ($)", min_value=0.0, value=0.0)
            otros = st.number_input("Otros conceptos diarios ($)", min_value=0.0, value=0.0)

        if st.button("Calcular SDI", type="primary"):
            p = Prestaciones(
                salario_diario=sd, anios_servicio=anios,
                dias_aguinaldo=dias_ag, prima_vacacional_pct=pct_pv,
                vale_despensa_diario=vales, fondo_ahorro_pct=fa_pct,
                bono_productividad_diario=bono, otros_conceptos_diarios=otros,
                tipo=tipo, uma_diaria=uma,
            )
            r = calcular_sdi(p)

            st.divider()
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Salario Diario Base", f"${r['salario_diario_base']:,.2f}")
            col_b.metric("Factor de Integración", f"{r['factor_integracion']:.4f}")
            col_c.metric("SDI", f"${r['sdi']:,.2f}",
                         delta=f"${r['sdi'] - r['salario_diario_base']:,.2f}")

            col_d, col_e = st.columns(2)
            col_d.metric("Días de Vacaciones (LFT 2023)", r["dias_vacaciones"])
            col_e.metric("SDI Topado IMSS (25 UMAs)", f"${r['sdi_topado_imss']:,.2f}",
                         delta="Igual" if r["sdi"] <= r["tope_25_umas"] else "⚠️ Topado")

            with st.expander("Desglose partes proporcionales"):
                df_desglose = pd.DataFrame([
                    {"Concepto": "Aguinaldo pp", "Monto diario": r["aguinaldo_pp"]},
                    {"Concepto": "Prima vacacional pp", "Monto diario": r["prima_vacacional_pp"]},
                    {"Concepto": "Vales despensa integrables", "Monto diario": r["vales_integrables_pp"]},
                    {"Concepto": "Fondo ahorro integrable", "Monto diario": r["fondo_ahorro_integrable_pp"]},
                    {"Concepto": "Otros conceptos", "Monto diario": r["otros_pp"]},
                    {"Concepto": "TOTAL PARTES PROPORCIONALES", "Monto diario": r["total_partes_proporcionales"]},
                ])
                st.dataframe(df_desglose, use_container_width=True)

    with tab2:
        st.info("Sube un Excel/CSV con columnas: nombre, nss, salario_diario, anios_servicio. "
                "Columnas opcionales: dias_aguinaldo, prima_vacacional_pct, "
                "vale_despensa_diario, fondo_ahorro_pct.")
        archivo_batch = st.file_uploader("Seleccionar archivo", type=["xlsx", "csv"])
        uma_batch = st.number_input("UMA diaria ($)", value=108.57, key="uma_batch")

        if archivo_batch:
            if archivo_batch.name.endswith(".csv"):
                df_in = pd.read_csv(archivo_batch)
            else:
                df_in = pd.read_excel(archivo_batch)

            st.dataframe(df_in.head(), use_container_width=True)

            if st.button("Calcular SDI por lote", type="primary"):
                registros = df_in.to_dict(orient="records")
                for r in registros:
                    r["uma_diaria"] = uma_batch

                from modules.sdi_calculator import calcular_sdi_batch
                resultados = calcular_sdi_batch(registros)
                df_out = pd.DataFrame(resultados)
                st.dataframe(df_out, use_container_width=True)

                # Exportar
                ruta = exportar_sdi_excel(resultados, periodo=str(date.today()))
                with open(ruta, "rb") as f:
                    st.download_button("📥 Descargar Excel", f, file_name=os.path.basename(ruta))


# ═══════════════════════════════════════════════════════════════════════════
# 🌐 IDSE / SIPARE
# ═══════════════════════════════════════════════════════════════════════════
elif menu == "🌐 IDSE / SIPARE":
    st.title("🌐 IDSE y SIPARE")

    with get_session() as s:
        _p = s.query(Patron).filter_by(id=patron_id_activo).first() if patron_id_activo else None
        patron_dict = {
            "registro_patronal": _p.registro_patronal,
            "usuario_idse": _p.usuario_idse or "",
            "certificado_path": _p.certificado_path or "",
        } if _p else None

    if not patron_dict:
        st.warning("Selecciona un patrón con credenciales configuradas.")
        st.stop()

    tab_idse, tab_sipare = st.tabs(["IDSE — Movimientos", "SIPARE — Pagos"])

    with tab_idse:
        st.subheader("Consultar Movimientos Afiliatorios (IDSE)")
        col1, col2 = st.columns(2)
        f_ini = col1.date_input("Fecha inicio", value=date.today().replace(day=1))
        f_fin = col2.date_input("Fecha fin", value=date.today())

        password_idse = st.text_input("Contraseña IDSE", type="password",
                                      help="No se almacena en la base de datos")
        cert_path = st.text_input("Ruta certificado .cer",
                                  value=patron_dict["certificado_path"])

        col_mov, col_inc = st.columns(2)

        if col_mov.button("🔍 Consultar Movimientos"):
            if not password_idse:
                st.error("Ingresa la contraseña IDSE")
            else:
                from modules.idse_scraper import consultar_movimientos_sync
                with st.spinner("Conectando con IDSE..."):
                    try:
                        movs = consultar_movimientos_sync(
                            patron_dict["registro_patronal"], patron_dict["usuario_idse"],
                            password_idse, cert_path, f_ini, f_fin
                        )
                        if movs:
                            st.dataframe(pd.DataFrame(movs), use_container_width=True)
                        else:
                            st.info("Sin movimientos en el período seleccionado.")
                    except Exception as e:
                        st.error(f"Error: {e}")

        if col_inc.button("🏥 Consultar Incapacidades"):
            if not password_idse:
                st.error("Ingresa la contraseña IDSE")
            else:
                from modules.idse_scraper import consultar_incapacidades_sync
                with st.spinner("Consultando incapacidades..."):
                    try:
                        incs = consultar_incapacidades_sync(
                            patron_dict["registro_patronal"], patron_dict["usuario_idse"],
                            password_idse, cert_path, f_ini, f_fin
                        )
                        if incs:
                            st.dataframe(pd.DataFrame(incs), use_container_width=True)
                        else:
                            st.info("Sin incapacidades en el período.")
                    except Exception as e:
                        st.error(f"Error: {e}")

    with tab_sipare:
        st.subheader("SIPARE — Líneas de Captura y Pagos")
        col1, col2 = st.columns(2)
        anio_sel = col1.selectbox("Año", list(range(date.today().year, 2019, -1)))
        bim_sel = col2.selectbox("Bimestre", [1, 2, 3, 4, 5, 6],
                                 format_func=lambda b: f"B{b} — {['Ene-Feb','Mar-Abr','May-Jun','Jul-Ago','Sep-Oct','Nov-Dic'][b-1]}")

        password_sipare = st.text_input("Contraseña SIPARE", type="password", key="pw_sipare")

        col_ref, col_dl = st.columns(2)
        if col_ref.button("📋 Obtener Referencia de Pago"):
            if not password_sipare:
                st.error("Ingresa la contraseña")
            else:
                from modules.sipare_scraper import obtener_referencia_sync
                with st.spinner("Consultando SIPARE..."):
                    try:
                        ref = obtener_referencia_sync(
                            patron_dict["registro_patronal"], patron_dict["usuario_idse"],
                            password_sipare, cert_path, anio_sel, bim_sel
                        )
                        if ref.get("error"):
                            st.error(ref["error"])
                        else:
                            st.success("✅ Referencia obtenida")
                            st.json(ref)
                    except Exception as e:
                        st.error(f"Error: {e}")

        if col_dl.button("📥 Descargar PDF SIPARE"):
            if not password_sipare:
                st.error("Ingresa la contraseña")
            else:
                from modules.sipare_scraper import descargar_sipare_sync
                with st.spinner("Descargando PDF..."):
                    try:
                        ruta = descargar_sipare_sync(
                            patron_dict["registro_patronal"], patron_dict["usuario_idse"],
                            password_sipare, cert_path, anio_sel, bim_sel
                        )
                        st.success(f"✅ Descargado: {ruta}")
                        with open(ruta, "rb") as f:
                            st.download_button("Descargar aquí", f,
                                               file_name=os.path.basename(ruta),
                                               mime="application/pdf")
                    except Exception as e:
                        st.error(f"Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# 🏥 INCAPACIDADES
# ═══════════════════════════════════════════════════════════════════════════
elif menu == "🏥 Incapacidades":
    st.title("🏥 Análisis de Incapacidades")

    tab1, tab2, tab3 = st.tabs(["Registrar / Calcular", "¿Afecta mi Prima de Riesgo?", "Análisis histórico"])

    with tab1:
        st.subheader("Calcular Subsidio de una Incapacidad")
        col1, col2 = st.columns(2)
        tipo_inc = col1.selectbox("Tipo de incapacidad", [
            "01 — Enfermedad General",
            "02 — Maternidad",
            "03 — Riesgo de Trabajo",
            "04 — Enfermedad Profesional",
        ])
        tipo_cod = tipo_inc[:2]

        sdi_inc = col2.number_input("SDI del trabajador ($)", min_value=0.0, value=400.0)
        sdi_top = col2.number_input("SDI topado IMSS ($)", min_value=0.0, value=400.0,
                                    help="SDI limitado a 25 UMAs")

        col3, col4 = st.columns(2)
        f_ini = col3.date_input("Fecha inicio incapacidad")
        f_fin = col4.date_input("Fecha fin incapacidad",
                                value=date.today() + timedelta(days=7))

        nss_inc = st.text_input("NSS del trabajador")
        nombre_inc = st.text_input("Nombre del trabajador")

        if st.button("Calcular Subsidio", type="primary"):
            try:
                det = calcular_subsidio(
                    tipo=tipo_cod, sdi=sdi_inc, fecha_inicio=f_ini,
                    fecha_fin=f_fin, nss=nss_inc, nombre=nombre_inc,
                    sdi_topado=sdi_top if sdi_top > 0 else None,
                )
                st.divider()
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Días totales", det.dias_totales)
                col_b.metric("Días cargo patrón", det.dias_pagan_patron)
                col_c.metric("Días paga IMSS", det.dias_pagan_imss)

                col_d, col_e = st.columns(2)
                col_d.metric("Subsidio diario IMSS", f"${det.subsidio_diario_imss:,.2f}")
                col_e.metric("Subsidio total IMSS", f"${det.subsidio_total_imss:,.2f}")

                if det.impacto_prima_riesgo:
                    st.warning(f"⚠️ Esta incapacidad ({det.nombre_tipo}) IMPACTA la Prima de Riesgo de Trabajo — revisa la pestaña '¿Afecta mi Prima de Riesgo?'")

                for alerta in det.alertas:
                    st.markdown(f'<div class="alerta-amarilla">⚠️ {alerta}</div>',
                                unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Error: {e}")

    with tab2:
        st.subheader("¿Esta incapacidad sube mi Prima de Riesgo?")
        st.caption("La Prima de Riesgo se recalcula cada febrero. Solo los accidentes de trabajo y enfermedades profesionales la afectan.")

        col1, col2 = st.columns(2)
        tipo_prima = col1.selectbox("Tipo de incapacidad a evaluar", [
            "01 — Enfermedad General",
            "02 — Maternidad",
            "03 — Riesgo de Trabajo (Accidente)",
            "04 — Enfermedad Profesional",
        ], key="tipo_prima")
        tipo_prima_cod = tipo_prima[:2]

        dias_nuevos = col2.number_input("Días de esta incapacidad", min_value=1, value=7, key="dias_prima")

        col3, col4 = st.columns(2)
        prima_actual = col3.number_input(
            "Tu Prima de Riesgo actual (%)",
            min_value=0.5, max_value=10.0, value=3.03, step=0.001, format="%.3f",
            help="La encuentras en tu último SUA o recibo SIPARE. Ejemplo: 3.030"
        )
        clase_prima = col4.selectbox(
            "Clase de riesgo de tu empresa",
            [1, 2, 3, 4, 5],
            index=2,
            format_func=lambda c: f"Clase {['I','II','III','IV','V'][c-1]}",
            key="clase_prima_tab2"
        )

        col5, col6 = st.columns(2)
        trab_prom = col5.number_input(
            "Trabajadores promedio (últimos 12 meses)",
            min_value=1.0, value=10.0, step=1.0,
            help="Suma todos tus trabajadores activos por mes y divide entre 12"
        )
        masa_anual = col6.number_input(
            "Masa salarial anual estimada ($)",
            min_value=0.0, value=500000.0, step=10000.0,
            help="SDI diario promedio × 365 × número de trabajadores"
        )
        dias_acum = col5.number_input(
            "Días de RT/EP ya acumulados este año",
            min_value=0, value=0,
            help="Si ya hubo otros accidentes este año, pon el total de días subsidiados"
        )

        if st.button("🔍 Analizar impacto en Prima de Riesgo", type="primary", key="btn_impacto"):
            from modules.incapacidades import calcular_impacto_prima
            try:
                resultado_prima = calcular_impacto_prima(
                    tipo_incapacidad=tipo_prima_cod,
                    dias_subsidiados_nuevos=int(dias_nuevos),
                    trabajadores_promedio=trab_prom,
                    prima_actual_pct=prima_actual,
                    clase=clase_prima,
                    masa_salarial_anual=masa_anual,
                    dias_subsidiados_acumulados=int(dias_acum),
                )

                st.divider()

                # Semáforo visual
                sem = resultado_prima["semaforo"]
                if sem == "verde":
                    st.success("🟢 SIN IMPACTO EN TU PRIMA DE RIESGO")
                elif sem == "amarillo":
                    st.warning("🟡 IMPACTO MODERADO EN TU PRIMA DE RIESGO")
                else:
                    st.error("🔴 ESTA INCAPACIDAD SÍ SUBE TU PRIMA DE RIESGO")

                # Explicación en lenguaje de negocio
                st.markdown("### ¿Qué significa esto para tu empresa?")
                st.markdown(resultado_prima["explicacion"])

                # Números clave (solo si hay impacto)
                if resultado_prima["afecta_prima"] and resultado_prima["diferencia_pct"] > 0:
                    st.divider()
                    col_a, col_b, col_c = st.columns(3)
                    col_a.metric(
                        "Prima actual",
                        f"{resultado_prima['prima_actual_pct']:.3f}%"
                    )
                    col_b.metric(
                        "Prima proyectada",
                        f"{resultado_prima['prima_nueva_pct']:.3f}%",
                        delta=f"+{resultado_prima['diferencia_pct']:.3f}%",
                        delta_color="inverse"
                    )
                    col_c.metric(
                        "Costo extra al año",
                        f"${resultado_prima['costo_anual_extra']:,.2f}",
                        delta="más en cuotas IMSS",
                        delta_color="inverse"
                    )

                # Recomendaciones
                st.divider()
                st.markdown("### ✅ ¿Qué debes hacer ahora?")
                for i, rec in enumerate(resultado_prima["recomendaciones"], 1):
                    st.markdown(f"**{i}.** {rec}")

            except Exception as e:
                st.error(f"Error al calcular: {e}")

    with tab3:
        with get_session() as s:
            incs_db = (
                s.query(Incapacidad).join(Trabajador)
                .filter(Trabajador.patron_id == patron_id_activo)
                .all()
            )

        if not incs_db:
            st.info("No hay incapacidades registradas para este patrón.")
        else:
            data_inc = []
            for i in incs_db:
                data_inc.append({
                    "NSS": i.trabajador.nss,
                    "Nombre": i.trabajador.nombre,
                    "Folio": i.folio,
                    "Tipo": i.descripcion_tipo,
                    "Fecha Inicio": i.fecha_inicio,
                    "Fecha Fin": i.fecha_fin,
                    "Días": i.dias,
                    "Subsidio Total": i.monto_total_subsidio,
                    "Estado": i.estado,
                })
            df_incs = pd.DataFrame(data_inc)
            st.dataframe(df_incs, use_container_width=True)

            if st.button("📥 Exportar Excel"):
                from modules.incapacidades import calcular_subsidio as cs
                detalles = []
                for i in incs_db:
                    if i.fecha_inicio and i.fecha_fin:
                        try:
                            d = cs(i.tipo or "01", i.monto_subsidio_diario or 0,
                                   i.fecha_inicio, i.fecha_fin, i.folio,
                                   i.trabajador.nss, i.trabajador.nombre)
                            detalles.append(d)
                        except Exception:
                            pass

                with get_session() as s2:
                    _pi = s2.query(Patron).filter_by(id=patron_id_activo).first()
                    nombre_patron = _pi.razon_social if _pi else ""
                ruta = exportar_incapacidades_excel(detalles, patron=nombre_patron)
                with open(ruta, "rb") as f:
                    st.download_button("Descargar", f, file_name=os.path.basename(ruta))


# ═══════════════════════════════════════════════════════════════════════════
# ⚠️ PRIMA DE RIESGO
# ═══════════════════════════════════════════════════════════════════════════
elif menu == "⚠️ Prima de Riesgo":
    st.title("⚠️ Prima de Riesgo de Trabajo")
    st.info("Art. 74 LSS — Se declara en febrero. Período: 1 oct – 30 sep del ejercicio anterior.")

    with get_session() as s:
        _pr = s.query(Patron).filter_by(id=patron_id_activo).first() if patron_id_activo else None
        clase_actual = _pr.clase_riesgo if _pr else 1

    col1, col2 = st.columns(2)
    clase = col1.selectbox("Clase de riesgo",
                           options=[1, 2, 3, 4, 5],
                           index=clase_actual - 1 if clase_actual else 0,
                           format_func=lambda c: f"Clase {['I','II','III','IV','V'][c-1]} — {CLASES_RIESGO[c]['nombre']}")
    ejercicio = col2.number_input("Ejercicio (año)", value=date.today().year - 1,
                                  min_value=2000, max_value=2100)

    col3, col4 = st.columns(2)
    trab_prom = col3.number_input("Trabajadores promedio oct-sep", min_value=1.0, value=10.0)
    dias_sub = col4.number_input("Días subsidiados (RT/EP)", min_value=0.0, value=0.0)

    col5, col6 = st.columns(2)
    dias_ip = col5.number_input("Días incapacidad permanente", min_value=0.0, value=0.0)
    defunciones = col6.number_input("Defunciones", min_value=0, value=0)

    prima_ant = st.number_input("Prima anterior (%) — dejar en 0 si es primer año",
                                min_value=0.0, max_value=100.0, value=0.0, step=0.001)

    if st.button("Calcular Prima de Riesgo", type="primary"):
        try:
            r = calcular_prima_riesgo(
                clase=clase,
                trabajadores_promedio=trab_prom,
                dias_subsidiados=dias_sub,
                dias_incap_permanente=dias_ip,
                defunciones=defunciones,
                prima_anterior=(prima_ant / 100) if prima_ant > 0 else None,
            )
            st.divider()
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Clase de Riesgo", r["nombre_clase"])
            col_b.metric("Prima Calculada", f"{r['prima_calculada_pct']:.5f}%")
            col_c.metric("Prima a Declarar", f"{r['prima_final_pct']:.5f}%",
                         delta=f"{r['variacion_pct']:.5f}%" if r.get("variacion_pct") else None)

            if r.get("nota_variacion"):
                st.warning(f"⚠️ {r['nota_variacion']}")

            with st.expander("Detalle completo"):
                st.json(r)

            if st.button("💾 Guardar Prima en BD") and patron_id_activo:
                from database.models import PrimaRiesgo as ModelPR
                with get_session() as s:
                    pr = ModelPR(
                        patron_id=patron_id_activo,
                        ejercicio=ejercicio,
                        trabajadores_promedio=trab_prom,
                        dias_subsidiados=dias_sub,
                        dias_incapacidad_permanente=dias_ip,
                        defunciones=defunciones,
                        prima_media_clase=r["prima_media_clase_pct"],
                        prima_minima=r["prima_minima_pct"],
                        prima_maxima=r["prima_maxima_pct"],
                        prima_calculada=r["prima_calculada_pct"],
                        prima_declarada=r["prima_final_pct"],
                        prima_anterior=prima_ant if prima_ant > 0 else None,
                        variacion=r.get("variacion_pct"),
                        fecha_declaracion=date.today(),
                    )
                    s.add(pr)
                st.success("✅ Prima guardada")
        except Exception as e:
            st.error(f"Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# 📊 COMPARATIVOS
# ═══════════════════════════════════════════════════════════════════════════
elif menu == "📊 Comparativos":
    st.title("📊 Comparativos entre Períodos")

    tab1, tab2 = st.tabs(["Plantilla / SDI", "Cuotas SIPARE"])

    with tab1:
        col1, col2 = st.columns(2)
        p_actual = col1.text_input("Período actual", placeholder="2024-B3")
        p_anterior = col2.text_input("Período anterior", placeholder="2024-B2")

        if st.button("Comparar") and p_actual and p_anterior and patron_id_activo:
            with get_session() as s:
                comp = comparar_plantilla(s, patron_id_activo, p_actual, p_anterior)

            if "error" in comp:
                st.error(comp["error"])
            else:
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Trabajadores actual", comp["trabajadores_actual"],
                             delta=comp.get("var_trabajadores"))
                col_b.metric("Masa salarial actual", f"${comp['masa_salarial_actual']:,.2f}",
                             delta=f"${comp.get('var_masa_salarial', 0):,.2f}")
                col_c.metric("SDI Promedio", f"${comp['sdi_promedio_actual']:,.2f}")

                if comp.get("altas"):
                    st.success(f"✅ Altas: {len(comp['altas'])} trabajadores")
                if comp.get("bajas"):
                    st.error(f"❌ Bajas: {len(comp['bajas'])} trabajadores")

                if comp.get("cambios_sdi"):
                    st.subheader("Cambios de SDI detectados")
                    st.dataframe(pd.DataFrame(comp["cambios_sdi"]), use_container_width=True)

                ruta = exportar_comparativo_excel(comp)
                with open(ruta, "rb") as f:
                    st.download_button("📥 Exportar comparativo", f,
                                       file_name=os.path.basename(ruta))

    with tab2:
        col1, col2 = st.columns(2)
        anio_comp = col1.selectbox("Año", list(range(date.today().year, 2019, -1)), key="anio_comp")
        bim_comp = col2.selectbox("Bimestre", [1, 2, 3, 4, 5, 6], key="bim_comp",
                                  format_func=lambda b: f"B{b}")

        if st.button("Comparar vs bimestre anterior") and patron_id_activo:
            with get_session() as s:
                comp_s = comparar_sipare(s, patron_id_activo, anio_comp, bim_comp)
            if "error" in comp_s:
                st.error(comp_s["error"])
            else:
                col_a, col_b = st.columns(2)
                col_a.metric("Monto actual", f"${comp_s['monto_actual']:,.2f}",
                             delta=f"{comp_s.get('variacion_pct', 0):.1f}%")
                col_b.metric("Estado", comp_s.get("estado_actual", "—"))
                st.json(comp_s)


# ═══════════════════════════════════════════════════════════════════════════
# 🏢 PATRONES
# ═══════════════════════════════════════════════════════════════════════════
elif menu == "🏢 Patrones":
    st.title("🏢 Gestión de Patrones")

    tab1, tab2 = st.tabs(["Lista de Patrones", "Agregar Patrón"])

    with tab1:
        with get_session() as s:
            filas_pat = [{
                "ID": p.id,
                "Registro Patronal": p.registro_patronal,
                "Razón Social": p.razon_social,
                "RFC": p.rfc,
                "Clase Riesgo": p.clase_riesgo,
                "Activo": p.activo,
            } for p in s.query(Patron).all()]
        if filas_pat:
            st.dataframe(pd.DataFrame(filas_pat), use_container_width=True)
        else:
            st.info("No hay patrones registrados.")

    with tab2:
        with st.form("form_patron"):
            col1, col2 = st.columns(2)
            rp = col1.text_input("Registro Patronal (11 dígitos)")
            rs = col2.text_input("Razón Social")
            rfc = col1.text_input("RFC")
            clase = col2.selectbox("Clase de Riesgo", [1, 2, 3, 4, 5],
                                   format_func=lambda c: f"Clase {['I','II','III','IV','V'][c-1]}")
            usuario = col1.text_input("Usuario IDSE (RFC patrón)")
            cert = col2.text_input("Ruta certificado .cer (opcional)")
            actividad = st.text_input("Actividad económica")
            fraccion = st.text_input("Fracción de riesgo")

            submitted = st.form_submit_button("Guardar Patrón")
            if submitted:
                if not rp or not rs:
                    st.error("Registro Patronal y Razón Social son obligatorios")
                else:
                    with get_session() as s:
                        pat = Patron(
                            registro_patronal=rp.strip(),
                            razon_social=rs.strip(),
                            rfc=rfc.strip(),
                            clase_riesgo=clase,
                            usuario_idse=usuario.strip(),
                            certificado_path=cert.strip() or None,
                            actividad=actividad.strip(),
                            fraccion=fraccion.strip(),
                        )
                        s.add(pat)
                    st.success(f"✅ Patrón {rp} — {rs} registrado correctamente")
                    st.rerun()
