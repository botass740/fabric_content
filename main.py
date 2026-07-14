import logging
import os
from app.config.settings import get_settings
from app.config.logging import setup_logging
from app.database.db import Database


def main() -> None:
    # Отключаем системный прокси (SOCKS4) для httpx
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    settings = get_settings()
    setup_logging(settings)

    # Инициализация базы данных
    logger = logging.getLogger(__name__)
    db = Database(settings.sqlite_db_path, logger=logger)
    logger.info(f"SQLite database path: {settings.sqlite_db_path}")
    logger.info("DB schema OK")

    # Создаем все необходимые директории
    settings.articles_dir.mkdir(parents=True, exist_ok=True)
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.playwright_user_data_path.mkdir(parents=True, exist_ok=True)

    logger.info("Startup OK")
    logger.info(f"Project root: {settings.project_root}")
    logger.info(f"Data dir: {settings.data_dir_path}")
    logger.info(f"Articles dir: {settings.articles_dir}")
    logger.info(f"Images dir: {settings.images_dir}")
    logger.info(f"Logs dir: {settings.logs_dir}")
    logger.info(f"Playwright profile: {settings.playwright_user_data_path}")

    # Запуск Telegram бота
    if os.getenv("RUN_BOT") == "1":
        from app.telegram.bot import run_bot
        from app.publishers.dzen_publisher import DzenPublisher
        logger.info("Starting Telegram bot...")
        publisher = DzenPublisher(settings, logger=logger)
        run_bot(settings, db, publisher)
        return

    # DEV: тест генерации
    if os.getenv("DEV_RUN_GENERATION") == "1":
        logger.info("=== DEV: Running generation test ===")

        from app.generators.topics import generate_topics
        from app.generators.titles import generate_titles
        from app.generators.article_plan import generate_article_plan
        from app.generators.story_check import generate_story_check
        from app.generators.articles import generate_article
        from app.generators.topic_matrix import pick_combination
        from app.context.trends import load_trend_context

        combination = pick_combination(db, logger=logger)
        logger.info(f"Combination: {combination}")

        # Один срез актуального фона на всю генерацию
        live_triggers = load_trend_context(settings, logger=logger)

        # Генерация тем
        topics = generate_topics(
            settings,
            combination=combination,
            live_triggers=live_triggers,
            recent_topics=db.recent_topics(limit=30),
            n=3,
        )
        logger.info(f"Topics: {topics}")

        # Генерация заголовков
        topic = topics[0] if topics else "финансовые ошибки в быту"
        titles = generate_titles(
            settings,
            topic=topic,
            hook_type=combination["hook_type"],
            hero=combination["hero"],
            n=5,
        )
        logger.info(f"Titles: {titles}")

        # План + story_check + статья
        title = titles[0] if titles else topic
        plan_text, plan_json = generate_article_plan(
            settings,
            topic=topic,
            title=title,
            hero=combination["hero"],
            emotion=combination["emotion"],
            format=combination["format"],
            live_triggers=live_triggers,
        )

        # Story check (в DEV режиме — однократно, без retry)
        check = generate_story_check(
            settings,
            topic=topic,
            title=title,
            plan_json=plan_json,
        )
        if check is not None:
            logger.info(f"[DEV] Story check: status={check['status']} score={check['score']}")
            if check["status"] == "FAIL":
                logger.warning(f"[DEV] Story check FAILED. Issues: {len(check.get('issues', []))}")
        else:
            logger.warning("[DEV] Story check technical error — skipped")

        article = generate_article(
            settings,
            topic=topic,
            title=title,
            plan=plan_text,
            hero=combination["hero"],
            emotion=combination["emotion"],
            format=combination["format"],
            live_triggers=live_triggers,
        )

        db.register_combination(
            hero=combination["hero"],
            emotion=combination["emotion"],
            format=combination["format"],
            trigger=combination["trigger"],
            hook_type=combination["hook_type"],
            topic=topic,
        )

        logger.info(f"Article length: {len(article)} chars")
        print("\n" + "="*60)
        print(f"COMBINATION: {combination}")
        print(f"TOPIC: {topic}")
        print(f"TITLE: {title}")
        print("="*60)
        print(article[:800] + "...")
        print("="*60)

    # DEV: тест генерации изображений
    if os.getenv("DEV_RUN_IMAGE") == "1":
        logger.info("=== DEV: Running image generation test ===")

        from app.generators.images import generate_cover

        topic = os.getenv("DEV_IMAGE_TOPIC", "финансовые ошибки в быту")
        title = os.getenv("DEV_IMAGE_TITLE", "Как я перестал тратить и начал жить")

        cover_path = generate_cover(settings, topic=topic, title=title, content=title)
        if cover_path:
            logger.info(f"Обложка сохранена: {cover_path}")
        else:
            logger.error("Не удалось создать обложку")


if __name__ == "__main__":
    main()
