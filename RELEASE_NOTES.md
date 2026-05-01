# Release Notes

> Auto-generated from git history. Updated on every push to `main`.

## May 01, 2026

### Features
- Add persistent fetch run tracking and broaden test coverage (`e93d0c4`)

### Bug Fixes
- Fix reliability: decouple article and narrative saves into two transactions (`ca167f4`)
- Fix daily scheduler timezone and prevent blank narrative saves (`7a68c4b`)

## April 30, 2026

### Improvements
- Harden narrative generation retries and surface fetch failures in UI (`2deadfd`)

## April 29, 2026

### Features
- Add startup diagnostics, fetch lifecycle logging, and smoke tests (`956679e`)

### Improvements
- Apply Claude design system: warm cream canvas, coral CTAs, dark narrative panel (`ced2ab9`)

### Changes
- Update README to reflect GPT-5.5 usage (`1e09f72`)
- Update GPT version in README description (`d7555bc`)
- Upgrade to GPT-5.5 and add auto-refresh during fetch (`40c737b`)

### Bug Fixes
- Fix OpenAI completion parameter and sync remaining local changes (`586700b`)
- Strip markdown fences at render time to fix existing DB records (`b8335d7`)
- Strip markdown code fences from OpenAI narrative response (`13001a4`)

## April 28, 2026

### Features
- Add Pylint workflow for Python code analysis (`834e8d8`)
- Convert to Flask webapp with SQLite storage and Bootstrap UI (`e5720d7`)

### Changes
- Switch from Anthropic to OpenAI (gpt-4o) for narrative generation (`e3153ec`)

## April 27, 2026

### Features
- Add NewsNarrative app: fetch daily top-10 news and build AI narrative (`3662d1f`)

### Other
- Initial commit (`3655f55`)
