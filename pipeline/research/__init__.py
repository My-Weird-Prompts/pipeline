"""
Research module for the MWP podcast pipeline.

Contains:
- Research coordinator (web search, planning)
- Episode memory (cross-episode references)
"""

# Research coordinator (preferred over planning agent)
try:
    from ..generators.research_coordinator import (
        run_research_coordinator,
        gather_research,
        ResearchCoordinator,
        ResearchContext,
    )
except ImportError:
    run_research_coordinator = None
    gather_research = None
    ResearchCoordinator = None
    ResearchContext = None

# Episode memory (cross-episode references)
try:
    from ..generators.episode_memory import (
        get_episode_memory_context,
        refresh_episode_index,
    )
except ImportError:
    get_episode_memory_context = None
    refresh_episode_index = None

# Planning agent (moved to core.script_generation)
try:
    from ..core.script_generation import run_planning_agent
except ImportError:
    run_planning_agent = None

__all__ = [
    # Research coordinator (preferred)
    'run_research_coordinator',
    'gather_research',
    'ResearchCoordinator',
    'ResearchContext',

    # Legacy (use research_coordinator instead)
    'run_planning_agent',

    # Episode memory
    'get_episode_memory_context',
    'refresh_episode_index',
]
