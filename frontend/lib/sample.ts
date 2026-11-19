// Generated from samples/express-users. Used by the 'Load sample' button.
import type { SourceFile } from "./types";

export const SAMPLE_FILES: SourceFile[] = [
  {
    "path": "server.js",
    "content": "const express = require(\"express\");\nconst usersRouter = require(\"./routes/users\");\n\nconst app = express();\napp.use(express.json());\n\n// Simple request logger middleware\napp.use((req, res, next) => {\n  console.log(`${req.method} ${req.url}`);\n  next();\n});\n\napp.get(\"/health\", (req, res) => {\n  res.json({ status: \"ok\" });\n});\n\napp.use(\"/users\", usersRouter);\n\n// Central error handler\napp.use((err, req, res, next) => {\n  console.error(err);\n  res.status(500).json({ error: \"Internal Server Error\" });\n});\n\nconst PORT = process.env.PORT || 3000;\napp.listen(PORT, () => console.log(`Listening on ${PORT}`));\n"
  },
  {
    "path": "routes/users.js",
    "content": "const express = require(\"express\");\nconst router = express.Router();\n\nlet users = [{ id: 1, name: \"Ada Lovelace\", email: \"ada@example.com\" }];\nlet nextId = 2;\n\n// GET /users?limit=10\nrouter.get(\"/\", (req, res) => {\n  const limit = parseInt(req.query.limit, 10) || users.length;\n  res.json(users.slice(0, limit));\n});\n\n// GET /users/:id\nrouter.get(\"/:id\", (req, res) => {\n  const user = users.find((u) => u.id === Number(req.params.id));\n  if (!user) return res.status(404).json({ error: \"User not found\" });\n  res.json(user);\n});\n\n// POST /users\nrouter.post(\"/\", (req, res) => {\n  const { name, email } = req.body;\n  if (!name || !email) {\n    return res.status(400).json({ error: \"name and email are required\" });\n  }\n  const user = { id: nextId++, name, email };\n  users.push(user);\n  res.status(201).json(user);\n});\n\n// DELETE /users/:id\nrouter.delete(\"/:id\", (req, res) => {\n  const before = users.length;\n  users = users.filter((u) => u.id !== Number(req.params.id));\n  if (users.length === before) return res.status(404).json({ error: \"User not found\" });\n  res.status(204).send();\n});\n\nmodule.exports = router;\n"
  }
];
