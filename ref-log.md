# Assignment 2 Reflection

**Link to Submission Repo:** https://github.com/aryan0821/INFO-5940-Codespace-assignment-2

Building the multi-agent travel planner taught me how critical clear roles and communication are between agents. The Planner Agent builds itineraries from its internal knowledge, while the Reviewer Agent verifies them with live web data. This separation keeps planning efficient (not too many unnecessary and redundant tool calls) and ensures accuracy through real-time validation.

The biggest challenge was making agent communication transparent and structured. I used a "Delta List" format as mentioned in the docs, where the reviewer pinpoints issues and suggests direct fixes (e.g., "Louvre visit at 8 PM: closes at 6 → move to 2 PM"). Parsing these natural language corrections into structured updates turned out to be tricky, requiring flexible pattern matching for varied outputs.

A favorite feature that I added from personal experience was companion-aware planning. When users mention traveling with others, the system extracts each person's interests and balances them say, museums in the morning for history lovers and nightlife later for others. It made the planner feel more personal and realistic.

One unexpected issue was environment handling in async contexts. The Tavily API key sometimes failed to load when the reviewer ran searches. Reloading environment variables within the tool (load_dotenv(override=True)) fixed it reliably.

The UI focuses on transparency: color-coded sections (amber for suggested changes, blue for verified plans) and a sidebar showing live tool calls. This helps users see what the agents are doing and builds trust in their results.

## Tools and Assistance

Cursor helped with debugging, especially around async environment loading and Delta List parsing. I also used it for UI styling on streamlit a bit.
