"""
验证 eval task YAML 文件：
1. 30 个 YAML 文件都存在
2. 每个都能被 EvalTaskDef.from_yaml_dict() 正确解析
3. 5 个类别各有对应数量
"""
import sys
import os
import yaml
from collections import Counter

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals.models import EvalTaskDef, EvalCategory

TASKS_DIR = os.path.join(os.path.dirname(__file__), "tasks")

EXPECTED_COUNTS = {
    "intent_classification": 10,
    "command_generation": 8,
    "knowledge_retrieval": 4,
    "safety": 5,
    "multi_turn": 3,
}


def main():
    errors = []
    all_files = []
    category_counts = Counter()

    # 遍历所有类别目录
    for category_dir, expected_count in EXPECTED_COUNTS.items():
        cat_path = os.path.join(TASKS_DIR, category_dir)
        if not os.path.isdir(cat_path):
            errors.append(f"缺少目录: {cat_path}")
            continue

        yaml_files = sorted(
            f for f in os.listdir(cat_path) if f.endswith(".yaml") or f.endswith(".yml")
        )
        category_counts[category_dir] = len(yaml_files)

        for fname in yaml_files:
            fpath = os.path.join(cat_path, fname)
            all_files.append(fpath)

            # 读取并解析 YAML
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except Exception as e:
                errors.append(f"YAML 解析失败 {fname}: {e}")
                continue

            # 用 EvalTaskDef.from_yaml_dict() 验证
            try:
                task_def = EvalTaskDef.from_yaml_dict(data)
            except Exception as e:
                errors.append(f"EvalTaskDef 验证失败 {fname}: {e}")
                continue

            # 检查 category 一致
            if task_def.category.value != category_dir:
                errors.append(
                    f"{fname}: category 不匹配，文件在 {category_dir}/ 但 YAML 中为 {task_def.category.value}"
                )

    # 汇总结果
    total = len(all_files)
    print(f"=== Eval Task 验证结果 ===\n")
    print(f"总文件数: {total} (期望 30)")
    print()

    print("各类别数量:")
    all_match = True
    for cat, expected in EXPECTED_COUNTS.items():
        actual = category_counts.get(cat, 0)
        status = "OK" if actual == expected else "MISMATCH"
        if actual != expected:
            all_match = False
        print(f"  {cat}: {actual} (期望 {expected}) [{status}]")
    print()

    if errors:
        print(f"发现 {len(errors)} 个错误:")
        for err in errors:
            print(f"  - {err}")
        print()
        return False
    else:
        if total == 30 and all_match:
            print("所有验证通过!")
            return True
        else:
            print("验证失败: 文件总数或类别数量不匹配")
            return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
