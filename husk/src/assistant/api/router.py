from fastapi import APIRouter

from assistant.api.v1 import (
    agents, automation, calendar, conversations, health, history, llm, logs, mail, mcp, notes, tasks, tools, usage,
)

api_router = APIRouter()
for module in (health, conversations, history, tasks, notes, calendar, mail, agents, automation, mcp, tools, llm, logs, usage):
    api_router.include_router(module.router)
