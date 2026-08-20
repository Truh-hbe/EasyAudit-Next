import { createServer } from "node:http";

import { route } from "./app.ts";

const port = Number.parseInt(process.env.PORT ?? "3001", 10);

const server = createServer((request, response) => {
  const result = route(request.method ?? "GET", request.url ?? "/");
  response.writeHead(result.status, result.headers);
  response.end(result.body);
});

server.listen(port, () => {
  console.log(`EasyAudit-Next M0 API listening on http://localhost:${port}`);
});
