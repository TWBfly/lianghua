"""
A-Share 3D Quant Web UI Server (A 股三维一体量化 Web UI 后端服务)
基于 Flask 搭建轻量级 API 与 Web 服务
访问地址: http://127.0.0.1:5050
"""

import os
import sys
import math
import re
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory

sys.path.append(os.path.dirname(__file__))
from backtest_kline_engine import KLineBacktestEngine, DB_PATH
from deepseek_analyzer import save_api_key_to_env
import deepseek_analyzer as _ds_mod

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")
kline_engine = KLineBacktestEngine(db_path=DB_PATH)
SYMBOL_RE = re.compile(r"^\d{6}$")


def validate_backtest_request(data, portfolio=False):
    data = data or {}
    start_date = str(data.get("start_date", "2024-01-01"))
    end_date = str(data.get("end_date", "2026-07-29"))
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("日期必须使用 YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")

    default_capital = 200000.0 if portfolio else 1000000.0
    try:
        initial_capital = float(
            data.get("initial_capital", default_capital)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("初始资金必须是数字") from exc
    if not math.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("初始资金必须是有限正数")

    result = {
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
    }
    if portfolio:
        symbols = data.get("symbols")
        if symbols is not None:
            if not isinstance(symbols, list) or len(symbols) > 20:
                raise ValueError("symbols 必须是最多20项的列表")
            if any(
                not isinstance(symbol, str)
                or not SYMBOL_RE.fullmatch(symbol)
                for symbol in symbols
            ):
                raise ValueError("股票代码必须是6位数字")
        result["symbols"] = symbols
    else:
        symbol = str(data.get("symbol", "603986"))
        if not SYMBOL_RE.fullmatch(symbol):
            raise ValueError("股票代码必须是6位数字")
        result["symbol"] = symbol
    return result


@app.route("/")
def index():
    """提供前端主页"""
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    """提供静态文件 (style.css, app.js 等)"""
    return send_from_directory(WEB_DIR, path)


@app.route("/api/run_backtest", methods=["POST"])
def run_backtest():
    """根据前端发送的股票与日期参数执行 K 线回测并返回 buy/sell 标记与理由"""
    try:
        params = validate_backtest_request(request.json or {})

        print(
            f"[Web Server] 接收到回测请求: 股票={params['symbol']}, "
            f"起始={params['start_date']}, 结束={params['end_date']}"
        )
        res = kline_engine.run_kline_backtest(
            **params
        )
        return jsonify(res)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"[Web Server Error] 回测失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/search_stocks", methods=["GET"])
def search_stocks():
    """根据代码或名称模糊搜索 A 股 5,884 只股票"""
    import pandas as pd
    query = request.args.get("q", "").strip()
    try:
        with kline_engine.get_connection() as conn:
            if not query:
                sql = "SELECT symbol, name, price, pe_ttm FROM stock_basic ORDER BY total_mv DESC LIMIT 20;"
                df = pd.read_sql_query(sql, conn)
            else:
                sql = "SELECT symbol, name, price, pe_ttm FROM stock_basic WHERE symbol LIKE ? OR name LIKE ? ORDER BY total_mv DESC LIMIT 20;"
                df = pd.read_sql_query(sql, conn, params=(f"%{query}%", f"%{query}%"))
                
        records = df.to_dict(orient="records")
        return jsonify(records)
    except Exception:
        return jsonify([]), 500


@app.route("/api/munger_stocks", methods=["GET"])
def get_munger_stocks():
    """获取符合查理·芒格五维选股标准的优秀股票池"""
    import pandas as pd
    query = request.args.get("q", "").strip()
    try:
        with kline_engine.get_connection() as conn:
            if not query:
                sql = """
                SELECT symbol, name, price, pe_ttm, pb, total_mv,
                       ROUND(pb / pe_ttm * 100, 2) as roe_est
                FROM stock_basic 
                WHERE pe_ttm > 0 AND pe_ttm <= 60 AND pb > 0 AND total_mv >= 10000000000 
                  AND name NOT LIKE '%ST%' AND name NOT LIKE '%退%'
                ORDER BY roe_est DESC LIMIT 50;
                """
                df = pd.read_sql_query(sql, conn)
            else:
                sql = """
                SELECT symbol, name, price, pe_ttm, pb, total_mv,
                       ROUND(pb / pe_ttm * 100, 2) as roe_est
                FROM stock_basic 
                WHERE pe_ttm > 0 AND pe_ttm <= 60 AND pb > 0 AND total_mv >= 10000000000 
                  AND name NOT LIKE '%ST%' AND name NOT LIKE '%退%'
                  AND (symbol LIKE ? OR name LIKE ?)
                ORDER BY roe_est DESC LIMIT 50;
                """
                df = pd.read_sql_query(sql, conn, params=(f"%{query}%", f"%{query}%"))
        
        records = df.to_dict(orient="records")
        return jsonify(records)
    except Exception as e:
        print("Munger API Error:", e)
        return jsonify([]), 500


@app.route("/api/run_portfolio_backtest", methods=["POST"])
def run_portfolio_backtest():
    """根据输入的初始本金 (如 200,000 元) 执行多股资产全组合回测与凯利公式资金分配"""
    try:
        params = validate_backtest_request(
            request.json or {}, portfolio=True
        )

        print(
            "[Web Server] 接收到统一组合回测请求: "
            f"本金=¥{params['initial_capital']:,.2f}"
        )
        res = kline_engine.run_portfolio_backtest(**params)
        return jsonify(res)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"[Portfolio Backtest Error]: {e}")
        return jsonify({"error": str(e)}), 500



@app.route("/api/set_api_key", methods=["POST"])
def set_api_key():
    """保存 DeepSeek API Key 到本地 .env 文件（无需重启服务器）"""
    data = request.json or {}
    key = (data.get("api_key") or "").strip()
    if not key or not key.startswith("sk-"):
        return jsonify({"error": "API Key 格式不正确，应以 sk- 开头"}), 400
    save_api_key_to_env(key)
    return jsonify({"ok": True, "message": f"DeepSeek API Key 已保存并生效 (key={key[:8]}...)"})


@app.route("/api/check_api_key", methods=["GET"])
def check_api_key():
    """检查当前 DeepSeek API Key 配置状态"""
    key = _ds_mod.DEEPSEEK_API_KEY or os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return jsonify({"configured": True, "key_prefix": key[:8] + "..."})
    return jsonify({"configured": False, "key_prefix": ""})


@app.route("/api/sync_data", methods=["POST"])
def sync_data():
    """手动一键更新与同步股票最新 K 线及基本面数据至本地 SQLite 数据库"""
    try:
        data = request.json or {}
        symbol = data.get("symbol", "600519").strip()
        print(f"[Web Server 🔄] 手动触发数据同步: 目标股票={symbol}")
        
        # 增量同步日线 K 线至本地 SQLite 数据库
        kline_engine.data_engine.sync_stock_daily(symbols=[symbol])
        
        return jsonify({
            "ok": True,
            "message": f"股票 [{symbol}] 最新日线 K 线与基本面数据已成功更新并持久化至本地 SQLite 数据库！"
        })
    except Exception as e:
        print(f"[Web Server Error] 同步数据失败: {e}")
        return jsonify({"error": f"同步失败: {str(e)}"}), 500


if __name__ == "__main__":
    port = 5050
    print("\n" + "="*70)
    print("🚀 A 股三维一体量化 Web UI 服务成功启动!")
    print(f"🌐 访问地址: http://127.0.0.1:{port}")
    print("="*70 + "\n")
    app.run(host="127.0.0.1", port=port, debug=False)
