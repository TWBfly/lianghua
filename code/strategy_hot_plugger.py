"""
strategy_hot_plugger.py — A 股策略热插拔与动态插件引擎

核心功能：
1. 自动监控与加载 `lianghua/strategies/*.py` 策略插件目录；
2. 支持运行时动态添加、编辑、重载新策略文件，无需重启 Web 服务器；
3. 无缝兼容内置策略库 `strategy_signal_library.py`；
4. 允许通过 API / Web UI 实时在线提交新的 Python 策略代码脚本。

ponytail: 利用 importlib.util 极简实现热插拔与沙盒加载，代码短小精悍。
"""
import ast
import os
import sys
import time
import importlib.util
import pandas as pd
from typing import Dict, Any, Callable, List

# 目录路径定义
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
STRATEGIES_DIR = os.path.join(BASE_DIR, "strategies")
os.makedirs(STRATEGIES_DIR, exist_ok=True)

sys.path.append(os.path.dirname(__file__))
from strategy_signal_library import SIGNAL_FUNCTIONS


FORBIDDEN_MODULES = {"os", "sys", "subprocess", "shutil", "socket", "http", "requests", "urllib", "importlib", "ctypes", "pickle"}
FORBIDDEN_BUILTINS = {"eval", "exec", "__import__", "compile", "breakpoint"}


def validate_strategy_code_ast(code_content: str) -> tuple[bool, str]:
    """使用 AST 校验策略代码，禁止危险模块与内建函数"""
    try:
        tree = ast.parse(code_content)
    except SyntaxError as e:
        return False, f"代码语法错误: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split('.')[0]
                if root_module in FORBIDDEN_MODULES:
                    return False, f"禁止导入受限模块: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_module = node.module.split('.')[0]
                if root_module in FORBIDDEN_MODULES:
                    return False, f"禁止导入受限模块: {node.module}"
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_BUILTINS or node.id in {"__builtins__", "__globals__"}:
                return False, f"禁止访问受限标识符: {node.id}"
        elif isinstance(node, ast.Attribute):
            if node.attr in {"__subclasses__", "__globals__", "__builtins__", "__import__"}:
                return False, f"禁止访问敏感属性: {node.attr}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BUILTINS:
                return False, f"禁止调用危险内建函数: {node.func.id}"

    return True, "Valid"


