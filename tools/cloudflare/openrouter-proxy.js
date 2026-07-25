// Cloudflare Worker: прокси для OpenRouter API (обход гео-блокировки).
// Переадресует все запросы на https://openrouter.ai с сохранением пути,
// метода, заголовков (включая Authorization) и тела.
export default {
  async fetch(request) {
    const url = new URL(request.url);
    url.hostname = "openrouter.ai";
    url.protocol = "https:";
    url.port = "";
    return fetch(new Request(url, request));
  },
};
