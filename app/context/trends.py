"""
Модуль загрузки актуальных финансовых триггеров.

monthly_triggers.txt — «жирные» темы месяца (10-15 блоков), обновляется вручную раз в месяц.
weekly_hot.txt — горячие темы недели (5-7 блоков), обновляется через /refresh_trends
                 (WebSearch + перезапись файла).

Формат файлов: блоки текста, разделённые пустой строкой. Строки, начинающиеся с '#', — комментарии.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Iterable

_MONTHLY_FILE = "monthly_triggers.txt"
_WEEKLY_FILE = "weekly_hot.txt"


def _context_dir(settings) -> Path:
    return settings.project_root / "app" / "context"


def _parse_blocks(text: str) -> list[str]:
    """
    Парсит файл на блоки. Блок — набор строк между пустыми строками.
    Строки, начинающиеся с '#', игнорируются.
    """
    blocks: list[str] = []
    current: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("#"):
            continue
        if not line.strip():
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def _load_file(settings, filename: str, logger: logging.Logger | None = None) -> list[str]:
    path = _context_dir(settings) / filename
    if not path.exists():
        if logger:
            logger.warning(f"Trend file not found: {path}")
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        if logger:
            logger.warning(f"Cannot read trend file {path}: {e}")
        return []
    return _parse_blocks(text)


def load_trend_context(
    settings,
    *,
    monthly_sample: int = 4,
    weekly_sample: int = 3,
    logger: logging.Logger | None = None,
) -> str:
    """
    Возвращает готовый текстовый блок с актуальными триггерами для подстановки в промт тем.
    Из monthly берём случайные monthly_sample блоков (чтобы каждая генерация видела разный срез).
    Из weekly берём случайные weekly_sample блоков.

    Если оба файла пустые — возвращает пустую строку (промт должен корректно обработать пустой блок).
    """
    log = logger or logging.getLogger(__name__)

    monthly = _load_file(settings, _MONTHLY_FILE, log)
    weekly = _load_file(settings, _WEEKLY_FILE, log)

    parts: list[str] = []

    if weekly:
        picked = random.sample(weekly, min(weekly_sample, len(weekly)))
        parts.append("Горячие темы этой недели:")
        for i, b in enumerate(picked, 1):
            parts.append(f"{i}. {b}")

    if monthly:
        if parts:
            parts.append("")
        picked = random.sample(monthly, min(monthly_sample, len(monthly)))
        parts.append("Фоновые триггеры месяца:")
        for i, b in enumerate(picked, 1):
            parts.append(f"{i}. {b}")

    if not parts:
        return "(актуальные триггеры не заданы — опирайся только на комбинацию осей)"

    return "\n".join(parts)


def write_weekly_hot(
    settings,
    blocks: Iterable[str],
    *,
    header: str | None = None,
    logger: logging.Logger | None = None,
) -> Path:
    """
    Перезаписывает weekly_hot.txt указанными блоками.
    header — опциональная шапка (комментарии с '#').
    Возвращает путь к файлу.
    """
    log = logger or logging.getLogger(__name__)
    path = _context_dir(settings) / _WEEKLY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if header:
        for h in header.splitlines():
            h = h.rstrip()
            if h and not h.startswith("#"):
                h = "# " + h
            lines.append(h)
        lines.append("")

    for b in blocks:
        b = b.strip()
        if not b:
            continue
        lines.append(b)
        lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    path.write_text(text, encoding="utf-8")
    log.info(f"weekly_hot.txt updated: {len([b for b in blocks if b.strip()])} blocks")
    return path
