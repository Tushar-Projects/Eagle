import os

# Ensure tests don't load random environment variables.
os.environ["GEMINI_API_KEY"] = "test_api_key"
os.environ["CLAUDE_API_KEY"] = "test_api_key"
os.environ["AI_PROVIDER"] = "mock"
os.environ["DATABASE_PATH"] = "sqlite:///:memory:"
