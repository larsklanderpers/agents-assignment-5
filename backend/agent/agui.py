"""Preserve standard interrupt options when the HTTP adapter clones an agent.

The pinned CopilotKit subclass has a narrower constructor than its AG-UI base;
explicitly accepting the base flags avoids silently losing multi-review support.
"""
from copilotkit import LangGraphAGUIAgent
from langgraph.types import Command


class ApprovalAGUIAgent(LangGraphAGUIAgent):
    def __init__(self, *, name, graph, description=None, config=None,
                 emit_interrupt_outcome=True, enable_legacy_on_interrupt_event=True,
                 emit_raw_events=True, emit_subagent_events=False):
        super().__init__(name=name, graph=graph, description=description, config=config)
        self.emit_interrupt_outcome = emit_interrupt_outcome
        self.enable_legacy_on_interrupt_event = enable_legacy_on_interrupt_event
        self.emit_raw_events = emit_raw_events
        self.emit_subagent_events = emit_subagent_events

    def _build_command_from_agui_resume(self, entries, *, open_interrupts=None):
        # The base adapter emits a generic sentinel for multiple responses.
        # LangGraph's actual fan-out tasks require {interrupt_id: decision}.
        ids = [entry.interrupt_id for entry in entries]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("Each review response needs a unique interrupt id")
        if open_interrupts is not None and not set(ids) <= {i.id for i in open_interrupts}:
            raise ValueError("Review response does not match a pending interrupt")
        return Command(resume={entry.interrupt_id: (
            entry.payload if entry.status == "resolved" else
            {"approved": False, "comments": "Review cancelled"}) for entry in entries})
