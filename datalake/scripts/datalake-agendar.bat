@echo off
REM ============================================================
REM  Datalake CCM -- agendamento diario
REM  Clique com o botao direito e escolha "Executar como
REM  administrador". Depois disso a carga roda sozinha as 5h,
REM  todos os dias, e voce nao precisa mais abrir nada.
REM ============================================================
title Datalake CCM - agendar carga diaria
net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERRO: precisa ser executado como administrador.
    echo  Clique com o botao direito neste arquivo e escolha
    echo  "Executar como administrador".
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File \"C:\datalake\setup_windows.ps1\" -Run -LakeRoot \"C:\datalake\"' -WorkingDirectory 'C:\datalake';" ^
 "$t = New-ScheduledTaskTrigger -Daily -At 5:00am;" ^
 "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2);" ^
 "Register-ScheduledTask -TaskName 'Datalake CCM' -Action $a -Trigger $t -Settings $s -User 'SYSTEM' -RunLevel Highest -Force | Out-Null;" ^
 "Write-Host '';" ^
 "Write-Host '  Agendado: todos os dias as 05:00' -ForegroundColor Green;" ^
 "Write-Host '  Para conferir: Agendador de Tarefas > Datalake CCM';" ^
 "Write-Host ''"

echo.
echo  Pressione qualquer tecla para fechar.
pause >nul
