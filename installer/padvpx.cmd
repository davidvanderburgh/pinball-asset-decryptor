@echo off
rem The Visual Pinball kit, on the app's own Python: `padvpx setup "<table.vpx>" <card.raw>`,
rem `padvpx patch`, `padvpx lcd`, `padvpx status` ... (tools\spike2_emu\vpx\padvpx.py).
"%~dp0python\python.exe" "%~dp0tools\spike2_emu\vpx\padvpx.py" %*
