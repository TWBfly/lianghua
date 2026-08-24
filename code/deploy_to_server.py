"""
deploy_to_server.py — 将 vn.py 虚拟盘交易引擎与策略自动化推送到远程服务器 (127.0.0.1 / 739265.xyz)
"""

from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import paramiko
from scp import SCPClient
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env_server_config():
    env_file = PROJECT_ROOT / ".env"
    cfg = {
        "host": "127.0.0.1",
        "port": 22,
        "user": "root",
        "password": "",
        "remote_dir": "/root/lianghua"
    }
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("SERVER_IP="):
                    cfg["host"] = line.split("=", 1)[1].strip()
                elif line.startswith("SERVER_PORT="):
                    cfg["port"] = int(line.split("=", 1)[1].strip())
                elif line.startswith("SERVER_USER="):
                    cfg["user"] = line.split("=", 1)[1].strip()
                elif line.startswith("SERVER_PASSWORD="):
                    cfg["password"] = line.split("=", 1)[1].strip()
    return cfg


def create_deploy_package() -> Path:
    """打包部署文件至临时压缩包"""
    tar_path = Path(tempfile.gettempdir()) / "lianghua_vnpy_deploy.tar.gz"
    print(f"📦 正在打包部署工程文件至 {tar_path} ...")

    with tarfile.open(tar_path, "w:gz") as tar:
        # 添加 code 目录
        tar.add(PROJECT_ROOT / "code", arcname="code")
        # 添加 strategies 目录
        tar.add(PROJECT_ROOT / "strategies", arcname="strategies")
        # 添加 vnpy 目录
        tar.add(PROJECT_ROOT / "vnpy", arcname="vnpy")
        # 添加 deploy_server_simnow.sh
        if (PROJECT_ROOT / "deploy_server_simnow.sh").exists():
            tar.add(PROJECT_ROOT / "deploy_server_simnow.sh", arcname="deploy_server_simnow.sh")
        # 添加 .env 配置文件
        if (PROJECT_ROOT / ".env").exists():
            tar.add(PROJECT_ROOT / ".env", arcname=".env")

    print(f"✅ 打包完成: 大小 {tar_path.stat().st_size / 1024 / 1024:.2f} MB")
    return tar_path


def deploy_and_run():
    cfg = load_env_server_config()
    print("=" * 80)
    print(f"🚀 [正在连接目标服务器] {cfg['user']}@{cfg['host']}:{cfg['port']}")
    print("=" * 80)

    # 1. 建立 SSH 连接
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=cfg["host"],
        port=cfg["port"],
        username=cfg["user"],
        password=cfg["password"],
        timeout=15
    )
    print("✅ SSH 连接成功！")

    # 2. 检查远程服务器环境
    stdin, stdout, stderr = ssh.exec_command("uname -a && python3 -V")
    out = stdout.read().decode().strip()
    print(f"🖥️ 远程服务器系统: {out}")

    # 3. 创建远程目录
    remote_dir = cfg["remote_dir"]
    ssh.exec_command(f"mkdir -p {remote_dir}/data/logs")

    # 4. 上传部署包
    tar_path = create_deploy_package()
    remote_tar = f"/tmp/{tar_path.name}"
    print(f"📤 正在上传部署包至远程 {remote_tar} ...")

    with SCPClient(ssh.get_transport()) as scp:
        scp.put(str(tar_path), remote_tar)
    print("✅ 上传成功！")

    # 5. 解压部署包
    print(f"📂 正在解压至 {remote_dir} ...")
    cmd_extract = f"tar -xzf {remote_tar} -C {remote_dir} && rm -f {remote_tar}"
    stdin, stdout, stderr = ssh.exec_command(cmd_extract)
    stderr_out = stderr.read().decode()
    if stderr_out:
        print(f"⚠️ 解压提示: {stderr_out}")

    # 6. 安装运行必要依赖（若无）
    print("🔧 检查并安装远程 Python 必要依赖 (pandas, numpy, etc.)...")
    ssh.exec_command("pip3 install --upgrade pip && pip3 install pandas numpy")

    # 7. 停止已有挂机进程并启动新的守护进程
    print("🟢 正在远程启动 SimNow 24h 虚拟盘挂机守护引擎...")
    cmd_start = (
        f"cd {remote_dir} && "
        f"chmod +x deploy_server_simnow.sh 2>/dev/null || true && "
        f"pkill -f 'run_simnow_paper_trader.py' 2>/dev/null || true && "
        f"nohup python3 code/run_simnow_paper_trader.py --symbol ag2612.SHFE --strategy tianji > data/logs/simnow_daemon_stdout.log 2>&1 &"
    )
    stdin, stdout, stderr = ssh.exec_command(cmd_start)
    import time
    time.sleep(3)

    # 8. 校验远程进程与日志
    stdin, stdout, stderr = ssh.exec_command("ps aux | grep 'run_simnow_paper_trader.py' | grep -v grep")
    ps_out = stdout.read().decode().strip()

    stdin, stdout, stderr = ssh.exec_command(f"tail -n 20 {remote_dir}/data/logs/vnpy_paper_trader.log 2>/dev/null || true")
    log_out = stdout.read().decode().strip()

    print("=" * 80)
    print("🎉 【服务器远程部署与挂机启动成功】")
    print("=" * 80)
    print(f" 远程部署路径: {remote_dir}")
    print(f" 挂机进程状态:\n{ps_out if ps_out else '进程正在启动中'}\n")
    print(f" 远程实时日志:\n{log_out}\n")
    print("=" * 80)

    ssh.close()


if __name__ == "__main__":
    deploy_and_run()
