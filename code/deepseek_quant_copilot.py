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
        """
        对 ML 模型推荐的 Top 股票列表进行大模型投资委员会 (Investment Committee) 审核
        """
        print(f"\n[AI Copilot] 正在通过 DeepSeek ({self.model}) 进行智能风控与多空终审...")

        stocks_summary = []
        for idx, row in top_stocks_df.iterrows():
            stocks_summary.append(
                f"- 代码: {row['symbol']}, 名称: {row['name']}, 最新价: {row['price']}元, "
                f"动态PE: {row['pe_ttm']}, ML预测5日收益率: {row['predicted_5d_return_pct']:.2f}%"
            )

        stocks_text = "\n".join(stocks_summary)

        system_prompt = (
            "你是一名严谨的 A 股资深量化风控专家与投资委员会主管。"
            "你的任务是对机器学习算法推荐的候选股票列表进行基本面避雷、研报评估与仓位终审。"
            "重点排查：立案调查、扣非大额亏损、大股东高比例减持、退市风险（*ST）。"
            "请严格以 JSON 格式输出分析结果。"
        )

        user_prompt = f"""
以下是机器学习多因子模型筛选出的当前最强反弹/领涨候选股票列表：

{stocks_text}

请对上述股票进行综合风险评估与投资审核，要求输出 JSON 格式，结构如下：
{{
  "audit_results": [
    {{
      "symbol": "股票代码",
      "name": "股票名称",
      "decision": "APPROVED (通过) / WATCH (观望) / REJECTED (拉黑)",
      "suggested_position_pct": 建议仓位百分比(如 15.0),
      "risk_level": "LOW / MEDIUM / HIGH",
      "rationale": "简短的量化风控理由 (50字以内)"
    }}
  ],
  "portfolio_summary": "整体组合策略建仓建议 (100字以内)"
}}
"""

        raw_response = self._call_api(user_prompt, system_prompt=system_prompt)
        if not raw_response:
            print("[AI Copilot] API 返回为空，回退至纯 ML 信号。")
            return top_stocks_df

        try:
            # 提取 JSON 内容
            json_str = raw_response
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0].strip()

            parsed = json.loads(json_str)
            audit_list = parsed.get("audit_results", [])
            audit_df = pd.DataFrame(audit_list)

            print("\n" + "="*70)
            print(f"DeepSeek AI 投资委员会终审结果 ({self.model}):")
            print("="*70)
            for item in audit_list:
                status_icon = "🟢" if item['decision'] == 'APPROVED' else ("🟡" if item['decision'] == 'WATCH' else "🔴")
                print(f"{status_icon} [{item['decision']}] {item['symbol']} ({item['name']}) | 建议仓位: {item['suggested_position_pct']}% | 风险: {item['risk_level']}")
                print(f"   └─ 理由: {item['rationale']}")

            print(f"\n💡 组合策略建议: {parsed.get('portfolio_summary', '')}")
            print("="*70)

            return audit_df

        except Exception as e:
            print(f"[AI Copilot] 完整 JSON 解析提示 ({e})，启动分块正则修复提取...")
            import re
            item_matches = re.findall(r'\{\s*"symbol"\s*:\s*"([^"]+)".*?"decision"\s*:\s*"([^"]+)".*?"suggested_position_pct"\s*:\s*([0-9\.]+).*?"risk_level"\s*:\s*"([^"]+)".*?"rationale"\s*:\s*"([^"]+)"', raw_response, re.DOTALL)
            
            if item_matches:
                audit_list = []
                for sym, dec, pos, risk, rat in item_matches:
                    audit_list.append({
                        "symbol": sym,
                        "name": sym,
                        "decision": dec,
                        "suggested_position_pct": float(pos),
                        "risk_level": risk,
                        "rationale": rat
                    })
                audit_df = pd.DataFrame(audit_list)
                print("\n" + "="*70)
                print(f"DeepSeek AI 投资委员会终审结果 (正则提取修复):")
                print("="*70)
                for item in audit_list:
                    status_icon = "🟢" if item['decision'] == 'APPROVED' else ("🟡" if item['decision'] == 'WATCH' else "🔴")
                    print(f"{status_icon} [{item['decision']}] {item['symbol']} | 建议仓位: {item['suggested_position_pct']}% | 风险: {item['risk_level']}")
                    print(f"   └─ 理由: {item['rationale']}")
                print("="*70)
                return audit_df

            return top_stocks_df


if __name__ == "__main__":
    copilot = DeepSeekQuantCopilot()

    # 模拟 ML 推荐输入
    demo_df = pd.DataFrame([
        {"symbol": "600519", "name": "贵州茅台", "price": 1320.0, "pe_ttm": 22.5, "predicted_5d_return_pct": 3.85},
        {"symbol": "000858", "name": "五粮液", "price": 128.5, "pe_ttm": 16.2, "predicted_5d_return_pct": 2.95},
        {"symbol": "300750", "name": "宁德时代", "price": 185.0, "pe_ttm": 24.1, "predicted_5d_return_pct": 4.12}
    ])

    copilot.audit_top_stocks(demo_df)
