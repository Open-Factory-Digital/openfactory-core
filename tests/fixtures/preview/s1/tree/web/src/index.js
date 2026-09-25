// A stand-in for the front end a preview fixture builds: it answers on 3000 and says where its API
// is, which is all a live preview of S1 needs of it.
const http = require("http");

http
  .createServer((req, res) => {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end(`web: the api is at ${process.env.NEXT_PUBLIC_API_URL || "(unset)"}\n`);
  })
  .listen(3000, "0.0.0.0");
