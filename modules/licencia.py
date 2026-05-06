"""
Sistema de licencias para Agente IMSS.
Genera un fingerprint único por máquina y valida contra servidor de activación.
Guarda la licencia cifrada localmente con gracia de 3 días sin internet.
"""
import hashlib
import json
import os
import platform
import socket
import struct
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

# ── Configuración ────────────────────────────────────────────────────────────
SERVIDOR_LICENCIAS = "https://licencias.tudominio.com/api"   # Cambia por tu servidor
DIAS_GRACIA_OFFLINE = 3
ARCHIVO_LICENCIA = Path(os.environ.get("APPDATA", ".")) / "AgenteIMSS" / "licencia.dat"
SALT = b"agente_imss_2024_salt_unico"     # Cambia esto antes de distribuir


# ── Fingerprint de máquina ───────────────────────────────────────────────────

def _mac_address() -> str:
    try:
        mac = uuid.getnode()
        return ":".join(f"{(mac >> (8 * i)) & 0xFF:02x}" for i in range(5, -1, -1))
    except Exception:
        return "00:00:00:00:00:00"


def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _procesador() -> str:
    try:
        return platform.processor()[:50]
    except Exception:
        return "unknown"


def generar_fingerprint() -> str:
    """Genera un ID único de la máquina — estable entre reinicios."""
    datos = f"{_mac_address()}|{_hostname()}|{_procesador()}|{platform.system()}"
    return hashlib.sha256(datos.encode()).hexdigest()[:32].upper()


# ── Cifrado local ────────────────────────────────────────────────────────────

def _clave_fernet() -> Fernet:
    """Deriva clave Fernet del fingerprint de la máquina."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=100_000,
    )
    fp = generar_fingerprint().encode()
    clave = base64.urlsafe_b64encode(kdf.derive(fp))
    return Fernet(clave)


def _guardar_licencia(datos: dict):
    ARCHIVO_LICENCIA.parent.mkdir(parents=True, exist_ok=True)
    f = _clave_fernet()
    cifrado = f.encrypt(json.dumps(datos).encode())
    ARCHIVO_LICENCIA.write_bytes(cifrado)


def _leer_licencia() -> Optional[dict]:
    if not ARCHIVO_LICENCIA.exists():
        return None
    try:
        f = _clave_fernet()
        raw = f.decrypt(ARCHIVO_LICENCIA.read_bytes())
        return json.loads(raw.decode())
    except Exception:
        return None


# ── Validación ───────────────────────────────────────────────────────────────

class EstadoLicencia:
    VALIDA = "valida"
    GRACIA = "gracia"          # Sin internet, dentro del período de gracia
    VENCIDA = "vencida"
    INVALIDA = "invalida"
    NO_ACTIVADA = "no_activada"


def activar_licencia(clave: str) -> dict:
    """
    Activa una clave de licencia contra el servidor.
    Retorna {"ok": True, "mensaje": ..., "expira": "YYYY-MM-DD", "tier": "pro"}
    """
    fp = generar_fingerprint()
    try:
        r = requests.post(
            f"{SERVIDOR_LICENCIAS}/activar",
            json={"clave": clave, "fingerprint": fp, "version": "1.0.0"},
            timeout=10,
        )
        datos = r.json()
        if datos.get("ok"):
            # Guardar localmente
            payload = {
                "clave": clave,
                "fingerprint": fp,
                "expira": datos["expira"],
                "tier": datos.get("tier", "basico"),
                "razon_social": datos.get("razon_social", ""),
                "ultima_validacion": datetime.now().isoformat(),
            }
            _guardar_licencia(payload)
            return {"ok": True, "mensaje": "Licencia activada correctamente.", **payload}
        return {"ok": False, "mensaje": datos.get("mensaje", "Clave inválida.")}
    except requests.RequestException:
        return {"ok": False, "mensaje": "Sin conexión al servidor de licencias."}


def verificar_licencia() -> dict:
    """
    Verifica el estado de la licencia. Flujo:
    1. Lee licencia local cifrada.
    2. Si tiene internet → valida contra servidor (refresca).
    3. Si no hay internet → usa gracia de 3 días.
    """
    local = _leer_licencia()
    fp = generar_fingerprint()

    if not local:
        return {"estado": EstadoLicencia.NO_ACTIVADA, "mensaje": "Sin licencia. Ingresa tu clave de activación."}

    # Verificar que el fingerprint coincide (no copiar licencia entre máquinas)
    if local.get("fingerprint") != fp:
        return {"estado": EstadoLicencia.INVALIDA, "mensaje": "Licencia no válida para esta máquina."}

    # Intentar validar online
    try:
        r = requests.post(
            f"{SERVIDOR_LICENCIAS}/verificar",
            json={"clave": local["clave"], "fingerprint": fp},
            timeout=5,
        )
        datos = r.json()
        if not datos.get("ok"):
            return {"estado": EstadoLicencia.INVALIDA, "mensaje": datos.get("mensaje", "Licencia revocada.")}

        # Actualizar fecha de última validación
        local["ultima_validacion"] = datetime.now().isoformat()
        local["expira"] = datos.get("expira", local["expira"])
        _guardar_licencia(local)

    except requests.RequestException:
        # Sin internet — aplicar período de gracia
        ultima = datetime.fromisoformat(local.get("ultima_validacion", "2000-01-01"))
        dias_offline = (datetime.now() - ultima).days
        if dias_offline > DIAS_GRACIA_OFFLINE:
            return {
                "estado": EstadoLicencia.INVALIDA,
                "mensaje": f"Sin conexión por {dias_offline} días. Conecta a internet para continuar.",
            }
        return {
            "estado": EstadoLicencia.GRACIA,
            "mensaje": f"Sin internet. Gracia: {DIAS_GRACIA_OFFLINE - dias_offline} día(s) restante(s).",
            **local,
        }

    # Verificar fecha de expiración
    try:
        expira = datetime.strptime(local["expira"], "%Y-%m-%d")
        if datetime.now() > expira:
            return {"estado": EstadoLicencia.VENCIDA,
                    "mensaje": f"Licencia vencida el {local['expira']}. Renueva en tudominio.com"}
    except (ValueError, KeyError):
        pass

    return {
        "estado": EstadoLicencia.VALIDA,
        "mensaje": "Licencia activa.",
        "tier": local.get("tier", "basico"),
        "expira": local.get("expira", ""),
        "razon_social": local.get("razon_social", ""),
    }


def es_licencia_valida() -> bool:
    estado = verificar_licencia()["estado"]
    return estado in (EstadoLicencia.VALIDA, EstadoLicencia.GRACIA)


def get_tier() -> str:
    local = _leer_licencia()
    return local.get("tier", "basico") if local else "ninguno"
