# discord-chat-report

**English** | [简体中文](README.md)

A local Codex skill for regular Discord members. It recovers locally cached messages from selected channels and forum posts, then uses the current Codex session to create a Chinese summary, an offline HTML report, shareable PNG images, and structured source data.

**Status: local cache recovery prototype. This is not a complete Discord history backup tool.** The reader does not call the Discord API and does not require a bot token or user token. The Python commands do not perform AI summarization by themselves.

## Requirements and setup

Verified locally on Windows 11 with Discord Stable 1.0.9258 and Python 3.13. Other operating systems and Discord versions have not been verified.

```powershell
python -m pip install -r scripts/requirements.txt
python -m unittest discover -s tests -v
python scripts/read_cache.py --list-channels
```

Use this repository as a Codex skill folder. In a Codex session, point Codex to the local `SKILL.md`, or install the whole folder using the skill installation method supported by your Codex host. You can start by using it directly inside the repository without changing global settings.

## Usage

```powershell
# The default window is 24 hours. You can explicitly select 48 or 72 hours.
# Use a new RUN_NAME for every run.
python scripts/read_cache.py --channel "CHANNEL_LINK_OR_ID" --out reports/RUN_NAME
python scripts/read_cache.py --channel "CHANNEL_LINK_OR_ID" --hours 48 --include-threads --out reports/RUN_NAME_48H

# Fixed time range with an explicit time zone: start is inclusive, end is exclusive.
python scripts/read_cache.py --channel "CHANNEL_LINK_OR_ID" --start "2026-09-20T09:00:00+08:00" --end "2026-09-21T09:00:00+08:00" --out reports/RUN_NAME_RANGE
```

Next, ask Codex to read the complete `messages.json`, write the summary to `report.json` according to the [report schema](references/report-schema.md), and run:

```powershell
python scripts/render_report.py reports/RUN_NAME
```

Open `index.html` directly to read the report offline and expand its source excerpts. Share `report.png`; when a report is too long, also share the numbered continuation images. Real reports stay under the Git-ignored `reports/` directory.

For forum channels, Discord must load a thread before its replies can appear in the local cache. Loading content in the normal client and reading files from disk are separate steps. This skill cannot recover content that the client has not loaded or cached.

## Privacy and limitations

- The reader only scans recognizable JSON or gzip message fragments in Discord's local Cache and IndexedDB files.
- It does not read tokens, cookies, Local Storage, process secrets, or account APIs, and it does not use a selfbot.
- Local cache contents may be partial, stale, or missing. An empty result does not prove that a channel had no messages.
- Cache files cannot prove which Discord account produced them. Confirm the active account and channel in the Discord client when accuracy matters.
- The current Codex session performs the semantic reading and summarization. No separate model API key is required, but running the Python scripts alone only exports and renders data.
- Reports are local by default. The project does not publish reports or send Discord messages automatically.

See the [implementation and compatibility notes](references/implementation.md) for the verified technical scope.

## Outputs

Each run produces:

- `messages.json`: structured messages and collection metadata.
- `messages.txt`: readable source text for review.
- `report.json`: structured summary with message ID citations.
- `summary.md`: Chinese summary report.
- `index.html`: self-contained offline report with escaped content and collapsed source excerpts.
- `report.png`: shareable long image; very long reports may continue as `report-02.png`, and so on.
- `verification.json` and `render-verification.json`: collection and rendering verification records.

Every important conclusion must cite an actual message ID. The report ranks useful items by information value and relevance, then uses engagement and recency as supporting signals so low-value noise does not dominate the reading list.

## Publishing to GitHub

Publish only the source code, tests, and fictional examples. Do not commit real reports, Discord cache files, credentials, or content from unrelated projects. Before pushing, inspect both the staged file summary and the full staged diff.

```powershell
git init
git add .gitignore SKILL.md README.md README_EN.md LICENSE agents scripts references tests
git diff --cached --stat
git diff --cached
git commit -m "Add Discord local cache report skill"
git branch -M main
# Create an empty repository in your own GitHub account, then configure its URL.
git remote add origin https://github.com/YOUR_ACCOUNT/discord-chat-report.git
git push -u origin main
```

This project does not automatically publish reports or send messages to Discord.
