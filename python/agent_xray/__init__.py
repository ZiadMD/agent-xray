"""Agent X-Ray: a live, cinematic 3D view of any LangGraph app.

from agent_xray import watch
graph = watch(graph)
graph.invoke({...})
"""

from .watch import WatchedGraph, watch

__all__ = ["WatchedGraph", "watch"]
__version__ = "0.1.0"
