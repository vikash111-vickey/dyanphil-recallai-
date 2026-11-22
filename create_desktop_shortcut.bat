@echo off
setlocal
cd /d "%~dp0"

echo Creating Dyanphil Desktop Shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$WshShell = New-Object -ComObject WScript.Shell; $Desktop = [System.Environment]::GetFolderPath('Desktop'); $Shortcut = $WshShell.CreateShortcut(\"$Desktop\Dyanphil.lnk\"); $Shortcut.TargetPath = '%~dp0start.bat'; $Shortcut.WorkingDirectory = '%~dp0'; $Shortcut.Description = 'Dyanphil - Laptop File Search & Emergency Vault'; $Shortcut.Save(); Write-Host 'Shortcut created successfully on Desktop!'"
pause
