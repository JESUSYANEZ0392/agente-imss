from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///agente_imss.db")
SCRAPING_TIMEOUT = int(os.getenv("SCRAPING_TIMEOUT", "30"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reportes")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# URLs de portales IMSS
URL_IDSE = "https://idse.imss.gob.mx/imss/faces/pages/inicio.xhtml"
URL_SIPARE = "https://sipare.imss.gob.mx/"
URL_IMSS_DIGITAL = "https://serviciosdigitales.imss.gob.mx/"
