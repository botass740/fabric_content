import pyperclip
import random
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from playwright.sync_api import Page, Locator, sync_playwright


@dataclass
class PublishResult:
    ok: bool
    url: str | None = None
    error: str | None = None
    screenshot_path: str | None = None


def sleep_rand(page: Page, a: float = 0.3, b: float = 1.0) -> None:
    """Случайная пауза чтобы не выглядеть как бот"""
    page.wait_for_timeout(int(random.uniform(a, b) * 1000))


def safe_screenshot(page: Page, logs_dir: Path, prefix: str = "dzen_fail") -> str:
    """Сохраняет скриншот в папку логов"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = logs_dir / f"{prefix}_{timestamp}.png"
    try:
        page.screenshot(path=str(path))
    except Exception:
        pass
    return str(path)


class DzenPublisher:
    """Publisher for Dzen platform using Playwright."""

    # Селекторы новой студии/редактора (dzen 17.08.2026).
    # Старый путь через аватар на главной («Создать публикацию» в меню) больше не существует:
    # dzen перевёл создание в студию /profile/editor/new/...
    CREATE_BTN = "[class*='publications-layout__button-NT']"
    MENU_WRITE_ARTICLE = "span:has-text('Написать статью')"
    TITLE_FIELD = "div[contenteditable][data-placeholder='Заголовок' i]"
    CONTENT_FIELD = "div.ql-editor[contenteditable]"
    FILE_INPUT = "input[type=file]"
    PUBLISH_BTN = "[data-testid='article-publish-btn']"

    def __init__(self, settings, logger):
        self.settings = settings
        self.logger = logger

    def publish_article(
        self,
        *,
        title: str,
        content: str,
        image_path: str | None,
    ) -> PublishResult:

        self.logger.info(f"Starting Dzen publish: {title[:50]}")

        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(self.settings.playwright_user_data_path),
                headless=self.settings.dzen_headless,
                locale="ru-RU",
                viewport={"width": 1400, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-default-browser-check",
                    "--no-first-run",
                    "--disable-default-apps",
                    "--disable-extensions-except=",
                    "--disable-popup-blocking",
                    "--disable-notifications",
                    "--disable-infobars",
                    "--deny-permission-prompts",
                ],
                ignore_default_args=["--enable-automation"],
            )
            context.set_default_timeout(self.settings.dzen_default_timeout_ms)

            try:
                if context.pages:
                    page = context.pages[0]
                else:
                    page = context.new_page()

                page.set_default_timeout(60000)

                # ШАГ 1: Открываем студию блогера (страница публикаций).
                # Старый вход через главную dzen.ru + аватар мёртв — создание переехало сюда.
                self.logger.info("Step 1: Opening dzen studio (publications)")
                page.goto(
                    "https://dzen.ru/profile/editor/new/publications/?state=draft",
                    wait_until="commit",
                    timeout=30000,
                )
                sleep_rand(page, 2.0, 3.0)

                # Проверка авторизации (после паузы, чтобы SPA успело применить редирект)
                if "passport" in page.url or "login" in page.url:
                    self.logger.warning("Not authorized!")
                    screenshot = safe_screenshot(page, self.settings.logs_dir, "not_authorized")
                    return PublishResult(ok=False, error="Not authorized", screenshot_path=screenshot)

                # ШАГ 2: Кнопка «Создать» в студии (открывает меню «Написать статью» / «Загрузить видео»)
                self.logger.info("Step 2: Looking for create button in studio...")
                create_btn = page.locator(self.CREATE_BTN).first
                try:
                    create_btn.wait_for(state="visible", timeout=60000)
                    create_btn.click()
                    sleep_rand(page, 1.5, 2.5)
                    self.logger.info("Create button clicked")
                except Exception as e:
                    screenshot = safe_screenshot(page, self.settings.logs_dir, "create_btn_not_found")
                    return PublishResult(
                        ok=False,
                        error=f"'Create' button in studio not found: {e}",
                        screenshot_path=screenshot,
                    )

                # ШАГ 3: В меню — «Написать статью»
                self.logger.info("Step 3: Clicking 'Написать статью' in create menu")
                try:
                    write_article = page.locator(self.MENU_WRITE_ARTICLE).first
                    write_article.wait_for(state="visible", timeout=15000)
                    write_article.click()
                    sleep_rand(page, 2.0, 3.0)
                    self.logger.info("'Написать статью' clicked")
                except Exception as e:
                    screenshot = safe_screenshot(page, self.settings.logs_dir, "write_article_btn_not_found")
                    return PublishResult(
                        ok=False,
                        error=f"'Написать статью' in create menu not found: {e}",
                        screenshot_path=screenshot,
                    )

                # Редактор новой статьи (Quill). Открывается в той же вкладке,
                # внутри SPA: /profile/editor/new/editor/<id>. Грузится на слабом VPS медленно.
                self.logger.info("Step 4: Waiting for article editor to load...")
                editor_ready = self._wait_for_editor(page)
                if not editor_ready:
                    self.logger.warning(
                        f"Editor fields never appeared. url={page.url}"
                    )
                    screenshot = safe_screenshot(page, self.settings.logs_dir, "editor_not_loaded")
                    return PublishResult(
                        ok=False,
                        error="Editor did not load (no ql-editor field)",
                        screenshot_path=screenshot,
                    )
                self.logger.info(f"Editor URL: {page.url}")

                return self._fill_and_publish(page, title=title, content=content, image_path=image_path)

            except Exception as e:
                self.logger.exception(f"Playwright error: {e}")
                try:
                    screenshot = safe_screenshot(page, self.settings.logs_dir, "dzen_error")
                except Exception:
                    screenshot = None
                return PublishResult(ok=False, error=str(e), screenshot_path=screenshot)

            finally:
                context.close()

    def _wait_for_editor(self, page, timeout_s: float = 90.0) -> bool:
        """Ждёт появления поля контента нового Quill-редактора (`ql-editor`).

        Редактор новой статьи грузится в SPA десятки секунд на слабом VPS,
        поэтому поллим селектор в цикле, а не ждём один раз с таймаутом.
        """
        deadline = timeout_s * 1000
        waited = 0.0
        while waited < deadline:
            try:
                n = page.locator(self.CONTENT_FIELD).count()
                if n >= 1:
                    try:
                        page.locator(self.TITLE_FIELD).first.wait_for(state="visible", timeout=5000)
                    except Exception:
                        pass
                    return True
            except Exception:
                pass
            page.wait_for_timeout(2000)
            waited += 2000
            if int(waited) % 10000 == 0:
                self.logger.info(f"Waiting for editor... {int(waited/1000)}s")
        return False

    def _fill_and_publish(
        self,
        page,
        *,
        title: str,
        content: str,
        image_path: str | None,
    ) -> PublishResult:

        self.logger.info(
            f"Preparing to fill editor: title_len={len(title)}, content_len={len(content)}"
        )

        # ================================================================
        # ШАГ 1: Вставить заголовок через буфер обмена (Ctrl+V)
        # ================================================================
        self.logger.info("Step 1: Filling title")
        try:
            title_loc = page.locator(self.TITLE_FIELD).first
            title_loc.wait_for(state="visible", timeout=30000)
            title_loc.click()
            sleep_rand(page, 0.5, 1.0)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            sleep_rand(page, 0.3, 0.5)

            pyperclip.copy(title)
            page.keyboard.press("Control+V")
            sleep_rand(page, 0.5, 1.0)
            got = title_loc.inner_text().strip()
            self.logger.info(f"Title pasted via clipboard (pasted_len={len(got)})")
        except Exception as e:
            screenshot = safe_screenshot(page, self.settings.logs_dir, "title_error")
            return PublishResult(ok=False, error=f"Title error: {e}", screenshot_path=screenshot)

        sleep_rand(page, 1.0, 1.5)

        # ================================================================
        # ШАГ 2: Загрузка обложки — прямой <input type=file> в редакторе
        # ================================================================
        if image_path and Path(image_path).exists():
            self.logger.info(f"Step 2: Uploading cover image: {image_path}")
            try:
                file_input = page.locator(self.FILE_INPUT).first
                file_input.set_input_files(str(image_path))
                sleep_rand(page, 3.0, 4.0)
                imgs = page.locator("img").count()
                self.logger.info(f"Cover image uploaded via input[type=file] (imgs={imgs})")
            except Exception as e:
                # Обложка некритична: неудача не должна ронять публикацию
                self.logger.warning(f"Cover upload failed (non-critical): {e}")
                safe_screenshot(page, self.settings.logs_dir, "cover_fail")
        else:
            self.logger.info("No cover image, skipping")

        sleep_rand(page, 1.0, 1.5)

        # ================================================================
        # ШАГ 3: Вставить контент (вставка с \n\n → отдельные <p>-блоки в Quill)
        # ================================================================
        self.logger.info("Step 3: Filling content")
        try:
            content_loc = page.locator(self.CONTENT_FIELD).first
            content_loc.click()
            sleep_rand(page, 0.5, 1.0)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            sleep_rand(page, 0.3, 0.5)

            # Форсируем фокус через JS
            page.evaluate("""() => {
                const el = document.querySelector('div.ql-editor[contenteditable]');
                if (el) {
                    el.focus();
                    const sel = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    range.collapse(false);
                    sel.removeAllRanges();
                    sel.addRange(range);
                }
            }""")
            sleep_rand(page, 0.3, 0.5)

            # Вставка целиком: Quill сам раскладывает \n\n на отдельные <p>-блоки.
            # Проверено на живом редакторе (17.08.2026).
            pyperclip.copy(content)
            page.keyboard.press("Control+V")
            sleep_rand(page, 2.0, 3.0)
            pasted_len = len(content_loc.inner_text().strip())
            self.logger.info(f"Content pasted (pasted_len={pasted_len}, expected~{len(content)})")

            # Если вставка проглотилась (слабый VPS) — печатаем по абзацам.
            if pasted_len < len(content) * 0.6:
                self.logger.warning("Paste swallowed — falling back to typing by paragraphs")
                content_loc.click()
                sleep_rand(page, 0.5, 1.0)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                sleep_rand(page, 0.3, 0.5)

                paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
                self.logger.info(f"Typing {len(paragraphs)} paragraphs")

                for i, para in enumerate(paragraphs):
                    for j in range(0, len(para), 500):
                        page.keyboard.type(para[j:j + 500], delay=0)
                        sleep_rand(page, 0.02, 0.05)

                    if i < len(paragraphs) - 1:
                        page.keyboard.press("Enter")
                        page.keyboard.press("Enter")
                        sleep_rand(page, 0.1, 0.2)

            sleep_rand(page, 1.0, 2.0)
            self.logger.info(f"Content filled ({len(content)} chars)")
        except Exception as e:
            screenshot = safe_screenshot(page, self.settings.logs_dir, "content_error")
            return PublishResult(ok=False, error=f"Content error: {e}", screenshot_path=screenshot)

        sleep_rand(page, 1.5, 2.0)

        # ================================================================
        # ШАГ 4: Нажать «Опубликовать» (data-testid), затем подтвердить в диалоге
        # ================================================================
        self.logger.info("Step 4: Publishing")
        try:
            publish_btn = page.locator(self.PUBLISH_BTN).first
            publish_btn.wait_for(state="visible", timeout=30000)
            publish_btn.click()
            sleep_rand(page, 2.0, 3.0)
            self.logger.info("Publish button (testid) clicked")
        except Exception as e:
            screenshot = safe_screenshot(page, self.settings.logs_dir, "publish_btn_not_found")
            return PublishResult(ok=False, error=f"Publish button not found: {e}", screenshot_path=screenshot)

        # После первого клика может открыться диалог подтверждения с «Опубликовать»
        sleep_rand(page, 2.0, 3.0)
        try:
            confirm = page.locator("button:has-text('Опубликовать')").all()
            self.logger.info(f"Found {len(confirm)} publish buttons after first click")
            for btn in reversed(confirm):
                try:
                    if btn.is_visible():
                        btn.click()
                        self.logger.info("Clicked final publish button in dialog")
                        sleep_rand(page, 4.0, 5.0)
                        break
                except Exception:
                    continue
        except Exception as e:
            self.logger.warning(f"Failed to click dialog publish button: {e}")

        # ================================================================
        # ШАГ 5: Проверяем успех
        # ================================================================
        sleep_rand(page, 3.0, 5.0)
        final_url = page.url
        self.logger.info(f"Final URL: {final_url}")

        # Признаки успеха (новый редактор может вести себя по-разному — ловим все):
        if "/a/" in final_url:
            self.logger.info("URL contains /a/ — published successfully")
            return PublishResult(ok=True, url=final_url)

        success_texts = ["Опубликовано", "Статья опубликована", "Публикация доступна"]
        for text in success_texts:
            try:
                if page.locator(f"text={text}").count() > 0:
                    self.logger.info(f"Success indicator found: {text}")
                    return PublishResult(ok=True, url=final_url)
            except Exception:
                pass

        # Публикация могла увести со страницы редактора на список публикаций/канал
        if "editor" not in final_url:
            self.logger.info("Left editor page — likely published successfully")
            return PublishResult(ok=True, url=final_url)

        screenshot = safe_screenshot(page, self.settings.logs_dir, "publish_unknown")
        return PublishResult(
            ok=False,
            error="Publish result unknown, check screenshot",
            screenshot_path=screenshot,
        )