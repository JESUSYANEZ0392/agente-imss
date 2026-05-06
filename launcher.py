"""
Launcher del Agente IMSS.
Este es el archivo que PyInstaller convierte en .exe.
Responsabilidades:
  1. Verificar licencia
  2. Mostrar splash screen
  3. Iniciar servidor Streamlit en background
  4. Abrir el navegador en localhost:8501
  5. Crear ícono en bandeja del sistema (system tray)
  6. Controlar el ciclo de vida de la aplicación
"""
import os
import sys
import time
import socket
import threading
import subprocess
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

# ── Ruta base (funciona tanto en .py como en .exe compilado) ─────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

APP_DIR = BASE_DIR
PORT = 8501
URL = f"http://localhost:{PORT}"

# Agregar directorio de la app al path
sys.path.insert(0, str(APP_DIR))


# ── Verificación de licencia ─────────────────────────────────────────────────

def verificar_y_activar() -> bool:
    """Muestra ventana de activación si no hay licencia válida. Retorna True si OK."""
    try:
        from modules.licencia import verificar_licencia, activar_licencia, EstadoLicencia, generar_fingerprint
        resultado = verificar_licencia()

        if resultado["estado"] in (EstadoLicencia.VALIDA, EstadoLicencia.GRACIA):
            if resultado["estado"] == EstadoLicencia.GRACIA:
                messagebox.showwarning(
                    "Agente IMSS — Aviso",
                    f"Sin conexión a internet.\n{resultado['mensaje']}"
                )
            return True

        # Mostrar ventana de activación
        return mostrar_ventana_activacion(resultado["mensaje"])

    except ImportError:
        # Si no está el módulo de licencia, permitir sin validación (modo desarrollo)
        return True


def mostrar_ventana_activacion(mensaje_error: str = "") -> bool:
    """Ventana de activación de licencia."""
    activado = [False]

    ventana = tk.Tk()
    ventana.title("Agente IMSS — Activación")
    ventana.geometry("480x320")
    ventana.resizable(False, False)
    ventana.configure(bg="#1a1a2e")

    try:
        ventana.iconbitmap(str(APP_DIR / "assets" / "icon.ico"))
    except Exception:
        pass

    # Logo / título
    tk.Label(ventana, text="🏛️ Agente IMSS", font=("Segoe UI", 20, "bold"),
             bg="#1a1a2e", fg="#ffffff").pack(pady=(25, 5))
    tk.Label(ventana, text="Automatización de Seguridad Social",
             font=("Segoe UI", 10), bg="#1a1a2e", fg="#a0a0c0").pack()

    tk.Frame(ventana, bg="#2a2a4e", height=1).pack(fill="x", pady=15, padx=30)

    if mensaje_error:
        tk.Label(ventana, text=mensaje_error, font=("Segoe UI", 9),
                 bg="#1a1a2e", fg="#ff6b6b", wraplength=400).pack(pady=(0, 10))

    tk.Label(ventana, text="Clave de activación:", font=("Segoe UI", 10),
             bg="#1a1a2e", fg="#ffffff").pack()

    entry_clave = tk.Entry(ventana, width=35, font=("Courier New", 12),
                           justify="center", relief="flat",
                           bg="#2a2a4e", fg="#ffffff", insertbackground="white")
    entry_clave.pack(pady=8, ipady=6)

    lbl_estado = tk.Label(ventana, text="", font=("Segoe UI", 9),
                          bg="#1a1a2e", fg="#ffd700", wraplength=400)
    lbl_estado.pack()

    def on_activar():
        clave = entry_clave.get().strip().upper()
        if not clave:
            lbl_estado.config(text="Ingresa tu clave de activación.", fg="#ff6b6b")
            return
        lbl_estado.config(text="Verificando...", fg="#ffd700")
        ventana.update()

        from modules.licencia import activar_licencia
        r = activar_licencia(clave)
        if r["ok"]:
            lbl_estado.config(text="✅ " + r["mensaje"], fg="#51cf66")
            ventana.update()
            time.sleep(1)
            activado[0] = True
            ventana.destroy()
        else:
            lbl_estado.config(text="❌ " + r["mensaje"], fg="#ff6b6b")

    def on_comprar():
        webbrowser.open("https://tudominio.com/comprar")

    # Mostrar fingerprint para soporte
    try:
        from modules.licencia import generar_fingerprint
        fp = generar_fingerprint()
    except Exception:
        fp = "N/A"

    btn_frame = tk.Frame(ventana, bg="#1a1a2e")
    btn_frame.pack(pady=10)

    tk.Button(btn_frame, text="  Activar  ", command=on_activar,
              bg="#4c6ef5", fg="white", font=("Segoe UI", 10, "bold"),
              relief="flat", padx=10, pady=5, cursor="hand2").pack(side="left", padx=5)

    tk.Button(btn_frame, text="Comprar licencia", command=on_comprar,
              bg="#2a2a4e", fg="#a0a0c0", font=("Segoe UI", 9),
              relief="flat", padx=8, pady=5, cursor="hand2").pack(side="left", padx=5)

    tk.Label(ventana, text=f"ID de equipo: {fp}", font=("Courier New", 7),
             bg="#1a1a2e", fg="#404060").pack(side="bottom", pady=8)

    ventana.mainloop()
    return activado[0]


