@echo off
rem MoonBit 0.1.20260920 defines this after windows.h; MinGW needs it first.
cc.exe -D_CRT_RAND_S %*
exit /b %errorlevel%
