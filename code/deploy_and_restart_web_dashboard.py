"""
code/deploy_and_restart_web_dashboard.py — 上传并重启 Web 监控大屏
"""

import os
import sys
import time
import paramiko
from pathlib import Path
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

env_config = dotenv_values(ENV_PATH)
SERVER_IP = env_config.get("SERVER_IP", "127.0.0.1")
SERVER_PORT = int(env_config.get("SERVER_PORT", 22))
SERVER_USER = env_config.get("SERVER_USER", "root")
SERVER_PASSWORD = env_config.get("SERVER_PASSWORD")

if not SERVER_PASSWORD:
    raise RuntimeError("missing required credentials: SERVER_PASSWORD")

REMOTE_OPT = "/opt/lianghua"

print(f"================================================================================")
print("🚀 Web 监控大屏云端部署重启")
print(f"================================================================================")

ssh = paramiko.SSHClient()
ssh.load_system_host_keys()
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

try:
    print(f"📡 正在连接云端服务器 {SERVER_USER}@{SERVER_IP}:{SERVER_PORT}...")
    ssh.connect(SERVER_IP, port=SERVER_PORT, username=SERVER_USER, password=SERVER_PASSWORD, timeout=15)
    sftp = ssh.open_sftp()
    print("✅ SSH & SFTP 已连接！")

    # 1. 同步文件
    files_to_sync = [
        "code/futures_dashboard_server.py",
    ]

    for rel_path in files_to_sync:
        local_f = PROJECT_ROOT / rel_path
        target_opt = f"{REMOTE_OPT}/{rel_path}"
        print(f"  ⬆️ 同步更新: {rel_path} -> {target_opt}")
        sftp.put(str(local_f), target_opt)

    # 2. 只重启 Web 大屏；禁用策略不能由部署器启动
    print("\n🔄 正在平滑重启 Web 大屏 Server (端口 8090 / 域名 739265.xyz)...")
    restart_cmd = f"""
    pkill -9 -f "futures_dashboard_server.py" || true
    sleep 1

    cd {REMOTE_OPT}
    nohup /opt/lianghua/venv/bin/python3 /opt/lianghua/code/futures_dashboard_server.py --port 8090 > /opt/lianghua/data/logs/dashboard_stdout.log 2>&1 < /dev/null &
    sleep 2

    ps aux | grep "futures_dashboard_server.py" | grep -v grep
    """

    stdin, stdout, stderr = ssh.exec_command(restart_cmd)
    out = stdout.read().decode("utf-8")
    print("\n" + "="*80)
    print("🖥️ 【服务器进程重启结果】:")
    print("="*80)
    print(out)
    print("="*80)

    # 3. 验证 HTTP 接口返回
    time.sleep(2)
    verify_cmd = "curl -s http://127.0.0.1:8090/api/status?strategy=taichong_dual_squad"
    stdin, stdout, stderr = ssh.exec_command(verify_cmd)
    api_res = stdout.read().decode("utf-8")
    print("\n📡 Web 大屏可用策略 API 验证:")
    print(api_res[:300] + ("..." if len(api_res) > 300 else ""))

    sftp.close()
    ssh.close()
    print("\nWeb 大屏部署完成；禁用策略未启动。")

except Exception as e:
    print(f"❌ 部署失败: {e}")
    sys.exit(1)
