# Letting an AI agent use the app

[← Back to the README](../../README.md)

An AI agent that supports MCP servers (Claude Desktop, Claude Code, Cursor,
VS Code and others) can use the app for you while it is open: "replace all
the ADVANCE TANKS sounds with the files in this folder", "clear every video
replacement", "build the card". It works the open window the way clicks do,
through the same checks, so whatever it changes shows in the window and in
your project like your own edits.

## Turning it on

1. In the app: **Settings** (the gear) > **AI agents** > **Let AI agents
   control PAD**.
2. The app shows the lines to add to your agent's MCP servers. For a
   Windows install they look like this:

```json
{
  "mcpServers": {
    "pinball-asset-decryptor": {
      "command": "C:\\Program Files\\Pinball Asset Decryptor\\python\\python.exe",
      "args": ["-m", "pinball_decryptor.mcp"],
      "cwd": "C:\\Program Files\\Pinball Asset Decryptor"
    }
  }
}
```

   On macOS and Linux the command is the app itself with `--mcp`. Copy the
   lines the app shows: they name your install's own paths.
3. Restart the agent so it picks up the new server, and keep the app open
   while it works.

**AI agents** > **Connect an agent…** shows those lines again. Untick
the setting to stop it: agents can no longer reach the app.

## What the agent gets

| Tool | What it does |
| --- | --- |
| `pad_status` | What is open: manufacturer, project folder, tabs, a job running, questions waiting, the last log lines |
| `pad_find_calls` | Finds the app's actions by words ("video replace", "scan") with their parameters and help |
| `pad_call` | Runs an action, like a click |
| `pad_answer` | Answers a question the app asks (Yes / No, OK, a file) |
| `pad_result` | Waits for a long action (an extract, a build) to finish |
| `pad_state`, `pad_search` | Reads what a tab shows, or finds rows in its list ("advance tank" on the Video tab) |
| `pad_use_files` | Hands the next Browse... / Choose... the files to use, the way dropping files on the button does |
| `pad_log` | The last lines of the log |

Every action the window has is there: pictures, sounds, videos, text,
scenes, defaults, extract, write, multi-boot and the rest.

## Safety

- It is off until you turn it on, and only programs running as you on this
  PC can reach it. The app writes `agent.json` (the local address and a
  key that changes every time the app starts) beside `settings.json`
  while the setting is on, and removes it when you untick it or close the
  app.
- The agent changes your project the way you would, and **Change
  history…** (the folder button) lists each change with its time. Keep a
  copy of a project you can't redo before handing it over (**Save project
  as…**).
