#!/usr/bin/env python3
"""
CLI: запуск LLM-анализа базы знаний.

Использование:
  python tools/run_llm_analyzer.py
  python tools/run_llm_analyzer.py --knowledge-dir knowledge_base_health

Результаты:
  - <knowledge-dir>/llm_analysis.json
  - <knowledge-dir>/RECOMMENDATIONS.md
"""

import argparse
import asyncio
import sys
import os

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from knowledge.llm_analyzer import LLMAnalyzer


async def main() -> None:
    """Запустить LLM-анализ и вывести сводку."""
    parser = argparse.ArgumentParser(
        description="LLM-анализ базы знаний"
    )
    parser.add_argument(
        "--knowledge-dir",
        default="knowledge_base",
        help="Папка с базой знаний (по умолчанию knowledge_base)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("LLM Анализ базы знаний")
    print("=" * 60)
    print()
    print(f"Загружаем агрегированные данные из {args.knowledge_dir}/...")

    analyzer = LLMAnalyzer(knowledge_dir=args.knowledge_dir)

    print("Отправляем запрос в Claude...")
    print("(это займёт 30-60 секунд)")
    print()

    try:
        result = await analyzer.analyze()

        print("=" * 60)
        print("АНАЛИЗ ЗАВЕРШЁН")
        print("=" * 60)
        print(f"Модель: {result['model']}")
        print(
            "Токенов использовано: "
            f"{result.get('prompt_tokens', 0) + result.get('completion_tokens', 0)}"
        )
        print()

        analyzer.save_analysis(result)

        print("Результаты сохранены:")
        print(f"  {args.knowledge_dir}/llm_analysis.json")
        print(f"  {args.knowledge_dir}/RECOMMENDATIONS.md")
        print()

        print("=" * 60)
        print("КРАТКАЯ ВЫЖИМКА")
        print("=" * 60)

        # Вывести первые 1000 символов анализа
        analysis_text = result.get("analysis", "")
        print(analysis_text[:1000])
        if len(analysis_text) > 1000:
            print("\n... (см. полный текст в RECOMMENDATIONS.md)")

        print()
        print("=" * 60)
        print("СЛЕДУЮЩИЙ ШАГ")
        print("=" * 60)
        print("Интеграция базы знаний в генератор статей:")
        print("  1. Обогатить app/generators/topics.py паттернами")
        print("  2. Обогатить app/generators/titles.py шаблонами")
        print("  3. Обогатить app/prompts/ рекомендациями")

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())