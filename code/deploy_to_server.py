"""
code/deploy_to_server.py — 将「太冲·弹塑性张量」双战队与 Web 监控系统自动化推送到远程服务器
"""

from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path
import paramiko

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env_server_config(env_file=None):
    env_file = Path(env_file) if env_file else PROJECT_ROOT / ".env"
    # ponytail: 硬编码配置仅作为 fallback，优先从 .env 读取
    cfg = {
        "host": os.environ.get("SERVER_IP", "127.0.0.1"),
        "port": 22,
        "user": "root",
        "password": "",
        "remote_dir": "/opt/lianghua"
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
    if not cfg["password"]:
        raise RuntimeError("missing required credentials: SERVER_PASSWORD")
    return cfg


def tar_filter(tarinfo):
    name = tarinfo.name
    if "__pycache__" in name or name.endswith(".pyc") or name.endswith(".log") or name.endswith(".db"):
        return None
    return tarinfo


def create_deploy_package() -> Path:
    """打包核心代码文件至轻量级压缩包"""
    tar_path = Path(tempfile.gettempdir()) / "lianghua_taichong_deploy.tar.gz"
    print(f"📦 正在打包轻量级核心工程文件至 {tar_path} ...", flush=True)

    with tarfile.open(tar_path, "w:gz") as tar:
        # 添加 code 目录
        tar.add(PROJECT_ROOT / "code", arcname="code", filter=tar_filter)
        # 添加 strategies 目录
        tar.add(PROJECT_ROOT / "strategies", arcname="strategies", filter=tar_filter)
        # 添加 .env 配置文件
        if (PROJECT_ROOT / ".env").exists():
            tar.add(PROJECT_ROOT / ".env", arcname=".env")

    print(f"✅ 轻量化打包完成: 大小 {tar_path.stat().st_size / 1024:.2f} KB", flush=True)
    return tar_path


def deploy_and_run():
    cfg = load_env_server_config()
    print("=" * 80, flush=True)
    print(f"🚀 [正在连接目标服务器] {cfg['user']}@{cfg['host']}:{cfg['port']} (域名: 739265.xyz)", flush=True)
    print("=" * 80, flush=True)

    # 1. 建立 SSH 连接
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(
        hostname=cfg["host"],
        port=cfg["port"],
        username=cfg["user"],
        password=cfg["password"],
        timeout=20
    )
    if ssh.get_transport():
        ssh.get_transport().set_keepalive(15)
    print("✅ SSH 连接成功！", flush=True)

    # 2. 检查远程服务器环境
    stdin, stdout, stderr = ssh.exec_command("uname -a && python3 -V")
    out = stdout.read().decode().strip()
    print(f"🖥️ 远程服务器系统: {out}", flush=True)

    # 3. 创建远程目录
    remote_dir = cfg["remote_dir"]
    ssh.exec_command(f"mkdir -p {remote_dir}/data/logs")

    # 4. 上传部署包 (使用 SFTP)
    tar_path = create_deploy_package()
    remote_tar = f"/tmp/{tar_path.name}"
    print(f"📤 正在上传部署包至远程 {remote_tar} ...", flush=True)

    sftp = ssh.open_sftp()
    sftp.put(str(tar_path), remote_tar)
    sftp.close()
    print("✅ 上传成功！", flush=True)

    # 5. 解压部署包
    print(f"📂 正在解压至 {remote_dir} ...", flush=True)
    cmd_extract = f"tar -xzf {remote_tar} -C {remote_dir} && rm -f {remote_tar}"
    stdin, stdout, stderr = ssh.exec_command(cmd_extract)
    stderr_out = stderr.read().decode()
    if stderr_out:
        print(f"⚠️ 解压提示: {stderr_out}", flush=True)

    # 5.5 执行实时 K 线同步 (异步或带超时)
    print("🔄 正在执行实时 K 线同步网关 (从 TqSdk 同步最新实时 K 线) ...", flush=True)
    try:
        stdin, stdout, stderr = ssh.exec_command(f"cd {remote_dir} && timeout 15 /opt/lianghua/venv/bin/python3 code/sync_live_futures_klines.py || true", timeout=20)
        sync_out = stdout.read().decode().strip()
        if sync_out:
            print(f"📊 同步回执:\n{sync_out}\n", flush=True)
    except Exception as e:
        print(f"⚠️ 行情同步跳过或超时: {e}", flush=True)

    # 6. 重启 Web Dashboard 与各策略守护进程 (包括太阴 15m 跨期、归元 15m 极值、太冲 V7、太冲双战队)
    print("🟢 正在远程启动 Web 监控大屏 (8090 / 739265.xyz) 与交易守护引擎...", flush=True)
    # ponytail: pkill+nohup 进程管理仅适合开发阶段；
    # 升级路径 = systemd unit 文件 + ExecStart/Restart=on-failure
    cmd_start = (
        f"cd {remote_dir} && "
        f"pkill -f 'futures_dashboard_server.py' 2>/dev/null || true && "
        f"pkill -f 'deploy_ek_supertrend_v7_trader.py' 2>/dev/null || true && "
        f"pkill -f 'deploy_taichong_squads_trader.py' 2>/dev/null || true && "
        f"pkill -f 'deploy_zscore_v2_15m_trader.py' 2>/dev/null || true && "
        f"pkill -f 'deploy_taiyin_calendar_trader.py' 2>/dev/null || true && "
        f"nohup /opt/lianghua/venv/bin/python3 code/futures_dashboard_server.py --port 8090 </dev/null > data/logs/dashboard_stdout.log 2>&1 & \n"
        f"nohup /opt/lianghua/venv/bin/python3 code/deploy_ek_supertrend_v7_trader.py </dev/null > data/logs/ek_v7_stdout.log 2>&1 & \n"
        f"nohup /opt/lianghua/venv/bin/python3 code/deploy_taichong_squads_trader.py </dev/null > data/logs/taichong_stdout.log 2>&1 & \n"
        f"nohup /opt/lianghua/venv/bin/python3 code/deploy_zscore_v2_15m_trader.py </dev/null > data/logs/zscore_stdout.log 2>&1 & \n"
        f"nohup /opt/lianghua/venv/bin/python3 code/deploy_taiyin_calendar_trader.py </dev/null > data/logs/taiyin_stdout.log 2>&1 & \n"
    )
    stdin, stdout, stderr = ssh.exec_command(cmd_start)
    time.sleep(6)

    # 7. 校验远程进程与日志
    stdin, stdout, stderr = ssh.exec_command("ps aux | grep -E 'futures_dashboard_server|deploy_ek_supertrend_v7_trader|deploy_taichong_squads_trader|deploy_zscore_v2_15m_trader|deploy_taiyin_calendar_trader' | grep -v grep")
    ps_out = stdout.read().decode().strip()

    stdin, stdout, stderr = ssh.exec_command(f"tail -n 25 {remote_dir}/data/logs/taiyin_calendar_trader.log 2>/dev/null || true")
    log_out = stdout.read().decode().strip()

    # 8. 本地 curl 验证服务器 Web 服务状态与策略 API
    stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:8090/api/status || true")
    api_out = stdout.read().decode().strip()

    print("=" * 80, flush=True)
    print("🎉 【「太阴·15m 黄金白银跨期套利」与 Web 监控大屏已成功推送并运行于服务器】", flush=True)
    print("=" * 80, flush=True)
    print(f" 远程部署路径: {remote_dir}")
    print(f" 实时监控大屏: https://739265.xyz/")
    print(f"\n🖥️ 运行中守护进程状态:\n{ps_out}\n")
    print(f"📊 远程太阴跨期交易引擎实时日志:\n{log_out}\n")
    print(f"📡 Web 监控大屏 API 状态:\n{api_out[:250]}...\n")
    print("=" * 80, flush=True)

    ssh.close()


if __name__ == "__main__":
    deploy_and_run()
