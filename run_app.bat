@echo off
cd /d "%~dp0"
"%~dp0.venv-1\Scripts\python.exe" -m streamlit run app.py --server.headless true --server.address 0.0.0.0 --server.port 59034
pause
