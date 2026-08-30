"""
A-Share 3D Quant Web UI Server (A 股三维一体量化 Web UI 后端服务)
基于 Flask 搭建轻量级 API 与 Web 服务
访问地址: http://127.0.0.1:5050
"""

import os
import sys
import math
import re
import hmac
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory

sys.path.append(os.path.dirname(__file__))
from backtest_kline_engine import (
    BACKTEST_MODES,
    DB_PATH,
    EXECUTABLE_STRATEGIES,
    KLineBacktestEngine,
)
from munger_dalio_ai_screener import MungerDalioAIScreener

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")
kline_engine = KLineBacktestEngine(db_path=DB_PATH)
md_screener = MungerDalioAIScreener(db_path=DB_PATH)
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
    backtest_mode = str(data.get("backtest_mode", "STRICT")).upper()
    if backtest_mode not in BACKTEST_MODES:
        raise ValueError("回测模式必须是 STRICT 或 RESEARCH_PROXY")
    result["backtest_mode"] = backtest_mode
    strategy = str(data.get("strategy", "causal_ml"))


    if strategy not in EXECUTABLE_STRATEGIES:
        raise ValueError(f"策略不可执行: {strategy}")
    result["strategy"] = strategy
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
        symbol = str(data.get("symbol", "600519"))

        if not SYMBOL_RE.fullmatch(symbol):
            raise ValueError("股票代码必须是6位数字")
        result["symbol"] = symbol
    return result


@app.route("/")
def index():
    """提供前端主页"""
    return send_from_directory(WEB_DIR, "index.html")


from strategy_hot_plugger import hot_plugger

@app.route("/api/strategies", methods=["GET"])
def strategies():
    """返回全量内置与热插拔策略清单及元数据"""
    return jsonify(hot_plugger.list_strategies())


@app.route("/api/register_strategy", methods=["POST"])
def register_strategy():
    """Remote Python execution is intentionally disabled."""
    return jsonify({
        "error": "远程策略代码注册已禁用",
        "error_code": "REMOTE_STRATEGY_REGISTRATION_DISABLED",
    }), 403



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
    """Return a current valuation snapshot, not a fundamental audit."""
    import pandas as pd
    query = request.args.get("q", "").strip()
    try:
        with kline_engine.get_connection() as conn:
            if not query:
                sql = """
                SELECT symbol, name, price, pe_ttm, pb, total_mv,
                       'UNKNOWN' AS fundamental_status,
                       'CURRENT_VALUATION_SNAPSHOT' AS data_scope
                FROM stock_basic 
                WHERE pe_ttm > 0 AND pe_ttm <= 60 AND pb > 0 AND total_mv >= 10000000000 
                  AND name NOT LIKE '%ST%' AND name NOT LIKE '%退%'
                ORDER BY total_mv DESC LIMIT 50;
                """
                df = pd.read_sql_query(sql, conn)
            else:
                sql = """
                SELECT symbol, name, price, pe_ttm, pb, total_mv,
                       'UNKNOWN' AS fundamental_status,
                       'CURRENT_VALUATION_SNAPSHOT' AS data_scope
                FROM stock_basic 
                WHERE pe_ttm > 0 AND pe_ttm <= 60 AND pb > 0 AND total_mv >= 10000000000 
                  AND name NOT LIKE '%ST%' AND name NOT LIKE '%退%'
                  AND (symbol LIKE ? OR name LIKE ?)
                ORDER BY total_mv DESC LIMIT 50;
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



@app.route("/api/sync_data", methods=["POST"])
def sync_data():
    """Synchronize daily bars through an authenticated admin route."""
    expected_token = os.environ.get("LIANGHUA_ADMIN_TOKEN", "")
    if not expected_token:
        return jsonify({
            "ok": False,
            "error": "管理员认证未配置",
            "error_code": "ADMIN_AUTH_NOT_CONFIGURED",
        }), 503
    authorization = request.headers.get("Authorization", "")
    supplied_token = (
        authorization[7:] if authorization.startswith("Bearer ") else ""
    )
    if not hmac.compare_digest(supplied_token, expected_token):
        return jsonify({
            "ok": False,
            "error": "未授权",
            "error_code": "UNAUTHORIZED",
        }), 401
    try:
        data = request.json or {}
        symbol = data.get("symbol", "600519")
        if not isinstance(symbol, str) or not SYMBOL_RE.fullmatch(symbol):
            return jsonify({"ok": False, "error": "股票代码必须是6位数字"}), 400
        summary = kline_engine.data_engine.sync_stock_daily(
            symbols=[symbol]
        )
        completed = summary["committed"] + summary["unchanged"]
        problems = summary["empty"] + summary["failed"]
        ok = bool(completed) and not problems
        status = 200 if ok else (207 if completed else 502)
        payload = {
            "ok": ok,
            "summary": summary,
            "message": (
                f"股票 [{symbol}] 日线数据已提交或确认无变化"
                if ok else "日线数据未完整同步"
            ),
        }
        if not ok:
            payload["error"] = payload["message"]
        return jsonify(payload), status
    except Exception as e:
        print(f"[Web Server Error] 同步数据失败: {e}")
        return jsonify({"error": f"同步失败: {str(e)}"}), 500


@app.route("/api/ai_financial_audit", methods=["GET"])
def get_ai_financial_audit():
    symbol = request.args.get("symbol", "600519").strip()
    name = request.args.get("name", "贵州茅台").strip()
    try:
        res = md_screener.audit_financial_with_ai(symbol=symbol, name=name)
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route(
    "/api/<path:unused>",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)

def api_not_found(unused):
    return jsonify({"error": "API endpoint not found"}), 404


if __name__ == "__main__":
    port = 5050
    print("\n" + "="*70)
    print("A 股策略回测 Web 服务已启动")
    print(f"🌐 访问地址: http://127.0.0.1:{port}")
    print("="*70 + "\n")
    app.run(host="127.0.0.1", port=port, debug=False)
