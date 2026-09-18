"""
fix_and_restore_production.py — 彻底修复生产环境并完整恢复所有量化策略与大屏服务
"""

import os
import paramiko
from scp import SCPClient
import time
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def fix_server(env_file=None):
    print("=" * 80)
    print("🚀 [正在连接生产服务器]")
    print("=" * 80)

    # 从 .env 读取服务器连接配置
    server_ip = os.environ.get("SERVER_IP", "127.0.0.1")
    server_pwd = ""
    env_file = Path(env_file) if env_file else PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("SERVER_IP="):
                    server_ip = line.split("=", 1)[1].strip()
                elif line.startswith("SERVER_PASSWORD="):
                    server_pwd = line.split("=", 1)[1].strip()
    if not server_pwd:
        raise RuntimeError("missing required credentials: SERVER_PASSWORD")

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(server_ip, 22, 'root', server_pwd, timeout=20)

    # 1. 确保远程目录存在
    ssh.exec_command("mkdir -p /opt/lianghua/code /opt/lianghua/data/logs")

    # 2. 将本地最新的代码与实时数据库同步到 /opt/lianghua (真实生产环境)
    print("📦 正在同步代码、行情守护引擎与最新数据库至 /opt/lianghua ...")
    with SCPClient(ssh.get_transport()) as scp:
        scp.put(str(PROJECT_ROOT / "code/futures_dashboard_server.py"), "/opt/lianghua/code/futures_dashboard_server.py")
        scp.put(str(PROJECT_ROOT / "code/realtime_market_daemon.py"), "/opt/lianghua/code/realtime_market_daemon.py")
        scp.put(str(PROJECT_ROOT / "code/fetch_tqsdk_multi_timeframe_history.py"), "/opt/lianghua/code/fetch_tqsdk_multi_timeframe_history.py")
        scp.put(str(PROJECT_ROOT / "code/run_simnow_paper_trader.py"), "/opt/lianghua/code/run_simnow_paper_trader.py")
        scp.put(str(PROJECT_ROOT / "code/vnpy_data_adapter.py"), "/opt/lianghua/code/vnpy_data_adapter.py")
        scp.put(str(PROJECT_ROOT / "code/vnpy_strategy_template.py"), "/opt/lianghua/code/vnpy_strategy_template.py")
        scp.put(str(PROJECT_ROOT / "code/vnpy_backtest_runner.py"), "/opt/lianghua/code/vnpy_backtest_runner.py")
        scp.put(str(PROJECT_ROOT / "code/deploy_vnpy_paper_trader.py"), "/opt/lianghua/code/deploy_vnpy_paper_trader.py")
        scp.put(str(PROJECT_ROOT / ".env"), "/opt/lianghua/.env")
        scp.put(str(PROJECT_ROOT / "nginx_739265_dashboard.conf"), "/etc/nginx/sites-available/lianghua-dashboard")
        
        # 同步最新的数据库
        db_file = PROJECT_ROOT / "data/ashare_quant.db"
        if db_file.exists():
            print(f"  ├─ 正在传输最新 SQLite 数据库 (大小: {db_file.stat().st_size / 1024 / 1024:.2f} MB)...")
            scp.put(str(db_file), "/opt/lianghua/data/ashare_quant.db")

    # 3. 检查 /opt/lianghua/venv 依赖
    print("🔧 检查并安装 /opt/lianghua/venv 依赖 (tqsdk, flask, psutil, pandas, numpy, lightgbm)...")
    stdin, stdout, stderr = ssh.exec_command("/opt/lianghua/venv/bin/pip install --upgrade tqsdk flask psutil pandas numpy lightgbm")
    print(stdout.read().decode())

    # 4. 配置标准 systemd 服务
    print("⚙️ 配置生产 systemd 服务...")
    
    # 4.1 实时行情与 K 线入库守护服务
    market_service = """[Unit]
Description=Futures Realtime Market Ingestion Daemon
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/lianghua
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/lianghua/venv/bin/python3 /opt/lianghua/code/realtime_market_daemon.py
Restart=always
RestartSec=5
StandardOutput=append:/opt/lianghua/data/logs/market_daemon.log
StandardError=append:/opt/lianghua/data/logs/market_daemon.log

[Install]
WantedBy=multi-user.target
"""

    # 4.2 Web 监控大屏服务
    futures_service = """[Unit]
Description=Futures Live Trading Web Dashboard Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/lianghua
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/lianghua/venv/bin/python3 /opt/lianghua/code/futures_dashboard_server.py
Restart=always
RestartSec=5
StandardOutput=append:/opt/lianghua/data/logs/dashboard_stdout.log
StandardError=append:/opt/lianghua/data/logs/dashboard_stdout.log

[Install]
WantedBy=multi-user.target
"""

    # 4.3 虚拟盘/仿真交易守护服务
    vnpy_service = """[Unit]
Description=VNPY SimNow Paper Trading Daemon
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/lianghua
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/lianghua/venv/bin/python3 /opt/lianghua/code/run_simnow_paper_trader.py --symbol ag2612.SHFE --strategy tianji
Restart=always
RestartSec=5
StandardOutput=append:/opt/lianghua/data/logs/simnow_daemon_stdout.log
StandardError=append:/opt/lianghua/data/logs/simnow_daemon_stdout.log

[Install]
WantedBy=multi-user.target
"""
    sftp = ssh.open_sftp()
    with sftp.open("/etc/systemd/system/futures_market_daemon.service", "w") as f:
        f.write(market_service)
    with sftp.open("/etc/systemd/system/futures_dashboard.service", "w") as f:
        f.write(futures_service)
    with sftp.open("/etc/systemd/system/vnpy-simnow.service", "w") as f:
        f.write(vnpy_service)
    sftp.close()

    # 5. 重启并测试所有服务
    print("🚀 正在重启 Nginx、行情守护、Dashboard 及虚拟盘交易服务...")
    ssh.exec_command("systemctl daemon-reload && systemctl enable futures_market_daemon futures_dashboard vnpy-simnow && systemctl restart futures_market_daemon futures_dashboard vnpy-simnow nginx")
    time.sleep(5)

    # 6. 验证服务状态
    stdin, stdout, stderr = ssh.exec_command("systemctl is-active futures_market_daemon futures_dashboard vnpy-simnow nginx")
    print("服务运行状态:\n", stdout.read().decode())

    # 7. 测试各 API 端点响应
    endpoints = [
        "https://739265.xyz/api/strategies",
        "https://739265.xyz/api/status?strategy=vnpy_simnow",
        "https://739265.xyz/api/status?strategy=zscore_v2_15m",
        "https://739265.xyz/api/kline?symbol=AG_IDX&strategy=vnpy_simnow",
        "https://739265.xyz/api/kline?symbol=AG_IDX&strategy=zscore_v2_15m",
        "https://739265.xyz/api/logs?strategy=vnpy_simnow",
    ]

    for ep in endpoints:
        stdin, stdout, stderr = ssh.exec_command(f"curl -s -k '{ep}'")
        res = stdout.read().decode()
        status_ok = "✅ 正常" if len(res) > 20 and "500" not in res and "error" not in res.lower() else "❌ 异常"
        print(f"{status_ok} -> {ep[:55]}... (返回字节: {len(res)})")

    # 8. 校验最新 K 线的具体时间戳
    print("\n🔍 正在抽检 AG_IDX (白银) 最新 K 线时间序列:")
    stdin, stdout, stderr = ssh.exec_command("curl -s -k 'https://739265.xyz/api/kline?symbol=AG_IDX&strategy=vnpy_simnow'")
    kline_raw = stdout.read().decode()
    try:
        k_json = json.loads(kline_raw)
        recent_cats = k_json.get("categories", [])[-5:]
        print(f"  📊 白银最近 5 根 K 线时间: {recent_cats}")
    except Exception as e:
        print(f"  ❌ 解析失败: {e}, 响应前 200 字: {kline_raw[:200]}")

    ssh.close()
    print("=" * 80)
    print("🎉 【生产环境修复、实时行情守护与全服务恢复完毕】")
    print("=" * 80)

if __name__ == "__main__":
    fix_server()
