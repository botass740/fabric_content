import logging
import os
from app.config.settings import get_settings
from app.config.logging import setup_logging
from app.database.db import Database


def main() -> None:
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
        logger.info("Starting Telegram bot...")
        run_bot(settings, db)
        return

    # DEV: тест генерации
    if os.getenv("DEV_RUN_GENERATION") == "1":
        logger.info("=== DEV: Running generation test ===")

        from app.generators.topics import generate_topics
        from app.generators.titles import generate_titles
        from app.generators.articles import generate_article

        # Генерация тем
        topics = generate_topics(settings, n=5)
        logger.info(f"Topics: {topics}")

        # Генерация заголовков
        topic = topics[0] if topics else "финансовые ошибки в быту"
        titles = generate_titles(settings, topic=topic, n=5)
        logger.info(f"Titles: {titles}")

        # Генерация статьи
        title = titles[0] if titles else topic
        article = generate_article(settings, topic=topic, title=title)

        logger.info(f"Article length: {len(article)} chars")
        print("\n" + "="*60)
        print(f"TOPIC: {topic}")
        print(f"TITLE: {title}")
        print("="*60)
        print(article[:500] + "...")
        print("="*60)

    # DEV: тест генерации изображений
    if os.getenv("DEV_RUN_IMAGE") == "1":
        logger.info("=== DEV: Running image generation test ===")

        from app.generators.images import generate_cover

        topic = os.getenv("DEV_IMAGE_TOPIC", "финансовые ошибки в быту")
        title = os.getenv("DEV_IMAGE_TITLE", "Как я перестал тратить и начал жить")

        cover_path = generate_cover(settings, topic=topic, title=title)
        if cover_path:
            logger.info(f"Обложка сохранена: {cover_path}")
        else:
            logger.error("Не удалось создать обложку")


if __name__ == "__main__":
    main()
