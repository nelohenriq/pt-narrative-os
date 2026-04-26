"""
pt-media-os — Embedding Prompt Metadata
Version: v1
Task: embeddings (Ollama nomic-embed-text / NIM nv-embedqa-e5-v5)

Note: Embedding models do not use text prompts in the traditional sense.
This file documents the embedding configuration and any prefix/passages used.
"""

# nomic-embed-text uses a task-type prefix for best results.
# For article embedding, we use the "search_document" task type.
EMBEDDING_PREFIX = "search_document: "

# The text sent to the embedding model is:
#   prefix + title + " — " + first_512_chars_of_cleaned_text
# This gives the model enough context for meaningful embeddings
# while staying within the 8192 token context window.

EMBEDDING_TEXT_TEMPLATE = "{prefix}{title} — {body_excerpt}"

# Configuration
EMBEDDING_DIM = 768           # nomic-embed-text output dimension
EMBEDDING_MAX_TOKENS = 8192   # nomic-embed-text context window
EMBEDDING_BODY_CHARS = 512    # chars of body to include in embedding text

EMBEDDING_PROMPT_VERSION = "v1"
