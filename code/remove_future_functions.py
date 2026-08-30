import os
import re
import sys
from pathlib import Path

def is_future_function_file(file_path):
    """
    Analyzes a Pine script / markdown wrapper file for future functions (未来函数) / repainting (重绘) patterns.
    Returns (has_future_func: bool, reasons: list of str)
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        return False, [f"Error reading file: {e}"]

    reasons = []

    # Rule 1: Explicit lookahead_on in request.security / security calls
    if re.search(r'barmerge\.lookahead_on', content, re.IGNORECASE):
        reasons.append("Contains 'barmerge.lookahead_on' (accesses future higher-timeframe data)")
    elif re.search(r'lookahead\s*=\s*(true|barmerge\.lookahead_on)', content, re.IGNORECASE):
        reasons.append("Contains 'lookahead = true' in security call")

    # Rule 2: Direct negative bar indexing (e.g. close[-1], high[-2])
    neg_index_matches = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\s*\[\s*-\s*[1-9]\d*\s*\]', content)
    if neg_index_matches:
        reasons.append(f"Negative bar indexing accessing future bars directly: {list(set(neg_index_matches))[:5]}")

    # Rule 3: Nadaraya-Watson non-causal estimator (calculates future + past points centered at barstate.islast)
    if re.search(r'Nadaraya-Watson', content, re.IGNORECASE) and re.search(r'barstate\.islast', content, re.IGNORECASE):
        reasons.append("Nadaraya-Watson non-causal repainting estimator calculated retroactively on barstate.islast")

    # Rule 4: Default repainting toggle enabled
    if re.search(r'repaint\s*=\s*input(\.bool)?\(\s*true', content, re.IGNORECASE):
        reasons.append("Repainting toggle enabled by default ('repaint = input(true)')")

    # Rule 5: Pine v1/v2/v3 security calls without explicit lookahead_off
    v123_match = re.search(r'//@version=[123]\b', content)
    if v123_match:
        if re.search(r'\bsecurity\s*\(', content) and not re.search(r'lookahead\s*=\s*barmerge\.lookahead_off', content, re.IGNORECASE):
            reasons.append("Pine v1-v3 'security()' call defaults to lookahead_on without explicit lookahead_off")

    # Rule 6: Negative plot offsets (offset = -N) which plot historical signals in the past visually
    neg_offset_matches = re.findall(r'plot\w*\s*\([^)]*offset\s*=\s*-\s*[1-9]\d*', content, re.IGNORECASE)
    if neg_offset_matches:
        reasons.append("Contains negative plot offset (shifts visual signals backwards to past bars)")

    # Rule 7: Retroactive loop rewriting historical bars on barstate.islast
    if re.search(r'barstate\.islast', content) and re.search(r'for\s+\w+\s*=\s*0\s+to.*line\.new\s*\(\s*n\s*-\s*\w+', content):
        reasons.append("Retroactive line/label creation over historical bars on barstate.islast")

    return len(reasons) > 0, reasons


def clean_directory(target_dir, dry_run=False):
    target_path = Path(target_dir)
    if not target_path.exists():
        print(f"Target directory does not exist: {target_dir}")
        return [], []

    removed_files = []
    retained_files = []

    for file_path in sorted(target_path.rglob('*')):
        if file_path.is_file() and file_path.suffix.lower() in ['.md', '.pine', '.txt']:
            has_future, reasons = is_future_function_file(file_path)
            rel_path = file_path.relative_to(target_path)
            if has_future:
                removed_files.append((file_path, reasons))
                print(f"[DELETE] {rel_path}")
                for r in reasons:
                    print(f"   └─ Reason: {r}")
                if not dry_run:
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        print(f"   └─ Error removing file: {e}")
            else:
                retained_files.append(file_path)

    print("\n" + "="*70)
    print(f"Scan Result for: {target_dir}")
    print(f"Total files scanned: {len(removed_files) + len(retained_files)}")
    print(f"Files containing future functions ({'WOULD BE DELETED' if dry_run else 'DELETED'}): {len(removed_files)}")
    print(f"Retained files: {len(retained_files)}")
    print("="*70)

    return removed_files, retained_files

def scan_python_lookahead(directory: str) -> list[dict]:
    """扫描 Python 文件中的常见前视偏差模式。
    ponytail: 启发式检测，不能替代人工审计；升级路径 = AST 解析追踪数据流
    """
    import re
    from pathlib import Path
    patterns = [
        (r'\.shift\s*\(\s*-', 'shift(-N) 使用了未来数据'),
        (r'\.bfill\s*\(', '.bfill() 后向填充引入未来数据'),
        (r'iloc\s*\[\s*-1\s*\]', 'iloc[-1] 在信号计算中可能使用未闭合K线'),
        (r'\.max\(\)', '.max() 全局聚合可能引入未来数据'),
        (r'lookahead', '显式 lookahead 标记'),
    ]
    findings = []
    for py_file in Path(directory).rglob('*.py'):
        try:
            text = py_file.read_text(encoding='utf-8')
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat, desc in patterns:
                if re.search(pat, line):
                    findings.append({
                        'file': str(py_file),
                        'line': lineno,
                        'pattern': desc,
                        'content': line.strip()[:120],
                    })
    return findings


if __name__ == '__main__':
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent)
    results = scan_python_lookahead(target)
    for r in results:
        print(f"{r['file']}:{r['line']} [{r['pattern']}] {r['content']}")
    print(f"\n共发现 {len(results)} 处潜在前视偏差")
