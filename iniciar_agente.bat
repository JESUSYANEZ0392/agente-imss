@echo off
cd /d C:\Users\consu\agente-imss
call .venv\Scripts\activate
start "" http://localhost:8501
streamlit run dashboard/app.py
