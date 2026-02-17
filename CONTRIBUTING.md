# Contributing to MWP Pipeline

Thanks for your interest in contributing to the My Weird Prompts pipeline!

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Set up your environment (see [docs/setup.md](docs/setup.md))
4. Create a feature branch: `git checkout -b my-feature`
5. Make your changes
6. Test locally with `modal serve modal_app/recording_app.py`
7. Submit a pull request

## Guidelines

- Keep changes focused and well-scoped
- Follow existing code patterns and conventions
- All LLM calls should go through the `pipeline/llm/` wrappers
- New pipeline stages should fail open (return original input on error)
- Add safety checks for any new stage that could produce truncated or empty output

## Architecture Principles

- **Fail-open**: Non-critical stages should degrade gracefully, not crash the pipeline
- **Shrinkage guards**: Any text transformation should reject output that shrinks content by more than 15-20%
- **Parallel where possible**: TTS and other independent operations should run in parallel
- **Environment-driven config**: No hardcoded secrets; use `os.environ.get()` with sensible defaults

## Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Steps to reproduce (if applicable)
- Relevant logs or error messages

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
