"""
Punto de entrada del Agente IMSS.
Uso:
  python main.py dashboard          → Lanza la UI Streamlit
  python main.py sdi <archivo.xlsx> → Calcula SDI por lote desde Excel
  python main.py sua <archivo.sua>  → Parsea y muestra resumen de un .SUA
  python main.py prima              → Calculadora de prima de riesgo (interactiva)
  python main.py init-db            → Inicializa la base de datos
"""
import sys
import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from database.connection import init_db

console = Console()


def cmd_dashboard():
    console.print(Panel("Iniciando Dashboard Streamlit...", style="bold blue"))
    app_path = Path(__file__).parent / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)], check=True)


def cmd_sua(filepath: str):
    from modules.sua_parser import parse_sua
    console.print(f"[bold]Procesando:[/bold] {filepath}")
    resultado = parse_sua(filepath)

    if resultado.patron:
        p = resultado.patron
        console.print(Panel(
            f"Patrón: {p.razon_social}\n"
            f"RP: {p.registro_patronal} | RFC: {p.rfc}\n"
            f"Período: {p.periodo} | Clase: {p.clase_riesgo}",
            title="Datos del Patrón", style="green"
        ))

    table = Table(title=f"Trabajadores ({len(resultado.trabajadores)})")
    table.add_column("NSS", style="cyan")
    table.add_column("Nombre")
    table.add_column("SD", justify="right")
    table.add_column("SDI", justify="right")
    table.add_column("Movimiento")

    for t in resultado.trabajadores[:50]:  # Mostrar primeros 50
        table.add_row(
            t.nss, t.nombre,
            f"${t.salario_diario:,.2f}",
            f"${t.sdi:,.2f}",
            t.movimiento or "—"
        )
    console.print(table)

    if resultado.errores:
        console.print(f"\n[yellow]⚠️ {len(resultado.errores)} advertencias:[/yellow]")
        for e in resultado.errores[:5]:
            console.print(f"  • {e}")

    console.print(f"\n[bold]Cuotas IMSS:[/bold] ${resultado.total_cuotas_imss:,.2f}")
    console.print(f"[bold]Cuotas INFONAVIT:[/bold] ${resultado.total_cuotas_infonavit:,.2f}")


def cmd_sdi_batch(filepath: str):
    import pandas as pd
    from modules.sdi_calculator import calcular_sdi_batch
    from reports.exporter import exportar_sdi_excel

    if filepath.endswith(".csv"):
        df = pd.read_csv(filepath)
    else:
        df = pd.read_excel(filepath)

    registros = df.to_dict(orient="records")
    resultados = calcular_sdi_batch(registros)

    table = Table(title="Resultados SDI")
    table.add_column("NSS")
    table.add_column("Nombre")
    table.add_column("SD", justify="right")
    table.add_column("FI", justify="right")
    table.add_column("SDI", justify="right")
    table.add_column("SDI Topado", justify="right")

    for r in resultados:
        table.add_row(
            r.get("nss", ""),
            r.get("nombre", ""),
            f"${r['salario_diario_base']:,.2f}",
            f"{r['factor_integracion']:.4f}",
            f"${r['sdi']:,.2f}",
            f"${r['sdi_topado_imss']:,.2f}",
        )
    console.print(table)

    ruta = exportar_sdi_excel(resultados)
    console.print(f"\n[green]✅ Excel exportado:[/green] {ruta}")


def cmd_init_db():
    console.print("[bold]Inicializando base de datos...[/bold]")
    init_db()
    console.print("[green]✅ Base de datos lista.[/green]")


def main():
    args = sys.argv[1:]
    if not args or args[0] == "dashboard":
        cmd_dashboard()
    elif args[0] == "init-db":
        cmd_init_db()
    elif args[0] == "sua" and len(args) > 1:
        cmd_sua(args[1])
    elif args[0] == "sdi" and len(args) > 1:
        cmd_sdi_batch(args[1])
    else:
        console.print(__doc__)


if __name__ == "__main__":
    main()
