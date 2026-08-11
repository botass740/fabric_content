#!/usr/bin/env python3
"""
CLI: запуск построения базы знаний из статистического анализа.

Использование:
  python tools/run_knowledge_builder.py
  python tools/run_knowledge_builder.py --db data/other.db \
      --stats data/report.json --output knowledge_base_health
"""

import argparse
import os
import sys

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from knowledge.builder import KnowledgeBuilder


def main() -> None:
    """Запустить построение базы знаний и вывести сводку."""
    parser = argparse.ArgumentParser(
        description="Построение базы знаний из статистического анализа"
    )
    parser.add_argument(
        "--db",
        default="data/research.db",
        help="Путь к базе данных (по умолчанию data/research.db)",
    )
    parser.add_argument(
        "--stats",
        default="data/statistics_report.json",
        help="Путь к файлу статистики (по умолчанию data/statistics_report.json)",
    )
    parser.add_argument(
        "--output",
        default="knowledge_base",
        help="Папка для базы знаний (по умолчанию knowledge_base)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Построение базы знаний из статистики")
    print("=" * 60)
    print(f"  БД:         {args.db}")
    print(f"  Статистика: {args.stats}")
    print(f"  Папка:      {args.output}")
    print()

    builder = KnowledgeBuilder(
        db_path=args.db,
        statistics_path=args.stats,
        knowledge_dir=args.output,
    )

    try:
        results = builder.build_all()

        print("\n" + "=" * 60)
        print(f"Созданные файлы в {args.output}/:")
        print("=" * 60)

        for name in results["files_created"]:
            path = os.path.join(args.output, f"{name}.json")
            if os.path.exists(path):
                size = os.path.getsize(path)
                print(f"  [OK] {name}.json: {size / 1024:.1f} KB")
            else:
                print(f"  [FAIL] {name}.json: не создан")

        meta_path = os.path.join(args.output, "meta.json")
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
        print("  (финальный анализ через Claude; "
              "если база в другой папке — добавь --knowledge-dir <папка>)")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        builder.close()


if __name__ == "__main__":
    main()