# ── Splash Screen ─────────────────────────────────────────────────────────────

class SplashScreen:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.configure(bg="#1a1a2e")

        ancho, alto = 420, 220
        x = (self.root.winfo_screenwidth() - ancho) // 2
        y = (self.root.winfo_screenheight() - alto) // 2
        self.root.geometry(f"{ancho}x{alto}+{x}+{y}")

        tk.Label(self.root, text="🏛️", font=("Segoe UI", 36),
                 bg="#1a1a2e", fg="#4c6ef5").pack(pady=(30, 5))
        tk.Label(self.root, text="Agente IMSS", font=("Segoe UI", 18, "bold"),
                 bg="#1a1a2e", fg="#ffffff").pack()
        tk.Label(self.root, text="Iniciando aplicación...",
                 font=("Segoe UI", 9), bg="#1a1a2e", fg="#a0a0c0").pack(pady=5)

        self.barra = ttk.Progressbar(self.root, mode="indeterminate", length=300)
        self.barra.pack(pady=10)
        self.barra.start(12)

        self.lbl_estado = tk.Label(self.root, text="Cargando módulos...",
                                   font=("Segoe UI", 8), bg="#1a1a2e", fg="#606080")
        self.lbl_estado.pack()

        tk.Label(self.root, text="v1.0.0", font=("Segoe UI", 7),
                 bg="#1a1a2e", fg="#303050").pack(side="bottom", pady=5)

        self.root.update()

    def set_estado(self, texto: str):
        self.lbl_estado.config(text=texto)
        self.root.update()

    def cerrar(self):
        self.barra.stop()
        self.root.destroy()


# ── Servidor Streamlit ────────────────────────────────────────────────────────

_proceso_streamlit = None


def _puerto_libre(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) != 0


def iniciar_streamlit():
    global _proceso_streamlit
    app_path = APP_DIR / "dashboard" / "app.py"

    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.port", str(PORT),
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
        "--browser.gatherUsageStats", "false",
        "--theme.base", "dark",
        "--theme.primaryColor", "#4c6ef5",
    ]

    _proceso_streamlit = subprocess.Popen(
        cmd,
        cwd=str(APP_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def esperar_streamlit(timeout: int = 30) -> bool:
    """Espera hasta que Streamlit responda en el puerto."""
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            with socket.create_connection(("localhost", PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


# ── Ícono en bandeja del sistema ──────────────────────────────────────────────

def iniciar_tray():
    """Crea ícono en bandeja con menú contextual (requiere pystray)."""
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Crear ícono simple si no existe el .ico
        img = Image.new("RGB", (64, 64), color="#1a1a2e")
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 56, 56], fill="#4c6ef5")
        draw.text((18, 18), "IM", fill="white")

        def on_abrir(icon, item):
            webbrowser.open(URL)

        def on_salir(icon, item):
            icon.stop()
            if _proceso_streamlit:
                _proceso_streamlit.terminate()
            os._exit(0)

        icono = pystray.Icon(
            "AgenteIMSS",
            img,
            "Agente IMSS",
            menu=pystray.Menu(
                pystray.MenuItem("Abrir Dashboard", on_abrir, default=True),
                pystray.MenuItem("Salir", on_salir),
            )
        )
        icono.run()
    except ImportError:
        # pystray no disponible — mantener proceso vivo con loop simple
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # 1. Verificar licencia (antes de mostrar splash)
    root_check = tk.Tk()
    root_check.withdraw()
    if not verificar_y_activar():
        root_check.destroy()
        sys.exit(0)
    root_check.destroy()

    # 2. Splash screen
    splash = SplashScreen()
    splash.set_estado("Verificando entorno...")

    # 3. Iniciar Streamlit
    if _puerto_libre(PORT):
        splash.set_estado("Iniciando servidor Streamlit...")
        iniciar_streamlit()
    else:
        splash.set_estado("Servidor ya activo, conectando...")

    # 4. Esperar a que esté listo
    splash.set_estado("Esperando que la aplicación esté lista...")
    listo = esperar_streamlit(timeout=40)

    splash.cerrar()

    if not listo:
        messagebox.showerror(
            "Agente IMSS",
            "No se pudo iniciar la aplicación.\n"
            "Verifica que Python y las dependencias estén instalados correctamente."
        )
        if _proceso_streamlit:
            _proceso_streamlit.terminate()
        sys.exit(1)

    # 5. Abrir navegador
    time.sleep(0.5)
    webbrowser.open(URL)

    # 6. Mantener vivo con ícono en bandeja
    tray_thread = threading.Thread(target=iniciar_tray, daemon=False)
    tray_thread.start()
    tray_thread.join()


if __name__ == "__main__":
    main()
