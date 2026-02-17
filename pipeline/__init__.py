"""
MWP Podcast Generation Pipeline

A modular pipeline for generating podcast episodes from voice prompts.

Modules:
- core: Transcription, script generation, metadata, tagging, embeddings
- tts: Text-to-speech (Chatterbox on Modal GPU)
- audio: Audio processing and episode assembly
- storage: R2 and Wasabi storage
- database: PostgreSQL database operations
- publishing: Publishing orchestration
- llm: LLM provider abstraction (Gemini, OpenRouter)
- config: Configuration and constants
"""

__version__ = "4.0.0"
