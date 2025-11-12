# Assignment 2 Reflection

Implementing this multi-agent travel planner revealed the importance of clear agent responsibilities and effective inter-agent communication. The Planner Agent creates itineraries from its knowledge base, while the Reviewer Agent validates them using real-time internet search. This separation ensures the planner doesn't rely on potentially outdated information, while the reviewer guarantees accuracy through fact-checking.

The most interesting challenge was designing transparent communication between agents. I implemented a "Delta List" format where the reviewer shows specific issues with clear fixes (e.g., "Louvre visit at 8 PM: Museum closes at 6 PM → Move to 2 PM"). Parsing the reviewer's natural language output to extract these structured change lists was more nuanced than expected, requiring pattern matching for different output formats.

A creative design choice was adding companion interest consideration. When users mention traveling with others, the planner detects companion mentions, extracts their preferences, and balances multiple interests within a single itinerary. For instance, if one person loves history and another prefers nightlife, the planner schedules museums in the morning and evening activities later, or finds activities combining both interests. This goes beyond simple itinerary generation—it requires understanding group dynamics and creatively sequencing activities to satisfy everyone.

Another challenge emerged with environment variables in async contexts. The Tavily API key needed to be available when the reviewer called the internet search tool, but sometimes failed if the environment wasn't properly initialized. I solved this by explicitly reloading environment variables within the tool function using `load_dotenv(override=True)`, ensuring keys are always available when needed.

The UI emphasizes transparency through color-coded sections (amber for changes, blue for validated itineraries) and real-time tool call logging in the sidebar, showing exactly what the reviewer searches for. This visibility builds user trust in the validation process.

---

**External Tools and GenAI Assistance:**

I used OpenAI's GPT-4o model via the `openai-agents` framework for both the Planner and Reviewer agents. The Tavily API was integrated for real-time internet search functionality, allowing the reviewer to fact-check opening hours, ticket prices, and other dynamic information. Streamlit provided the web interface, and python-dotenv managed environment variables for secure API key handling. I used GitHub Copilot and Cursor AI for code completion and debugging assistance, particularly when troubleshooting the async environment variable loading issue and implementing the Delta List parsing logic.

