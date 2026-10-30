"""
FastAPI server for the Financial Approval System.

Follows the official CopilotKit + LangGraph FastAPI quickstart pattern:
https://docs.copilotkit.ai/langgraph/quickstart?agent=bring-your-own
"""

import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from backend.agent.agui import ApprovalAGUIAgent
from backend.agent.checkpointer import create_async_checkpointer
from backend.config import LANGSMITH_API_KEY, LANGSMITH_PROJECT
from backend.agent.activity import ActivityStore

# Enable LangSmith tracing if configured
if LANGSMITH_API_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT


def build_graph(checkpointer, event_store=None):
    """Try the student's graph first; fall back to the demo graph."""
    try:
        from backend.agent.graph import create_approval_graph
        graph = create_approval_graph(checkpointer=checkpointer, event_store=event_store)
        print("[server] Loaded student approval graph")
    except Exception as exc:
        from backend.agent.demo_graph import create_demo_graph
        graph = create_demo_graph(checkpointer=checkpointer)
        print(f"[server] Student graph not ready ({type(exc).__name__}), using demo graph")
    return graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    # AG-UI calls the graph's async API, so the checkpointer must be the async
    # AsyncSqliteSaver, which has to be opened inside the running event loop.
    async with create_async_checkpointer() as checkpointer:
        app.state.activity_store = ActivityStore()
        routes_before = list(app.router.routes)
        agent = ApprovalAGUIAgent(
            name="approval_agent", description="Financial approval workflow agent",
            graph=build_graph(checkpointer, app.state.activity_store),
        )
        # Attach the LangGraph agent as an AG-UI endpoint (official CopilotKit pattern)
        add_langgraph_fastapi_endpoint(
            app=app,
            agent=agent,
            path="/",
        )
        try:
            yield
        finally:
            # Drop the endpoint bound to this checkpointer before it closes, so a
            # second startup in the same process (e.g. tests) registers a fresh one.
            app.router.routes[:] = routes_before


# FastAPI app
app = FastAPI(title="Financial Approval System", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "financial-approval-system"}


@app.get("/bonus/dashboard")
def dashboard():
    return app.state.activity_store.dashboard()


@app.get("/bonus/audit/{run_id}")
def audit(run_id: str):
    record = app.state.activity_store.audit(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return record


@app.get("/bonus/export")
def export_audit():
    return JSONResponse(app.state.activity_store.export(), headers={
        "Content-Disposition": 'attachment; filename="approval-audit.json"'})


if __name__ == "__main__":
    uvicorn.run("backend.server:app", host="0.0.0.0", port=8000, reload=True)
