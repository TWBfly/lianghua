"""
deepseek_analyzer.py — 真正的 DeepSeek AI 公告分析器
功能：调用 DeepSeek API，对每次买入前的股票公告做真实 AI 风险审计
输出：结构化的 AI 研判理由字符串

ponytail: 单文件，复用 requests，结果缓存到 SQLite 避免重复调用（省 API 费用）
         ceiling: 仅做单次买入时分析，非实时流式；upgrade: 加 streaming 支持
"""
import os
import json
import hashlib
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime

# ─── 配置区 ───────────────────────────────────────────────────────────────────
# 方式1：直接在此处填写（不推荐上传到 git）
# 方式2：设置环境变量 DEEPSEEK_API_KEY
# 方式3：Web UI 页面上通过设置面板输入并存到本地 DB
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-v4-flash"
MAX_TOKENS = 300
CACHE_DB_PATH = os.path.join(os.path.dirname(__file__), "../data/deepseek_cache.db")

# 自动从 .env 加载 API Key（优先级: 环境变量 > .env 文件）
def _load_env_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(__file__), "../.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    k = line.split("=", 1)[1].strip()
                    if k:
                        os.environ["DEEPSEEK_API_KEY"] = k
                        return k
    return ""

DEEPSEEK_API_KEY = _load_env_key()


def _init_cache_db():
    """初始化 AI 分析结果缓存表"""
    with sqlite3.connect(CACHE_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_analysis_cache (
                cache_key TEXT PRIMARY KEY,
                symbol TEXT,
                analysis TEXT,
                created_at TEXT
            )
        """)
        conn.commit()


def _cache_key(symbol: str, notice_title: str, buy_date: str) -> str:
    """生成缓存 key（同股票 + 同公告标题 + 同买入日期 → 不重复调用）"""
    raw = f"{symbol}|{notice_title}|{buy_date}"
    return hashlib.md5(raw.encode()).hexdigest()


def analyze_notice_risk(
    symbol: str,
    stock_name: str,
    notice_title: str,
    buy_date: str,
    net_profit_yi: float,
    rsi: float,
    ml_score: float,
    api_key: str = ""
) -> str:
    """
    核心函数：调用 DeepSeek 对公告标题进行 AI 风险审计
    返回：格式化的 AI 研判理由字符串
    - 如果 API Key 未配置 → 返回明确的"未接入AI"提示（不再伪造结论）
    - 如果有缓存 → 直接返回缓存结果（节省 token）
    - 如果 API 调用失败 → 返回错误提示
    """
    _init_cache_db()
    effective_key = api_key or DEEPSEEK_API_KEY

    if not effective_key:
        return (
            f"【⚠️ AI未接入】DeepSeek API Key 未配置，无法进行真实 AI 风险审计。"
            f"当前仅凭技术指标决策：ML评分={ml_score:.1f}/10，RSI={rsi:.1f}。"
            f"建议在页面顶部设置面板填入 DeepSeek API Key 以启用 AI 维度。"
        )

    ckey = _cache_key(symbol, notice_title, buy_date)

    # 查缓存
    with sqlite3.connect(CACHE_DB_PATH) as conn:
        row = conn.execute(
            "SELECT analysis FROM ai_analysis_cache WHERE cache_key=?", (ckey,)
        ).fetchone()
    if row:
        return f"[AI缓存⚡] {row[0]}"

    # 构建 Prompt
    prompt = f"""你是A股专业合规风控分析师。请对以下信息进行简要风险审计，直接给出结论，不要废话：

股票：{stock_name}（{symbol}）
买入日期：{buy_date}
最新公告标题：《{notice_title}》
近期净利润：{net_profit_yi:.2f} 亿元
技术指标：RSI={rsi:.1f}，ML上涨概率评分={ml_score:.1f}/10

请完成：
1. 公告是否含有重大风险信号（立案调查/股东减持/业绩暴雷/债务危机）？
2. 基本面是否支撑买入？
3. 综合风险评级：低/中/高，并给出一句话买入理由或否决理由。

格式：【风险:低/中/高】结论一句话。"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.3,
        "stream": False
    }

    try:
        req = urllib.request.Request(
            f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {effective_key}"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        analysis = result["choices"][0]["message"]["content"].strip()

        # 存缓存
        with sqlite3.connect(CACHE_DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ai_analysis_cache VALUES (?, ?, ?, ?)",
                (ckey, symbol, analysis, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()

        return f"[DeepSeek AI 🤖] {analysis}"

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:200]
        return f"[DeepSeek API错误 {e.code}] {body}"
    except Exception as ex:
        return f"[DeepSeek 连接失败] {str(ex)[:100]}"


def save_api_key_to_env(api_key: str):
    """持久化 API Key 到本地 .env 文件（不提交 git）"""
    env_path = os.path.join(os.path.dirname(__file__), "../.env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = [l for l in f.readlines() if not l.startswith("DEEPSEEK_API_KEY=")]
    lines.append(f"DEEPSEEK_API_KEY={api_key}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)
    # 同步到当前进程环境变量
    os.environ["DEEPSEEK_API_KEY"] = api_key
    global DEEPSEEK_API_KEY
    DEEPSEEK_API_KEY = api_key
