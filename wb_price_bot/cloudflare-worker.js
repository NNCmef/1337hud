export default {
  async fetch(request) {
    const incoming = new URL(request.url);

    if (!incoming.pathname.startsWith("/bot")) {
      return new Response("WB Telegram Bot API relay is running", { status: 200 });
    }

    const telegramUrl = new URL(
      incoming.pathname + incoming.search,
      "https://api.telegram.org"
    );

    const headers = new Headers(request.headers);
    headers.set("Host", "api.telegram.org");

    return fetch(telegramUrl, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD"
        ? undefined
        : request.body,
      redirect: "follow",
    });
  },
};
