"""
DeepSeek AI Key Quant Co-Pilot Module (大模型智能风控与投资委员会审计引擎)
负责接入 SenseNova / DeepSeek API (deepseek-v4-flash)
对机器学习 (LightGBM) 筛选出的 Top 候选股票进行基本面舆情、黑天鹅避雷与仓位分配终审
"""

import os
import json
import urllib.request
import pandas as pd

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")


class DeepSeekQuantCopilot:
    def __init__(self, env_path=ENV_PATH):
        self.env_path = env_path
        self.config = self._load_env()
        self.api_key = self.config.get("DEEPSEEK_API_KEY")
        self.base_url = self.config.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
        self.model = self.config.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

        if not self.api_key:
            print("[Warning] 未找到 DEEPSEEK_API_KEY，请检查 .env 文件。")

    def _load_env(self):
        config = {}
        if os.path.exists(self.env_path):
            with open(self.env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        config[k.strip()] = v.strip()
        return config

    def _call_api(self, prompt, system_prompt=None):
        """安全调用 SenseNova / DeepSeek API"""
        if not self.api_key:
            return None

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2048
        }

        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[DeepSeek API Error] 请求失败: {e}")
            return None

    def audit_top_stocks(self, top_stocks_df):
        """Fail closed until dated, source-identified documents are supplied."""
        columns = [
            "symbol", "name", "decision", "suggested_position_pct",
            "risk_level", "rationale",
        ]
        if top_stocks_df is None or top_stocks_df.empty:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame([{
            "symbol": str(row.get("symbol", "")),
            "name": str(row.get("name", row.get("symbol", ""))),
            "decision": "UNAVAILABLE",
            "suggested_position_pct": 0.0,
            "risk_level": "UNKNOWN",
            "rationale": "MISSING_GROUNDED_DOCUMENTS",
        } for _, row in top_stocks_df.iterrows()], columns=columns)


if __name__ == "__main__":
    copilot = DeepSeekQuantCopilot()

    # 模拟 ML 推荐输入
    demo_df = pd.DataFrame([
        {"symbol": "600519", "name": "贵州茅台", "price": 1320.0, "pe_ttm": 22.5, "predicted_5d_return_pct": 3.85},
        {"symbol": "000858", "name": "五粮液", "price": 128.5, "pe_ttm": 16.2, "predicted_5d_return_pct": 2.95},
        {"symbol": "300750", "name": "宁德时代", "price": 185.0, "pe_ttm": 24.1, "predicted_5d_return_pct": 4.12}
    ])

    copilot.audit_top_stocks(demo_df)
