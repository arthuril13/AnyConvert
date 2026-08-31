@echo off
REM Builds dist\AnyConvert.exe - a single portable file you can copy anywhere.
setlocal

cd /d "%~dp0"

echo === installing dependencies ===
python -m pip install -r requirements.txt || goto :fail

echo.
echo === drawing the icon ===
python make_icon.py || goto :fail

echo.
echo === checking the converters still work ===
python selftest.py || goto :fail

echo.
echo === building the exe ===
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name AnyConvert ^
  --icon icon.ico ^
  --add-data "icon.ico;." ^
  --collect-all tkinterdnd2 ^
  --collect-all pillow_heif ^
  --collect-data reportlab ^
  --hidden-import PIL._tkinter_finder ^
  --hidden-import converters.images ^
  --hidden-import converters.media ^
  --hidden-import converters.documents ^
  --hidden-import converters.data ^
  --hidden-import converters.archives ^
  --hidden-import converters.diskimages ^
  --hidden-import converters.fonts ^
  app.py || goto :fail

echo.
echo ==========================================================
echo  Done.  dist\AnyConvert.exe
echo ==========================================================
goto :eof

:fail
echo.
echo BUILD FAILED - see the messages above.
exit /b 1
