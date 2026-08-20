const net = require("net");

const server = net.createServer((client) => {
  const upstream = net.connect({ host: "::1", port: 8976 });
  client.pipe(upstream);
  upstream.pipe(client);
  upstream.on("error", () => client.destroy());
});

server.listen(8976, "127.0.0.1");
