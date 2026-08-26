import os

# Ensure tests don't load random environment variables.
os.environ["MODEL_API_KEY"] = "test_api_key"
os.environ["MODEL_PROVIDER"] = "test_provider"
os.environ["DATABASE_PATH"] = "sqlite:///:memory:"
