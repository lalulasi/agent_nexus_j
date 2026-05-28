@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create([IO.File]::ReadAllText('%~dp0start.ps1')))"
