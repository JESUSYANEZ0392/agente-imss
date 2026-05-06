from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime,
    ForeignKey, Boolean, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()


class Patron(Base):
    __tablename__ = "patrones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    registro_patronal = Column(String(11), unique=True, nullable=False)
    razon_social = Column(String(200), nullable=False)
    rfc = Column(String(13))
    clase_riesgo = Column(Integer)          # I=1 a V=5
    fraccion = Column(String(10))
    actividad = Column(String(300))
    usuario_idse = Column(String(100))      # RFC o usuario IDSE
    certificado_path = Column(String(500))  # Ruta del .cer
    activo = Column(Boolean, default=True)
    notas = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    trabajadores = relationship("Trabajador", back_populates="patron", cascade="all, delete-orphan")
    primas_riesgo = relationship("PrimaRiesgo", back_populates="patron", cascade="all, delete-orphan")
    pagos = relationship("PagoSIPARE", back_populates="patron", cascade="all, delete-orphan")
    archivos_sua = relationship("ArchivoSUA", back_populates="patron", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Patron {self.registro_patronal} - {self.razon_social}>"


class Trabajador(Base):
    __tablename__ = "trabajadores"
    __table_args__ = (UniqueConstraint("patron_id", "nss", name="uq_patron_nss"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    patron_id = Column(Integer, ForeignKey("patrones.id"), nullable=False)
    nss = Column(String(11), nullable=False)
    curp = Column(String(18))
    rfc = Column(String(13))
    nombre = Column(String(200), nullable=False)
    fecha_ingreso = Column(Date)
    fecha_baja = Column(Date)
    tipo_trabajador = Column(String(2), default="01")  # 01=permanente, 02=eventual ciudad, 03=eventual campo
    tipo_salario = Column(String(10), default="fijo")  # fijo, variable, mixto
    activo = Column(Boolean, default=True)
    departamento = Column(String(100))
    puesto = Column(String(100))

    patron = relationship("Patron", back_populates="trabajadores")
    salarios = relationship("RegistroSalario", back_populates="trabajador", cascade="all, delete-orphan")
    incapacidades = relationship("Incapacidad", back_populates="trabajador", cascade="all, delete-orphan")
    movimientos = relationship("MovimientoAfiliatorio", back_populates="trabajador", cascade="all, delete-orphan")
    incidencias = relationship("Incidencia", back_populates="trabajador", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Trabajador {self.nss} - {self.nombre}>"


class RegistroSalario(Base):
    """Historial de SDI por trabajador por período."""
    __tablename__ = "registros_salario"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False)
    fecha_registro = Column(Date, nullable=False)
    periodo = Column(String(7), nullable=False)     # Ej: "2024-01" o "2024-B1"
    salario_diario_base = Column(Float, nullable=False)
    salario_diario_integrado = Column(Float)
    factor_integracion = Column(Float)

    # Prestaciones usadas para el cálculo
    dias_aguinaldo = Column(Float, default=15.0)
    dias_vacaciones = Column(Float)
    prima_vacacional_pct = Column(Float, default=0.25)
    vale_despensa_diario = Column(Float, default=0.0)
    fondo_ahorro_pct = Column(Float, default=0.0)
    otros_conceptos_diarios = Column(Float, default=0.0)
    tipo_prestaciones = Column(String(10), default="ley")  # "ley" o "superiores"

    # Límite IMSS
    uma_vigente = Column(Float)
    veces_uma_limite = Column(Float, default=25.0)
    sdi_topado = Column(Float)   # SDI limitado a 25 UMAs para cuotas

    trabajador = relationship("Trabajador", back_populates="salarios")


class MovimientoAfiliatorio(Base):
    """Movimientos IDSE: altas, bajas, modificaciones de salario."""
    __tablename__ = "movimientos_afiliatorios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False)
    tipo_movimiento = Column(String(2), nullable=False)
    # 08=Alta, 02=Baja, 07=Modificación Salario, 11=Ausentismo, 12=Reanudación
    descripcion_movimiento = Column(String(50))
    fecha_movimiento = Column(Date, nullable=False)
    salario_diario = Column(Float)
    estado = Column(String(20), default="pendiente")  # pendiente, enviado, aceptado, rechazado
    folio_idse = Column(String(50))
    causa_baja = Column(String(3))  # 01=Voluntaria, 02=Defunción, etc.
    fecha_proceso = Column(DateTime)
    respuesta_imss = Column(Text)    # JSON con respuesta IDSE

    trabajador = relationship("Trabajador", back_populates="movimientos")


class Incapacidad(Base):
    __tablename__ = "incapacidades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False)
    folio = Column(String(50), unique=True)
    tipo = Column(String(2))
    # 01=Enfermedad General, 02=Maternidad, 03=Riesgo de Trabajo, 04=Enfermedad Profesional
    descripcion_tipo = Column(String(50))
    fecha_inicio = Column(Date)
    fecha_fin = Column(Date)
    dias = Column(Integer)
    porcentaje_subsidio = Column(Float)   # 60%, 70%, 100%
    monto_subsidio_diario = Column(Float)
    monto_total_subsidio = Column(Float)
    estado = Column(String(20))           # vigente, concluida, cancelada
    secuencia = Column(Integer, default=1)  # Número de prórroga
    pdf_path = Column(String(500))

    trabajador = relationship("Trabajador", back_populates="incapacidades")


class Incidencia(Base):
    """Registro de faltas, retardos, horas extra, etc."""
    __tablename__ = "incidencias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False)
    periodo = Column(String(7), nullable=False)
    tipo = Column(String(30), nullable=False)
    # falta_injustificada, falta_justificada, retardo, hora_extra, suspension
    fecha = Column(Date, nullable=False)
    cantidad = Column(Float, default=1.0)   # horas o días según tipo
    descuento_aplicado = Column(Float, default=0.0)
    notas = Column(Text)

    trabajador = relationship("Trabajador", back_populates="incidencias")


class PrimaRiesgo(Base):
    """Declaración anual de Prima de Riesgo de Trabajo (IMSS Art. 74)."""
    __tablename__ = "primas_riesgo"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patron_id = Column(Integer, ForeignKey("patrones.id"), nullable=False)
    ejercicio = Column(Integer, nullable=False)           # Año del período (Oct-Sep)
    trabajadores_promedio = Column(Float)
    dias_subsidiados = Column(Float, default=0.0)         # Por incapacidades RT/EP
    dias_incapacidad_permanente = Column(Float, default=0.0)
    defunciones = Column(Integer, default=0)
    prima_media_clase = Column(Float)
    prima_minima = Column(Float)
    prima_maxima = Column(Float)
    prima_calculada = Column(Float)
    prima_declarada = Column(Float)
    prima_anterior = Column(Float)
    variacion = Column(Float)    # Diferencia vs prima anterior
    fecha_declaracion = Column(Date)
    vigente = Column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("patron_id", "ejercicio", name="uq_patron_ejercicio"),)

    patron = relationship("Patron", back_populates="primas_riesgo")


class PagoSIPARE(Base):
    """Referencias y pagos bimestrales SIPARE."""
    __tablename__ = "pagos_sipare"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patron_id = Column(Integer, ForeignKey("patrones.id"), nullable=False)
    anio = Column(Integer, nullable=False)
    bimestre = Column(Integer, nullable=False)    # 1 a 6
    periodo_label = Column(String(20))            # Ej: "Ene-Feb 2024"
    linea_captura = Column(String(200))
    monto_cuotas_obrero = Column(Float, default=0.0)
    monto_cuotas_patronal = Column(Float, default=0.0)
    monto_retiro = Column(Float, default=0.0)
    monto_infonavit = Column(Float, default=0.0)
    monto_total = Column(Float)
    fecha_limite_pago = Column(Date)
    fecha_pago = Column(Date)
    estado = Column(String(20), default="pendiente")  # pendiente, pagado, vencido
    archivo_pdf_path = Column(String(500))
    __table_args__ = (UniqueConstraint("patron_id", "anio", "bimestre", name="uq_patron_periodo"),)

    patron = relationship("Patron", back_populates="pagos")


class ArchivoSUA(Base):
    """Registro de archivos .SUA procesados."""
    __tablename__ = "archivos_sua"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patron_id = Column(Integer, ForeignKey("patrones.id"), nullable=False)
    nombre_archivo = Column(String(200))
    periodo = Column(String(7))
    fecha_carga = Column(DateTime, default=datetime.utcnow)
    registros_trabajadores = Column(Integer, default=0)
    total_cuotas_imss = Column(Float, default=0.0)
    total_cuotas_infonavit = Column(Float, default=0.0)
    hash_archivo = Column(String(64))    # SHA256 para detectar duplicados
    ruta_archivo = Column(String(500))
    procesado = Column(Boolean, default=False)
    errores = Column(Text)

    patron = relationship("Patron", back_populates="archivos_sua")
