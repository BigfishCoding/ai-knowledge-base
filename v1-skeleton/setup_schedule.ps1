# ═══════════════════════════════════════════════════════════════
#  AI Knowledge Base — 一键注册 Windows 定时任务
#  用法: 以管理员权限运行 PowerShell，执行此脚本
# ═══════════════════════════════════════════════════════════════

#Requires -RunAsAdministrator

$TASK_NAME = "AI-KnowledgeBase-Daily"
$BAT_PATH  = "E:\openCode\ai-knowledge-base\v1-skeleton\run_daily.bat"

# 检查启动脚本是否存在
if (-not (Test-Path $BAT_PATH)) {
    Write-Host "[错误] 找不到启动脚本: $BAT_PATH" -ForegroundColor Red
    exit 1
}

# 如果任务已存在，先删除
$existing = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[信息] 任务 '$TASK_NAME' 已存在，正在删除旧任务..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
}

# 创建触发器：每天早上 9:00
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00AM

# 创建动作
$action = New-ScheduledTaskAction -Execute $BAT_PATH -WorkingDirectory "E:\openCode\ai-knowledge-base\v1-skeleton"

# 创建设置
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# 注册任务
Register-ScheduledTask `
    -TaskName $TASK_NAME `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "AI 知识库每日自动采集流水线 — 每天 09:00 执行" `
    -RunLevel Highest

Write-Host ""
Write-Host "[成功] 定时任务 '$TASK_NAME' 已注册!" -ForegroundColor Green
Write-Host "  - 触发时间: 每天 09:00" -ForegroundColor Cyan
Write-Host "  - 启动脚本: $BAT_PATH" -ForegroundColor Cyan
Write-Host "  - 错过补执行: 是" -ForegroundColor Cyan
Write-Host "  - 失败重试: 3 次，间隔 5 分钟" -ForegroundColor Cyan
Write-Host "  - 超时限制: 2 小时" -ForegroundColor Cyan
Write-Host ""
Write-Host "管理命令:" -ForegroundColor Yellow
Write-Host "  手动运行:    Start-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor Gray
Write-Host "  查看任务:    Get-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor Gray
Write-Host "  查看历史:    Get-ScheduledTaskInfo -TaskName '$TASK_NAME'" -ForegroundColor Gray
Write-Host "  禁用任务:    Disable-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor Gray
Write-Host "  删除任务:    Unregister-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor Gray
