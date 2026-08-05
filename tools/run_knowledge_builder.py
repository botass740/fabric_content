#!/usr/bin/env python3
"""
CLI: запуск построения базы знаний из статистического анализа.

Использование:
  python tools/run_knowledge_builder.py
"""

import os
import sys

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from knowledge.builder import KnowledgeBuilder


def main() -> None:
    """Запустить построение базы знаний и вывести сводку."""
    print("=" * 60)
    print("Построение базы знаний из статистики")
    print("=" * 60)

    builder = KnowledgeBuilder()

    try:
        results = builder.build_all()

        print("\n" + "=" * 60)
        print("Созданные файлы в knowledge_base/:")
        print("=" * 60)

        for name in results["files_created"]:
            path = f"knowledge_base/{name}.json"
            if os.path.exists(path):
                size = os.path.getsize(path)
                print(f"  [OK] {name}.json: {size / 1024:.1f} KB")
            else:
                print(f"  [FAIL] {name}.json: не создан")

        meta_path = "knowledge_base/meta.json"
        if os.path.exists(meta_path):
            size = os.path.getsize(meta_path)
            print(f"  [OK] meta.json: {size / 1024:.1f} KB")

        print("\n" + "=" * 60)
        print("ГОТОВО!")
        print("=" * 60)
        print(f"Проанализировано статей: {results['articles_analyzed']}")
        print(f"Файлов создано: {len(results['files_created'])}")
        print(f"Время выполнения: {results['build_time_seconds']} с")
        print()
        print("Следующий шаг:")
        print("  python tools/run_llm_analyzer.py")
        print("  (финальный анализ через Claude)")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        builder.close()


if __name__ == "__main__":
    main()