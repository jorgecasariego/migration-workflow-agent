from fastapi import APIRouter, HTTPException, Response

from app.schemas import User, UserCreate

router = APIRouter(prefix="/users", tags=["users"])

_users: list[User] = [User(id=1, name="Ada Lovelace", email="ada@example.com")]
_next_id = 2


@router.get("/", response_model=list[User])
def list_users(limit: int | None = None) -> list[User]:
    return _users[: limit or len(_users)]


@router.get("/{user_id}", response_model=User)
def get_user(user_id: int) -> User:
    for user in _users:
        if user.id == user_id:
            return user
    raise HTTPException(status_code=404, detail="User not found")


@router.post("/", response_model=User, status_code=201)
def create_user(body: UserCreate) -> User:
    # Express returned 400 for missing fields; FastAPI/Pydantic returns 422 instead.
    global _next_id
    user = User(id=_next_id, **body.model_dump())
    _next_id += 1
    _users.append(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int) -> Response:
    before = len(_users)
    _users[:] = [u for u in _users if u.id != user_id]
    if len(_users) == before:
        raise HTTPException(status_code=404, detail="User not found")
    return Response(status_code=204)
