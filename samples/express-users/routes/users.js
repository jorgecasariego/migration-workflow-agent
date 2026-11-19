const express = require("express");
const router = express.Router();

let users = [{ id: 1, name: "Ada Lovelace", email: "ada@example.com" }];
let nextId = 2;

// GET /users?limit=10
router.get("/", (req, res) => {
  const limit = parseInt(req.query.limit, 10) || users.length;
  res.json(users.slice(0, limit));
});

// GET /users/:id
router.get("/:id", (req, res) => {
  const user = users.find((u) => u.id === Number(req.params.id));
  if (!user) return res.status(404).json({ error: "User not found" });
  res.json(user);
});

// POST /users
router.post("/", (req, res) => {
  const { name, email } = req.body;
  if (!name || !email) {
    return res.status(400).json({ error: "name and email are required" });
  }
  const user = { id: nextId++, name, email };
  users.push(user);
  res.status(201).json(user);
});

// DELETE /users/:id
router.delete("/:id", (req, res) => {
  const before = users.length;
  users = users.filter((u) => u.id !== Number(req.params.id));
  if (users.length === before) return res.status(404).json({ error: "User not found" });
  res.status(204).send();
});

module.exports = router;
