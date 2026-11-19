# Expected migration (hand-written reference)

This is a hand-written example of what a good migration of `../express-users` looks like.
It is **not** produced or used by the application; the agent generates its own code via
the LLM each run. It is used by `backend/tests/test_verification.py` to check that the
verifier accepts a correct migration.

| Express                      | FastAPI                                   |
|------------------------------|-------------------------------------------|
| `app.use(express.json())`    | Built in: Pydantic body models            |
| `express.Router()` + `app.use("/users", r)` | `APIRouter(prefix="/users")` + `include_router` |
| `req.params.id`              | typed path param `user_id: int`           |
| `res.status(404).json(...)`  | `raise HTTPException(404, ...)`           |
| logger middleware            | `@app.middleware("http")`                 |
| error-handling middleware    | `@app.exception_handler(Exception)`       |

Known behaviour difference: missing `name`/`email` gives **422** (Pydantic) instead of **400**.