class StrategyHotPlugger:
    def __init__(self, strategies_dir: str = STRATEGIES_DIR):
        self.strategies_dir = strategies_dir
        self.custom_strategies: Dict[str, Dict[str, Any]] = {}
        self.file_mtimes: Dict[str, float] = {}
        self.reload_plugins()

    def reload_plugins(self):
        """扫描策略目录，热重载或新增修改的策略脚本"""
        if not os.path.exists(self.strategies_dir):
            return

        for fname in os.listdir(self.strategies_dir):
            if fname.endswith(".py") and not fname.startswith("_"):
                filepath = os.path.join(self.strategies_dir, fname)
                mtime = os.path.getmtime(filepath)

                # 仅在文件新建或修改时重新加载
                if filepath not in self.file_mtimes or self.file_mtimes[filepath] < mtime:
                    self._load_strategy_file(filepath)
                    self.file_mtimes[filepath] = mtime

    def _load_strategy_file(self, filepath: str):
        """使用 importlib 动态加载独立策略 py 文件，前置 AST 安全校验"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                code_content = f.read()

            is_valid, err_msg = validate_strategy_code_ast(code_content)
            if not is_valid:
                print(f"[HotPlug Security Warning] 拒绝加载存在安全隐患的策略文件 {filepath}: {err_msg}")
                return

            mod_name = os.path.splitext(os.path.basename(filepath))[0]
            spec = importlib.util.spec_from_file_location(mod_name, filepath)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)

                # 约定: 文件内定义 STRATEGY_NAME 与 calculate_signal(df)
                strat_name = getattr(module, "STRATEGY_NAME", mod_name)
                calc_func = getattr(module, "calculate_signal", None)
                description = getattr(module, "STRATEGY_DESCRIPTION", "自定义热插拔因果策略")

                if callable(calc_func):
                    self.custom_strategies[strat_name] = {
                        "name": strat_name,
                        "description": description,
                        "func": calc_func,
                        "file": filepath,
                        "is_custom": True,
                        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(filepath)))
                    }
                    print(f"[HotPlug] 🚀 成功热加载策略插件: {strat_name} ({filepath})")
        except Exception as e:
            print(f"[HotPlug Error] 无法加载策略文件 {filepath}: {e}")

    def list_strategies(self) -> List[Dict[str, Any]]:
        """获取全量可用策略列表（内置 + 热插拔自定义）"""
        self.reload_plugins()
        res = [
            {"name": "causal_ml", "description": "因果因果机器学习主策略 (Walk-Forward)", "is_custom": False}
        ]

        # 1. 内置策略
        for name in SIGNAL_FUNCTIONS.keys():
            res.append({
                "name": name,
                "description": f"内置规则策略: {name}",
                "is_custom": False
            })

        # 2. 热插拔自定义策略
        for name, meta in self.custom_strategies.items():
            if name not in SIGNAL_FUNCTIONS:
                res.append({
                    "name": name,
                    "description": meta["description"],
                    "is_custom": True,
                    "updated_at": meta.get("updated_at", "")
                })

        return res

    def get_executable_strategies(self) -> List[str]:
        """返回所有可调用的策略名称列表"""
        self.reload_plugins()
        strategies = ["causal_ml"] + list(SIGNAL_FUNCTIONS.keys()) + list(self.custom_strategies.keys())
        return list(dict.fromkeys(strategies))

    def calculate_signal(self, strategy_name: str, df: pd.DataFrame) -> pd.Series:
        """统一调用策略计算信号函数 (返回 -1, 0, 1)"""
        self.reload_plugins()

        # 1. 优先查热插拔自定义策略
        if strategy_name in self.custom_strategies:
            func = self.custom_strategies[strategy_name]["func"]
            sig = func(df)
            return pd.Series(sig, index=df.index).fillna(0).astype(int)

        # 2. 查内置策略库
        if strategy_name in SIGNAL_FUNCTIONS:
            func = SIGNAL_FUNCTIONS[strategy_name]
            sig = func(df)
            return pd.Series(sig, index=df.index).fillna(0).astype(int)

        raise ValueError(f"未找到已注册的热插拔策略: {strategy_name}")

    def save_custom_strategy_code(self, strategy_name: str, code_content: str, description: str = "") -> str:
        """从 Web API 动态保存新的策略脚本并实时生效（带 AST 安全审计）"""
        is_valid, err_msg = validate_strategy_code_ast(code_content)
        if not is_valid:
            raise ValueError(f"策略代码安全审核未通过: {err_msg}")

        import re
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", strategy_name):
            raise ValueError("策略名称必须是合法的标识符(仅包含字母、数字、下划线)")

        filename = f"{strategy_name}.py"
        filepath = os.path.abspath(os.path.join(self.strategies_dir, filename))
        if not filepath.startswith(os.path.abspath(self.strategies_dir)):
            raise ValueError("策略文件路径非法")

        # 如果没有标准头，补全头部描述
        if "STRATEGY_NAME" not in code_content:
            header = f'STRATEGY_NAME = "{strategy_name}"\nSTRATEGY_DESCRIPTION = "{description or "动态热插拔策略"}"\n\n'
            code_content = header + code_content

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code_content)

        # 强制热加载
        self._load_strategy_file(filepath)
        return filepath


# 全局单例
hot_plugger = StrategyHotPlugger()

if __name__ == "__main__":
    print("=== 热插拔策略库概览 ===")
    strats = hot_plugger.list_strategies()
    print(f"当前共注册 {len(strats)} 个策略:")
    for s in strats[:5]:
        print("  •", s)
