# app.py
"""
Multi-Agent Travel Planner

Highlights:
- Clear separation of concerns (tools, agents, orchestration, UI)
- Simple global logger to display tool calls live in the sidebar
- Planner → Reviewer pipeline enforced before rendering any answer
- Minimal dependencies and straightforward control flow
"""

from __future__ import annotations

import os
import asyncio
import time
from typing import Callable, Dict, List, Optional, Any

import streamlit as st
from dotenv import load_dotenv
from tavily import TavilyClient

# ──────────────────────────────────────────────────────────────────────────────
# Environment & Globals
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()  # Loads variables from a local .env if present
os.environ.setdefault("OPENAI_LOG", "error")
os.environ.setdefault("OPENAI_TRACING", "false")

# Tool call logger: the UI sets this per request. The tool checks it and logs.
# Using a simple global makes this easy to teach and reason about.
TOOL_LOGGER: Optional[Callable[[Dict[str, Any]], None]] = None


def set_tool_logger(logger: Optional[Callable[[Dict[str, Any]], None]]) -> None:
    """Install or remove the UI logger used by tools to report activity."""
    global TOOL_LOGGER
    TOOL_LOGGER = logger


def log_tool_event(event: Dict[str, Any]) -> None:
    """If a logger is installed, send the event to the UI."""
    if TOOL_LOGGER is not None:
        try:
            TOOL_LOGGER(event)
        except Exception:
            # Logging should never break the app or the tool itself
            pass


