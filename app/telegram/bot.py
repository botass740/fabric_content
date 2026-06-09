import asyncio
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app.database.db import Database, STATUS_APPROVED, STATUS_GENERATED, STATUS_REJECTED
from app.generators.articles import generate_article
from app.generators.images import generate_cover
from app.generators.titles import generate_titles
from app.generators.topics import generate_topics

logger = logging.getLogger(__name__)


def is_admin(settings, user_id: int | None) -> bool:
    if settings.telegram_admin_id is None:
        return True
    return user_id == settings.telegram_admin_id


def chunk_text(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    return chunks


def build_actions_keyboard(article_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"pub:{article_id}"),
            InlineKeyboardButton("🔄 Перегенерировать", callback_data=f"regen:{article_id}"),
        ],
        [
            InlineKeyboardButton("❌ Удалить", callback_data=f"del:{article_id}"),
        ],
    ])


async def send_article_preview(bot, chat_id: int, article: dict) -> None:
    title = article.get("title", "")
    content = article.get("content", "")
    image_path = article.get("image_path")
    status = article.get("status", "")
    article_id = article.get("id")

    # Отправка фото
    if image_path and Path(image_path).exists():
        try:
            with open(image_path, "rb") as photo:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=title[:1000],
                )
        except Exception as e:
            logger.warning(f"Failed to send photo: {e}")
            await bot.send_message(chat_id=chat_id, text=f"Заголовок: {title}")
    else:
        await bot.send_message(chat_id=chat_id, text=f"Заголовок: {title}")

    # Отправка текста статьи кусками
    chunks = chunk_text(content)
    for chunk in chunks:
        await bot.send_message(chat_id=chat_id, text=chunk)

    # Финальное сообщение с кнопками
    status_text = f"Статус: {status}\nID: {article_id}"
    await bot.send_message(
        chat_id=chat_id,
        text=status_text,
        reply_markup=build_actions_keyboard(article_id),
    )


def generate_full_article_payload(settings) -> tuple[str, str, str, str | None]:
    # Темы
    topics = generate_topics(settings, n=8)
    topic = topics[0] if topics else "финансовые ошибки в быту"

    # Заголовки
    titles = generate_titles(settings, topic=topic, n=8)
    title = titles[0] if titles else topic

    # Статья
    content = generate_article(settings, topic=topic, title=title)

    # Обложка
    image_path = generate_cover(settings, topic=topic, title=title)

    return topic, title, content, image_path


# ========================= Handlers =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    if not is_admin(settings, update.effective_user.id):
        return

    text = (
        "Привет! Я бот для публикации статей в Дзен.\n\n"
        "/generate — создать новую статью\n"
        "/queue — показать очередь статей\n"
        "/publish_last — опубликовать последнюю одобренную"
    )
    await update.message.reply_text(text)


async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]

    if not is_admin(settings, update.effective_user.id):
        return

    await update.message.reply_text("Генерирую статью... это может занять 1-2 минуты.")

    try:
        topic, title, content, image_path = await asyncio.to_thread(
            generate_full_article_payload, settings
        )

        article_id = db.create_article(
            title=title,
            content=content,
            image_path=image_path,
            status=STATUS_GENERATED,
        )
        article = db.get_article(article_id)

        await send_article_preview(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            article=article,
        )

    except Exception:
        logger.exception("Error in /generate handler")
        await update.message.reply_text("Ошибка генерации, см. логи.")


async def queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]

    if not is_admin(settings, update.effective_user.id):
        return

    articles = db.list_queue(limit=10)

    if not articles:
        await update.message.reply_text("Очередь пуста.")
        return

    lines = []
    for a in articles:
        title_short = a["title"][:50] + "..." if len(a["title"]) > 50 else a["title"]
        lines.append(f"#{a['id']} [{a['status']}] {title_short}")

    await update.message.reply_text("\n".join(lines))


async def publish_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]

    if not is_admin(settings, update.effective_user.id):
        return

    last = db.get_last(status=STATUS_APPROVED)

    if not last:
        await update.message.reply_text(
            "Нет одобренных статей. Нажмите 'Опубликовать' под превью."
        )
        return

    await update.message.reply_text(
        f"Публикатор Дзена будет добавлен на следующем этапе.\n"
        f"Последняя одобренная: #{last['id']} {last['title'][:60]}"
    )


# ========================= Callback Handler =========================

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    query = update.callback_query

    if not is_admin(settings, query.from_user.id):
        await query.answer("Нет доступа.")
        return

    data = query.data

    try:
        action, article_id_str = data.split(":", 1)
        article_id = int(article_id_str)
    except Exception:
        await query.answer("Неверный формат.")
        return

    # Кнопка: Опубликовать
    if action == "pub":
        article = db.get_article(article_id)
        if not article:
            await query.answer("Статья не найдена.")
            return

        if article["status"] == "published":
            await query.answer("Уже опубликовано.")
            return

        db.set_status(article_id, STATUS_APPROVED)
        await query.answer("Одобрено ✅")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Статья #{article_id} одобрена. Для публикации используйте /publish_last",
        )

    # Кнопка: Удалить
    elif action == "del":
        db.set_status(article_id, STATUS_REJECTED)
        await query.answer("Удалено ❌")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    # Кнопка: Перегенерировать
    elif action == "regen":
        await query.answer("Перегенерирую... подождите.")
        old = db.get_article(article_id)
        if not old:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Статья #{article_id} не найдена.",
            )
            return
        try:
            seed_topic = old["title"]
            def _regen(settings, seed_topic):
                titles = generate_titles(settings, topic=seed_topic, n=6)
                new_title = titles[0] if titles else seed_topic
                new_content = generate_article(settings, topic=seed_topic, title=new_title)
                new_image = generate_cover(settings, topic=seed_topic, title=new_title)
                return new_title, new_content, new_image
            new_title, new_content, new_image = await asyncio.to_thread(
                _regen, settings, seed_topic
            )
            db.update_article(
                article_id,
                title=new_title,
                content=new_content,
                image_path=new_image,
            )
            db.set_status(article_id, STATUS_GENERATED)
            article = db.get_article(article_id)
            await send_article_preview(
                bot=context.bot,
                chat_id=query.message.chat_id,
                article=article,
            )
        except Exception:
            logger.exception(f"Error regenerating article #{article_id}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Ошибка перегенерации статьи #{article_id}, см. логи.",
            )


def run_bot(settings, db: Database) -> None:
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["db"] = db
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("generate", generate))
    application.add_handler(CommandHandler("queue", queue))
    application.add_handler(CommandHandler("publish_last", publish_last))
    application.add_handler(CallbackQueryHandler(on_callback))
    logger.info("Bot started, polling...")
    application.run_polling()
