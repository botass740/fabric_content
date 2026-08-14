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

                # ШАГ 1: Открываем главную Дзена.
                # DOMContentLoaded у dzen нестабилен (6-60+с) и упирался в таймаут 60с,
                # из-за чего публикации падали. Ждём только commit навигации (быстрый),
                # а реальную готовность UI определяем ожиданием иконки профиля ниже.
                self.logger.info("Step 1: Opening dzen.ru")
                page.goto("https://dzen.ru", wait_until="commit", timeout=30000)
                sleep_rand(page, 2.0, 3.0)

                # Проверка авторизации (после паузы, чтобы SPA успело применить редирект)
                if "passport" in page.url or "login" in page.url:
                    self.logger.warning("Not authorized!")
                    screenshot = safe_screenshot(page, self.settings.logs_dir, "not_authorized")
                    return PublishResult(ok=False, error="Not authorized", screenshot_path=screenshot)

                # ШАГ 2: ждём появления иконки профиля (явное ожидание вместо
                # ненадёжного DOMContentLoaded) и кликаем
                self.logger.info("Step 2: Clicking profile icon")
                profile_clicked = False
                profile_selectors = [
                    "[class*='profile']",
                    "[class*='avatar']",
                    "[class*='Avatar']",
                    "[data-testid='user-avatar']",
                ]
                for sel in profile_selectors:
                    try:
                        loc = page.locator(sel).first
                        loc.wait_for(state="visible", timeout=60000)
                        loc.click()
                        sleep_rand(page, 1.0, 2.0)
                        profile_clicked = True
                        self.logger.info(f"Profile clicked via: {sel}")
                        break
                    except Exception:
                        continue

                if not profile_clicked:
                    screenshot = safe_screenshot(page, self.settings.logs_dir, "profile_not_found")
                    return PublishResult(ok=False, error="Profile icon not found", screenshot_path=screenshot)

                # ШАГ 3: Кликаем "Создать публикацию"
                self.logger.info("Step 3: Clicking 'Создать публикацию'")
                create_pub_btn = page.locator("button:has-text('Создать публикацию')").first
                if create_pub_btn.is_visible():
                    create_pub_btn.click()
                    sleep_rand(page, 1.0, 2.0)
                else:
                    screenshot = safe_screenshot(page, self.settings.logs_dir, "create_pub_not_found")
                    return PublishResult(ok=False, error="'Создать публикацию' not found", screenshot_path=screenshot)

                # ШАГ 4: Кликаем "Написать статью"
                self.logger.info("Step 4: Clicking 'Написать статью'")
                article_clicked = False
                article_selectors = [
                    "button:has-text('Создать статью')",
                    "button:has-text('Написать статью')",
                    "button:has-text('Статья')",
                    "a:has-text('Создать статью')",
                    "a:has-text('Написать статью')",
                ]
                for sel in article_selectors:
                    try:
                        loc = page.locator(sel).first
                        if loc.is_visible():
                            loc.click()
                            sleep_rand(page, 2.0, 3.0)
                            article_clicked = True
                            self.logger.info(f"Article editor opened via: {sel}")
                            break
                    except Exception:
                        continue

                if not article_clicked:
                    screenshot = safe_screenshot(page, self.settings.logs_dir, "article_btn_not_found")
                    return PublishResult(ok=False, error="'Создать статью' not found", screenshot_path=screenshot)

                sleep_rand(page, 2.0, 3.0)

                # Редактор может открыться в новой вкладке и грузится долго на слабом VPS
                editor_page = self._wait_for_editor_page(context, page)
                if editor_page is None:
                    self.logger.warning(
                        f"Editor fields never appeared. Pages: {[p.url for p in context.pages]}"
                    )
                    screenshot = safe_screenshot(page, self.settings.logs_dir, "editor_not_loaded")
                    return PublishResult(
                        ok=False,
                        error="Editor did not load (no DraftEditor fields)",
                        screenshot_path=screenshot,
                    )
                page = editor_page
                page.bring_to_front()
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

    def _wait_for_editor_page(self, context, current_page, timeout_s: float = 60.0):
        """Ищет вкладку с загрузившимся редактором (есть DraftEditor-поля).

        Редактор может открыться в новой вкладке, а на слабом VPS его
        JS-бандл грузится десятки секунд — поэтому опрашиваем все вкладки.
        """
        selector = 'div.notranslate.public-DraftEditor-content[role="textbox"]'
        deadline = timeout_s * 1000
        waited = 0.0
        while waited < deadline:
            for p in context.pages:
                try:
                    if p.locator(selector).count() >= 2:
                        return p
                except Exception:
                    continue
            current_page.wait_for_timeout(2000)
            waited += 2000
            self.logger.info(f"Waiting for editor... {int(waited/1000)}s, pages={len(context.pages)}")
        return None

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
        # ШАГ 1: Найти все DraftEditor поля и разделить по Y-позиции
        # ================================================================
        self.logger.info("Step 1: Locating editor fields")
        sleep_rand(page, 1.0, 2.0)

        try:
            fields = page.evaluate("""
                () => {
                    const els = document.querySelectorAll(
                        'div.notranslate.public-DraftEditor-content[role="textbox"]'
                    );
                    return Array.from(els).map((el, i) => {
                        const r = el.getBoundingClientRect();
                        return {index: i, x: r.x, y: r.y, width: r.width, height: r.height};
                    });
                }
            """)
            self.logger.info(f"Found DraftEditor fields: {fields}")
        except Exception as e:
            screenshot = safe_screenshot(page, self.settings.logs_dir, "fields_not_found")
            return PublishResult(ok=False, error=f"Cannot locate editor fields: {e}", screenshot_path=screenshot)

        if len(fields) < 2:
            screenshot = safe_screenshot(page, self.settings.logs_dir, "fields_not_enough")
            return PublishResult(ok=False, error=f"Expected 2 fields, got {len(fields)}", screenshot_path=screenshot)

        fields_sorted = sorted(fields, key=lambda f: f["y"])
        title_idx = fields_sorted[0]["index"]
        content_idx = fields_sorted[1]["index"]
        self.logger.info(f"Title field index={title_idx}, content field index={content_idx}")

        # ================================================================
        # ШАГ 2: Вставить заголовок через буфер обмена (Ctrl+V)
        # ================================================================
        self.logger.info("Step 2: Filling title")
        try:
            title_loc = page.locator(
                'div.notranslate.public-DraftEditor-content[role="textbox"]'
            ).nth(title_idx)
            title_loc.click()
            sleep_rand(page, 0.5, 1.0)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            sleep_rand(page, 0.3, 0.5)

            pyperclip.copy(title)
            page.keyboard.press("Control+V")
            sleep_rand(page, 0.5, 1.0)
            self.logger.info("Title pasted via clipboard")
        except Exception as e:
            screenshot = safe_screenshot(page, self.settings.logs_dir, "title_error")
            return PublishResult(ok=False, error=f"Title error: {e}", screenshot_path=screenshot)

        sleep_rand(page, 1.0, 1.5)

        # ================================================================
        # ШАГ 3: Загрузка обложки через file chooser
        # ================================================================
        if image_path and Path(image_path).exists():
            self.logger.info(f"Step 3: Uploading cover image: {image_path}")
            try:
                # Кликаем в поле контента чтобы появилась иконка +
                content_loc = page.locator(
                    'div.notranslate.public-DraftEditor-content[role="textbox"]'
                ).nth(content_idx)
                content_loc.click()
                sleep_rand(page, 0.5, 1.0)
                page.keyboard.press("Control+Home")
                sleep_rand(page, 0.5, 1.0)

                # Ищем кнопку + (добавить блок)
                plus_selectors = [
                    '[class*="editorBlockButton"]',
                    '[class*="block-button"]',
                    '[class*="blockButton"]',
                    '[class*="side-toolbar"]',
                    '[class*="sideToolbar"]',
                    '[class*="addButton"]',
                ]

                clicked = False
                for sel in plus_selectors:
                    try:
                        btn = page.locator(sel).first
                        if btn.count() > 0 and btn.is_visible():
                            btn.click()
                            sleep_rand(page, 0.3, 0.5)
                            self.logger.info(f"Clicked + button: {sel}")
                            clicked = True
                            break
                    except:
                        continue

                if clicked:
                    sleep_rand(page, 0.3, 0.5)
                    img_selectors = [
                        '[class*="image-popup"]',
                        '[class*="imageButton"]',
                        '[class*="image"]',
                        '[aria-label*="зображени"]',
                        '[title*="зображени"]',
                    ]
                    for sel in img_selectors:
                        try:
                            btn = page.locator(sel).first
                            if btn.count() > 0 and btn.is_visible():
                                btn.click()
                                self.logger.info(f"Clicked image button: {sel}")
                                sleep_rand(page, 0.5, 1.0)
                                break
                        except:
                            continue

                # Теперь popup открыт — кликаем на кнопку "Загрузите файл"
                with page.expect_file_chooser(timeout=10000) as fc_info:
                    upload_btn = page.locator('[class*="image-popup__fileButton"]').first
                    upload_btn.click()
                    self.logger.info("Clicked 'Загрузите файл' button")

                # Загружаем файл через перехваченный file chooser
                file_chooser = fc_info.value
                file_chooser.set_files(str(image_path))
                sleep_rand(page, 2.0, 3.0)
                self.logger.info("Cover image uploaded successfully")

                # Ждём пока файл загрузится на сервер и popup закроется
                self.logger.info("Waiting for file to upload and popup to close...")
                try:
                    # Ждём исчезновения кнопки "Загрузите файл"
                    page.wait_for_selector(
                        '[class*="image-popup__fileButton"]',
                        state="hidden",
                        timeout=15000
                    )
                    self.logger.info("File uploaded, popup closed")
                except:
                    self.logger.warning("Upload timeout, trying Escape")
                    page.keyboard.press("Escape")
                    sleep_rand(page, 1.0, 1.5)

                sleep_rand(page, 1.5, 2.0)

            except Exception as e:
                self.logger.warning(f"Cover upload failed (non-critical): {e}")
                safe_screenshot(page, self.settings.logs_dir, "cover_fail")
        else:
            self.logger.info("No cover image, skipping")

        sleep_rand(page, 1.0, 1.5)


        # ШАГ 4: Вставить контент
        # ================================================================
        self.logger.info("Step 4: Filling content")
        try:
            content_loc = page.locator(
                'div.notranslate.public-DraftEditor-content[role="textbox"]'
            ).nth(content_idx)
            content_loc.click()
            sleep_rand(page, 0.5, 1.0)
            page.keyboard.press("Control+A")
            page.keyboard.press("Control+End")
            sleep_rand(page, 0.3, 0.5)

            # Форсируем фокус через JS
            page.evaluate(f"""
                () => {{
                    const editors = document.querySelectorAll(
                        'div.notranslate.public-DraftEditor-content[role="textbox"]'
                    );
                    if (editors.length > {content_idx}) {{
                        const el = editors[{content_idx}];
                        el.focus();
                        const sel = window.getSelection();
                        const range = document.createRange();
                        range.selectNodeContents(el);
                        range.collapse(false);
                        sel.removeAllRanges();
                        sel.addRange(range);
                    }}
                }}
            """)
            sleep_rand(page, 0.3, 0.5)

            # Печатаем по абзацам с Shift+Enter между ними
            paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
            self.logger.info(f"Typing {len(paragraphs)} paragraphs")

            for i, para in enumerate(paragraphs):
                # Печатаем абзац кусками
                for j in range(0, len(para), 500):
                    page.keyboard.type(para[j:j+500], delay=0)
                    sleep_rand(page, 0.02, 0.05)

                # Между абзацами — Shift+Enter (мягкий перенос, без большого отступа)
                if i < len(paragraphs) - 1:
                    page.keyboard.press("Shift+Enter")
                    page.keyboard.press("Shift+Enter")
                    sleep_rand(page, 0.1, 0.2)

            sleep_rand(page, 1.0, 2.0)
            self.logger.info(f"Content typed ({len(content)} chars)")

        except Exception as e:
            screenshot = safe_screenshot(page, self.settings.logs_dir, "content_error")
            return PublishResult(ok=False, error=f"Content error: {e}", screenshot_path=screenshot)

        sleep_rand(page, 1.5, 2.0)
        
        # ================================================================
        # ШАГ 5: Нажать "Опубликовать"
        # ================================================================
        self.logger.info("Step 5: Publishing")
        publish_selectors = [
            "button:has-text('Опубликовать')",
            "button:has-text('Publish')",
            "[data-testid='publish-button']",
        ]
        publish_clicked = False
        for selector in publish_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible():
                    btn.click()
                    sleep_rand(page, 2.0, 3.0)
                    publish_clicked = True
                    self.logger.info(f"Publish clicked via: {selector}")
                    break
            except Exception:
                continue

        if not publish_clicked:
            screenshot = safe_screenshot(page, self.settings.logs_dir, "publish_btn_not_found")
            return PublishResult(ok=False, error="Publish button not found", screenshot_path=screenshot)

        # После первого клика ждём диалог подтверждения
        sleep_rand(page, 2.0, 3.0)
        try:
            # Ждём появления диалога
            page.wait_for_selector(
                "button:has-text('Опубликовать')",
                timeout=10000
            )
            sleep_rand(page, 1.0, 1.5)

            # Берём все кнопки и кликаем последнюю видимую
            dialog_publish_buttons = page.locator("button:has-text('Опубликовать')").all()
            self.logger.info(f"Found {len(dialog_publish_buttons)} publish buttons after first click")

            for btn in reversed(dialog_publish_buttons):
                try:
                    if btn.is_visible():
                        btn.click()
                        self.logger.info("Clicked final publish button in dialog")
                        sleep_rand(page, 4.0, 5.0)
                        break
                except:
                    continue
        except Exception as e:
            self.logger.warning(f"Failed to click dialog publish button: {e}")

        # Проверяем URL
        final_url = page.url
        self.logger.info(f"Final URL: {final_url}")

        if "/a/" in final_url:
            self.logger.info("URL contains /a/ — published successfully")
            return PublishResult(ok=True, url=final_url)

        # URL всё ещё /edit — пробуем ещё раз
        self.logger.warning("URL still /edit — trying one more publish click")
        try:
            btn = page.locator("button:has-text('Опубликовать')").first
            if btn.is_visible():
                btn.click()
                sleep_rand(page, 4.0, 5.0)
                final_url = page.url
                self.logger.info(f"Final URL after retry: {final_url}")
        except Exception as e:
            self.logger.warning(f"Retry publish failed: {e}")

        if "/a/" in final_url:
            self.logger.info("Published successfully after retry")
            return PublishResult(ok=True, url=final_url)
        else:
            self.logger.warning(f"Published but URL is /edit: {final_url}")
            return PublishResult(ok=True, url=final_url)

        # ================================================================
        # ШАГ 6: Проверяем успех
        # ================================================================
        sleep_rand(page, 3.0, 5.0)
        current_url = page.url
        self.logger.info(f"Final URL: {current_url}")

        success_texts = ["Опубликовано", "Статья опубликована", "Готово"]
        for text in success_texts:
            try:
                if page.locator(f"text={text}").count() > 0:
                    self.logger.info(f"Success indicator found: {text}")
                    return PublishResult(ok=True, url=current_url)
            except Exception:
                pass

        if current_url != self.settings.dzen_editor_url:
            self.logger.info("URL changed — likely published successfully")
            return PublishResult(ok=True, url=current_url)

        screenshot = safe_screenshot(page, self.settings.logs_dir, "publish_unknown")
        return PublishResult(
            ok=False,
            error="Publish result unknown, check screenshot",
            screenshot_path=screenshot,
        )