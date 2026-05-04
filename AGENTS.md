# Project Instructions

## Persistent Rules

### 1. Encoding and Chinese Text

- All new or modified text files in this repository must use UTF-8.
- Do not introduce GBK, ANSI, Big5, or UTF-16 unless the user explicitly requests it.
- In Python, always pass `encoding="utf-8"` when reading or writing text files.
- When writing JSON, use `ensure_ascii=False` so Chinese content stays readable.
- If Chinese looks garbled in terminal output, first suspect the shell encoding or code page instead of assuming the source file is broken.
- Do not blindly rewrite Chinese text that looks garbled in Windows PowerShell. Verify the file with UTF-8-aware reading first.

### 2. PowerShell Handling

- When reading Chinese text in PowerShell, prefer explicit UTF-8 commands such as `Get-Content -Encoding utf8`.
- When writing Chinese text in PowerShell, prefer `Set-Content -Encoding utf8` or `Out-File -Encoding utf8`.
- If a session needs to print Chinese reliably, set console encodings to UTF-8 before further inspection:
  - `[Console]::InputEncoding = [System.Text.Encoding]::UTF8`
  - `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`

### 3. Session Memory for This Repository

- Treat this file as the long-term instruction source for future sessions in this repository.
- When the user adds a new standing preference, add it here instead of relying on chat memory alone.
- If a new rule conflicts with an older one, update this file so the newest rule is explicit.

### 4. User Additions

- Add future long-term preferences in this section.
- Current standing preference: always default to UTF-8 to avoid Chinese mojibake.
