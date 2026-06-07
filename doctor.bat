@echo off
chcp 65001 >nul

echo.
echo ================================================
echo   SiYuan Bridge — 诊断脚本
echo ================================================
echo.

:: 确定安装目录
set "INSTALL_DIR=%~dp0"
cd /d "%INSTALL_DIR%"

echo 安装目录: %INSTALL_DIR%
echo.

:: 检查 Python
echo [1/4] 检查 Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [失败] 未找到 Python。请先安装 Python 3.11+。
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [OK] Python %%v

:: 检查配置文件
echo.
echo [2/4] 检查配置文件...
if exist "%INSTALL_DIR%config.local.json" (
    echo [OK] config.local.json 存在
) else (
    echo [失败] config.local.json 不存在
    echo        请手动创建配置文件 config.local.json。
    pause
    exit /b 1
)

:: 检查思源连接
echo.
echo [3/4] 检查思源连接...
python -m source_code doctor
if errorlevel 1 (
    echo [失败] 思源连接检查未通过
    echo.
    echo 请确认：
    echo   1. 思源笔记正在运行
    echo   2. Token 正确（设置 → 关于 → API Token）
    echo   3. 思源笔记正在运行且端口正确（默认 6806）
) else (
    echo [OK] 思源连接正常
)

:: 检查 MCP 启动脚本
echo.
echo [4/4] 检查 MCP 启动脚本...
set "RUN_MCP=%INSTALL_DIR%scripts\run_mcp.py"
if exist "%RUN_MCP%" (
    echo [OK] run_mcp.py 存在
) else (
    echo [失败] run_mcp.py 不存在: %RUN_MCP%
)

:: 总结
echo.
echo ================================================
echo   诊断完成
echo ================================================
echo.
echo MCP 注册路径：
echo   %RUN_MCP%
echo.
echo 如果所有检查通过，请确保：
echo   1. MCP 已注册到你的 AI 客户端
echo      （参考 mcp_configs\ 目录中的配置模板）
echo   2. AI 客户端已重启
echo.
echo 使用方式：对 AI 说"帮我查一下笔记"
echo.

pause
