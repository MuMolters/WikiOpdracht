@echo off
REM Bouwt robotnet.exe met de MSVC-compiler van Visual Studio 2022 (statisch gelinkt,
REM zodat de exe zonder extra DLL's op de tweede pc kan draaien).
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
cl /nologo /EHsc /O2 /std:c++17 /MT /W4 robotnet.cpp