def redact_for_logs(value: Any) -> Any:
    """
    Make sure we don't leak secrets and keep logs small.
    This is deliberately simple for teaching.
    """
    if isinstance(value, str):
        low = value.lower()
        if any(k in low for k in ("api_key", "token", "secret", "password")):
            return "[redacted]"
        return value if len(value) <= 300 else value[:120] + "… [truncated]"
    if isinstance(value, dict):
        return {k: ("[redacted]" if any(s in k.lower() for s in ("key", "token", "secret", "password"))
                    else redact_for_logs(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_logs(v) for v in value]
    return value


# ──────────────────────────────────────────────────────────────────────────────
# Agent Framework Imports (provided by you)
# ──────────────────────────────────────────────────────────────────────────────
# These come from your own framework. We assume:
# - Agent: defines a model + instructions + optional tools
# - Runner.run(agent, input): executes an agent and returns an object with text
from agents import Agent, Runner, function_tool  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────────────

@function_tool
def internet_search(query: str) -> str:
    """
    Internet search backed by Tavily.
    - Reads TAVILY_API_KEY from environment.
    - Sends simple log events before/after the call so the UI can show activity.
    """
    log_tool_event({"type": "call", "tool": "internet_search", "args": {"query": redact_for_logs(query)}})

    try:
        # Reload environment variables to ensure they're available
        load_dotenv(override=True)
        api_key = os.getenv("TAVILY_API_KEY")
        
        if not api_key:
            msg = "missing TAVILY_API_KEY in environment."
            log_tool_event({"type": "error", "tool": "internet_search", "error": msg})
            return f"Search error: {msg}"

        # Initialize client with explicit API key
        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=3)

        items = response.get("results", [])
        lines = [f"- {it.get('title', 'N/A')}: {it.get('content', 'N/A')}" for it in items]
        output = "\n".join(lines) if lines else "No results found."

        log_tool_event({
            "type": "result",
            "tool": "internet_search",
            "preview": redact_for_logs(output[:400] + ("…" if len(output) > 400 else "")),
        })
        return output

    except Exception as e:
        error_msg = str(e)
        log_tool_event({"type": "error", "tool": "internet_search", "error": error_msg})
        # Provide more helpful error message
        if "API key" in error_msg or "Unauthorized" in error_msg:
            return f"Search error: Invalid Tavily API key. Please check your TAVILY_API_KEY in the .env file. Error: {error_msg}"
        return f"Search error: {error_msg}"

    finally:
        log_tool_event({"type": "end", "tool": "internet_search"})


# ──────────────────────────────────────────────────────────────────────────────
# Agents
# ──────────────────────────────────────────────────────────────────────────────

# BEGIN SOLUTION
REVIEWER_INSTRUCTIONS = """
You are a Travel Plan Reviewer Agent. Your role is to review and validate travel itineraries created by a Planner Agent before they are shown to the user.

Your primary responsibilities:
1. **Feasibility Check**: Verify that activities are realistic and feasible
   - Check opening hours of museums, attractions, restaurants
   - Verify ticket prices and availability
   - Validate travel times between locations
   - Ensure activities can actually be completed in the allocated time

2. **Identify Issues**: Find unrealistic or conflicting activities
   - Activities scheduled during closed hours
   - Unrealistic travel times or distances
   - Budget overruns or incorrect price estimates
   - Conflicting activities (e.g., two places at the same time)
   - Missing essential information (transportation, meals, etc.)

3. **Use Internet Search**: Use the internet_search tool for real-time fact-checking
   - Verify current ticket prices and availability
   - Check opening hours and days of operation
   - Validate travel times and distances between locations
   - Confirm current information about attractions, restaurants, etc.

4. **Create Delta List**: For any issues found, create a "Delta List" with:
   - Specific changes needed (what to change)
   - Clear reasons for each change (why it's needed)
   - Concrete fixes or corrections

Your output format:
1. **Delta List** (if issues found):
   - List each issue as: "[Issue]: [Reason] → [Fix]"
   - Be specific and actionable
   - Example: "Louvre visit at 8 PM: Museum closes at 6 PM → Move to 2 PM"

2. **Validated Itinerary**:
   - If issues were found, provide the corrected itinerary
   - If no issues, confirm the plan is valid
   - Maintain the same clear, structured format as the original
   - Include brief notes on what was verified via internet search

Be thorough and use internet search liberally to ensure accuracy. Your goal is to catch errors before the user sees the plan.
"""

PLANNER_INSTRUCTIONS = """
You are a Travel Planner Agent. Your role is to transform a user's travel prompt into a detailed, day-by-day itinerary.

Your task:
Take a vague travel prompt (e.g., "Plan a week-long Europe trip for a student on a $1,500 budget who loves history and food, traveling with a friend who enjoys art and nightlife") and expand it into a comprehensive travel plan that considers all travelers' interests.

Requirements for your itinerary:

1. **Day-by-Day Structure**: 
   - Organize activities by day
   - Include approximate times for each activity
   - Specify locations clearly

2. **Essential Components**:
   - Day-by-day activities with approximate times and locations
   - Estimated costs for each major expense (accommodations, activities, meals, transportation)
   - City clusters (group activities by geographic proximity)
   - Logistics (transportation between cities/locations, check-in/check-out times)

3. **User Constraints**:
   - Respect the stated budget (break down costs and ensure total stays within budget)
   - Honor specific dates or duration mentioned
   - **Incorporate user interests**: Identify and include activities that match the user's stated interests (e.g., history, food, art, nature, adventure, shopping, nightlife)
   - **Consider companions' interests**: If the user mentions traveling with companions (family, friends, partner, children, etc.), identify their interests and preferences, and create a balanced itinerary that accommodates both the user's and companions' interests
   - Balance activities to ensure everyone in the travel group has engaging experiences
   - Match the pacing preference (relaxed, moderate, or fast-paced)

4. **Format**:
   - Present the plan in a clear, structured format that's easy to read
   - Use headings, bullet points, and clear sections
   - Include a summary with total estimated costs
   - Make it visually organized and scannable

Important constraints:
- **No internet access**: You work entirely from your own knowledge
- Be realistic with time estimates and travel logistics
- Consider practical factors like meal times, rest, and travel between locations
- **Provide a balanced mix of activities** that match both the user's and any companions' interests
- When companions are mentioned, ensure the itinerary includes activities that appeal to different interests within the group
- If interests conflict, find creative ways to balance them (e.g., morning activity for one interest, afternoon for another, or activities that combine multiple interests)

Your output should be a complete, ready-to-use travel itinerary that a user could follow.
"""

reviewer_agent = Agent(
    name="Reviewer Agent",
    model="openai.gpt-4o",
    instructions=REVIEWER_INSTRUCTIONS.strip(),
    tools=[internet_search]
)

planner_agent = Agent(
    name="Planner Agent",
    model="openai.gpt-4o",
    instructions=PLANNER_INSTRUCTIONS.strip(),
)

# END SOLUTION


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration Helpers
# ──────────────────────────────────────────────────────────────────────────────

def extract_text(result_obj: Any) -> str:
    """
    Pull a usable string from the Runner result in a tolerant way.
    Your Runner may expose final_output, text, or __str__.
    """
    return (
        getattr(result_obj, "final_output", None)
        or getattr(result_obj, "text", None)
        or str(result_obj)
    )


def run_planner(user_text: str) -> str:
    """Run the Planner and return its itinerary text."""
    result = asyncio.run(Runner.run(planner_agent, user_text))
    return extract_text(result)


def run_reviewer(plan_text: str) -> str:
    """Run the Reviewer on the planner’s output and return validated text."""
    result = asyncio.run(Runner.run(reviewer_agent, plan_text))
    return extract_text(result)


# ──────────────────────────────────────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Travel Planner", 
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
    <style>
    .main-header {
        background: linear-gradient(90deg, #1f77b4 0%, #ff7f0e 100%);
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 1rem;
    }
    .delta-list {
        background-color: #fef3c7;
        border-left: 4px solid #f59e0b;
        padding: 1.5rem;
        margin: 1rem 0;
        border-radius: 8px;
        color: #1f2937;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .delta-list h3, .delta-list h4, .delta-list strong {
        color: #92400e;
    }
    .delta-list p, .delta-list li {
        color: #374151;
        line-height: 1.6;
    }
    .validated-itinerary {
        background-color: #eff6ff;
        border-left: 4px solid #3b82f6;
        padding: 1.5rem;
        margin: 1rem 0;
        border-radius: 8px;
        color: #1f2937;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .validated-itinerary h3, .validated-itinerary h4, .validated-itinerary strong {
        color: #1e40af;
    }
    .validated-itinerary p, .validated-itinerary li {
        color: #374151;
        line-height: 1.6;
    }
    </style>
""", unsafe_allow_html=True)

st.title("✈️ Multi-Agent Travel Planner")
st.markdown("**Transform your travel ideas into validated, day-by-day itineraries**")
st.caption("🤖 Planner Agent creates the plan → 🔎 Reviewer Agent validates with real-time fact-checking")

# Sidebar: session controls + examples + dev panel
with st.sidebar:
    st.header("📋 Session Controls")
    if st.button("🔄 Reset Conversation", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    
    st.divider()
    
    st.subheader("💡 Example Prompts")
    example_prompts = [
        "Plan a week-long Europe trip for a student on a $1,500 budget who loves history and food",
        "3-day Paris trip for art lovers with $800 budget",
        "5-day Tokyo itinerary for food enthusiasts, budget $2,000",
        "Weekend getaway to New York City, $500 budget, interested in museums and Broadway"
    ]
    
    for i, prompt in enumerate(example_prompts):
        if st.button(f"📌 Example {i+1}", key=f"example_{i}", use_container_width=True):
            st.session_state.example_prompt = prompt
    
    st.divider()
    
    st.subheader("🔧 Developer View")
    show_tools = st.toggle("Show tool activity (live)", value=True)
    if show_tools:
        tool_expander = st.expander("🔧 Tool Activity", expanded=True)
        tool_panel = tool_expander.container()
    else:
        tool_panel = st.container()  # inert sink
    
    st.divider()
    st.markdown("**About**")
    st.info("""
    This app uses two AI agents:
    - **Planner**: Creates detailed itineraries
    - **Reviewer**: Validates with internet search
    """)

# Helper function to parse Delta List and Itinerary from reviewer output
def parse_reviewer_output(review_text: str) -> tuple[Optional[str], str]:
    """
    Parse the reviewer output to extract Delta List and Validated Itinerary.
    Returns (delta_list, validated_itinerary)
    """
    delta_list = None
    validated_itinerary = review_text
    
    # Look for Delta List section
    if "**Delta List**" in review_text or "Delta List" in review_text:
        # Try to extract delta list
        parts = review_text.split("**Validated Itinerary**")
        if len(parts) > 1:
            delta_list = parts[0].replace("**Delta List**", "").replace("Delta List", "").strip()
            validated_itinerary = parts[1].strip()
        else:
            # Alternative format: look for "Delta List" followed by itinerary
            parts = review_text.split("2. **Validated Itinerary**")
            if len(parts) > 1:
                delta_list = parts[0].replace("1. **Delta List**", "").replace("**Delta List**", "").strip()
                validated_itinerary = parts[1].strip()
    
    return delta_list, validated_itinerary

# Session state for chat history
if "messages" not in st.session_state:
    st.session_state.messages = []  # list[dict(role, content)]
    st.session_state.meta = []      # list[dict(trace)]
    
    # Show welcome message for first-time users
    with st.chat_message("assistant"):
        st.markdown("""
        👋 **Welcome to the Multi-Agent Travel Planner!**
        
        I can help you create detailed, validated travel itineraries. Just describe:
        - Your destination(s)
        - Duration of trip
        - Budget
        - Your interests (history, food, art, nature, etc.)
        
        The Planner Agent will create a day-by-day itinerary, and the Reviewer Agent will validate it with real-time fact-checking to ensure accuracy!
        """)

# Render history
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        # Check if this is a reviewer output with delta list
        if msg["role"] == "assistant" and "delta_list" in msg:
            delta_list = msg.get("delta_list")
            validated_itinerary = msg.get("content", "")
            
            if delta_list:
                st.markdown("### 🔍 Changes Made (Delta List)")
                st.markdown(f'<div class="delta-list">{delta_list}</div>', unsafe_allow_html=True)
                st.divider()
            
            st.markdown("### ✅ Validated Itinerary")
            st.markdown(f'<div class="validated-itinerary">{validated_itinerary}</div>', unsafe_allow_html=True)
        else:
            st.markdown(msg["content"])
        
        if msg["role"] == "assistant" and i < len(st.session_state.meta):
            meta = st.session_state.meta[i]
            if meta:
                st.caption(meta.get("trace", ""))

# Handle example prompt from sidebar
user_input = None
if "example_prompt" in st.session_state:
    user_input = st.session_state.example_prompt
    del st.session_state.example_prompt

# Chat input
if user_input is None:
    user_input = st.chat_input("Describe your travel (destination, duration, budget, interests)…")

if user_input:
    # Add user message to history and render it
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.session_state.meta.append(None)
    with st.chat_message("user"):
        st.markdown(user_input)

    # Assistant output block
    with st.chat_message("assistant"):
        # Live “working…” text and progress bar
        live_msg = st.empty()
        progress = st.progress(0)

        # Per-request tool log (shown in the sidebar)
        tool_events: List[Dict[str, Any]] = []

        def ui_tool_logger(event: Dict[str, Any]) -> None:
            """Append an event and re-render the sidebar log."""
            tool_events.append(event)
            with tool_panel:
                st.markdown("**Recent tool calls**")
                for ev in tool_events[-60:]:  # last N entries
                    t = ev.get("tool", "unknown")
                    et = ev.get("type", "event")
                    if et == "call":
                        st.write(f"• **{t}** called with `{ev.get('args')}`")
                    elif et == "result":
                        st.write(f"• **{t}** result preview:\n\n> {ev.get('preview')}")
                    elif et == "error":
                        st.error(f"• **{t}** error: {ev.get('error')}")
                    elif et == "end":
                        st.write(f"• **{t}** finished")

        # Install the logger so tools can report to the sidebar
        set_tool_logger(ui_tool_logger)

        try:
            # Optional: clear sidebar panel on each run
            with tool_panel:
                st.empty()

            # Step 1: Planner
            with st.status("🧭 Planner Agent: generating itinerary…", expanded=True) as status:
                live_msg.markdown("🧭 Planner Agent is creating your itinerary…")
                plan_text = run_planner(user_input)
                progress.progress(40)
                status.update(label="🔎 Reviewer Agent: validating with live searches…", state="running")

            # Step 2: Reviewer (tool calls will appear live in sidebar)
            live_msg.markdown("🔎 Reviewer Agent is validating the plan with live searches…")
            review_text = run_reviewer(plan_text)
            progress.progress(90)

            # Completed
            live_msg.markdown("✅ Validation complete. Rendering results…")
            time.sleep(0.2)
            progress.progress(100)

            # Parse reviewer output to extract Delta List and Validated Itinerary
            delta_list, validated_itinerary = parse_reviewer_output(review_text)
            
            # Clear the progress indicators
            live_msg.empty()
            progress.empty()

            # Display Delta List if present
            if delta_list:
                st.markdown("### 🔍 Changes Made (Delta List)")
                st.markdown(f'<div class="delta-list">{delta_list}</div>', unsafe_allow_html=True)
                st.divider()
            
            # Display Validated Itinerary
            st.markdown("### ✅ Validated Itinerary")
            st.markdown(f'<div class="validated-itinerary">{validated_itinerary}</div>', unsafe_allow_html=True)
            
            # Expandable sections for more details
            with st.expander("📋 See Original Plan from Planner Agent"):
                st.markdown(plan_text)
            
            with st.expander("🔍 See Full Reviewer Output"):
                st.markdown(review_text)

            # Save to history with delta list info
            st.session_state.messages.append({
                "role": "assistant", 
                "content": validated_itinerary,
                "delta_list": delta_list
            })
            st.session_state.meta.append({"trace": "Planner Agent → Reviewer Agent"})
            st.caption("✅ Validated by Reviewer Agent with real-time fact-checking")

        except Exception as e:
            # Friendly error box
            live_msg.markdown("❌ Something went wrong.")
            err = f"⚠️ Error while processing your request:\n\n```\n{e}\n```"
            st.markdown(err)
            st.session_state.messages.append({"role": "assistant", "content": err})
            st.session_state.meta.append({"trace": "Runtime error."})

        finally:
            # Always remove the logger so it doesn't leak into the next request
            set_tool_logger(None)
