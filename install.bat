@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ================================================
echo   SiYuan Agent Bridge — 安装脚本
echo ================================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python。请先安装 Python 3.11+ 并添加到 PATH。
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [OK] Python %%v

:: 确定安装目录
set "DEFAULT_DIR=%LOCALAPPDATA%\siyuan-agent-bridge"
echo.
echo 默认安装目录: %DEFAULT_DIR%
set /p INSTALL_DIR="输入安装目录（直接回车使用默认）: "
if "!INSTALL_DIR!"=="" set "INSTALL_DIR=%DEFAULT_DIR%"

if exist "!INSTALL_DIR!" (
    echo.
    echo [警告] 目录已存在: !INSTALL_DIR!
    set /p OVERWRITE="是否覆盖安装？(y/n): "
    if /i not "!OVERWRITE!"=="y" (
        echo 取消安装。
        pause
        exit /b 0
    )
)

:: 复制文件
echo.
echo 正在复制文件到 !INSTALL_DIR! ...
if not exist "!INSTALL_DIR!" mkdir "!INSTALL_DIR!"

:: 使用 robocopy 复制，排除不需要的目录
robocopy "%cd%" "!INSTALL_DIR!" /E /NFL /NDL /NP /XF "config.local.json" ".gitignore" ".gitattributes" /XD ".git" "__pycache__" ".pytest_cache" ".test_tmp" "tests" "dist" "knowledge_base" "ai_workspace" ".codebuddy" >nul
if errorlevel 8 (
    echo [错误] 文件复制失败。
    pause
    exit /b 1
)
echo [OK] 文件复制完成

:: 收集工作空间信息
echo.
echo --------------------------------------------------
echo   思源工作空间配置
echo --------------------------------------------------
echo.
set /p WS_NAME="工作空间名称（默认: 主工作空间）: "
if "!WS_NAME!"=="" set "WS_NAME=主工作空间"

set /p WS_PORT="思源端口（默认: 6806）: "
if "!WS_PORT!"=="" set "WS_PORT=6806"

set /p WS_TOKEN="思源 API Token（在思源 → 设置 → 关于 中复制）: "
if "!WS_TOKEN!"=="" (
    echo [错误] Token 不能为空。
    pause
    exit /b 1
)

:: 写入 config.local.json
echo.
echo 正在创建配置文件...
(
    echo {
    echo   "profiles": [
    echo     {
    echo       "name": "!WS_NAME!",
    echo       "token": "!WS_TOKEN!"
    echo     }
    echo   ],
    echo   "language": "zh-CN"
    echo }
) > "!INSTALL_DIR!\config.local.json"
echo [OK] 配置文件已创建: !INSTALL_DIR!\config.local.json

:: 运行诊断
echo.
echo --------------------------------------------------
echo   运行诊断...
echo --------------------------------------------------
cd /d "!INSTALL_DIR!"
python -m source_code doctor
if errorlevel 1 (
    echo.
    echo [警告] 诊断未全部通过。请检查：
    echo         1. 思源笔记是否正在运行
    echo         2. Token 是否正确（设置 → 关于 → API Token）
    echo         3. 端口是否为 !WS_PORT!
) else (
    echo.
    echo [OK] 思源连接正常！
)

:: 完成
echo.
echo ================================================
echo   安装完成！
echo ================================================
echo.
echo 安装目录: !INSTALL_DIR!
echo.
echo 下一步：
echo   1. 注册 MCP 到你的 AI 客户端（参考 mcp_configs\ 目录中的模板）
echo   2. 重启 AI 客户端
echo   3. 对 AI 说"帮我查一下笔记里的内容"
echo.
echo 如果遇到问题，运行 doctor.bat 进行诊断。
echo.
echo 重要安全提醒：
echo   config.local.json 包含你的思源 API Token。
echo   请不要分享或上传该文件。
echo.

pause
endlocal
