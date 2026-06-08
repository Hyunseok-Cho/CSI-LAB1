@echo off
cd /d "%~dp0.."
"C:\Users\joy40\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m csi_lab1.task2_modbus_gui --port COM6 --role slave
