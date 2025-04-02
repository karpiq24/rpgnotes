# RPG Session Notes Automator

This Python script automates the process of generating detailed session notes for tabletop role-playing games (TTRPGs) run over Discord with audio recording (e.g., using Craig bot). It leverages:

*   **FoundryVTT Chat Logs:** Extracts session information (like session number).
*   **Audio Recordings:** Unzips and prepares audio files (FLAC format expected).
*   **Whisper:** Transcribes the audio recordings with speaker diarization (based on filenames and a mapping file).
*   **Google Gemini:** Generates a comprehensive session summary and extracts key details (events, NPCs, locations, items, AI image prompts) from the transcript and optional context.
*   **Instructor & Pydantic:** Ensures structured data extraction from the Gemini API.

The final output is a formatted Markdown file containing the session summary and extracted details, ready for use.

## Features

*   Automatically finds the newest FoundryVTT chat log (`.json`) and audio recording (`.flac.zip`).
*   Prettifies and saves the relevant chat log, tagged with the session number.
*   Extracts FLAC audio files from the Craig zip archive.
*   Transcribes multiple audio files using OpenAI's Whisper model (supports CUDA acceleration).
*   Uses a custom initial prompt for Whisper to improve transcription quality and context.
*   Maps Discord user IDs (from audio filenames) to character/player names using a JSON mapping file.
*   Combines individual speaker transcripts into a single, time-sorted transcript (JSON and TXT).
*   Filters out low-confidence or irrelevant speech segments.
*   Leverages Google's Gemini Pro model to generate a detailed narrative summary of the session.
*   Uses Gemini Pro with Instructor to extract structured data:
    *   Session Title
    *   Session Date (attempts to infer or defaults to the last Monday)
    *   Key Events/Decisions
    *   Important NPCs
    *   Visited Locations
    *   Significant Items
    *   AI Image Generation Prompts (in English) based on session events.
*   Utilizes external text files (`CONTEXT_DIR`) and the *previous* session's summary (if found) to provide additional context to the AI, improving summary quality and continuity.
*   Formats the generated summary and details into a clean Markdown file using a customizable template.
*   Optionally cleans up temporary files after successful execution.

## Prerequisites

*   **Python 3.x**
*   **Pip** (Python package installer)
*   **NVIDIA GPU with CUDA installed** (Recommended for significantly faster Whisper transcription). The script defaults to `cuda`, but Whisper can fall back to CPU if CUDA is unavailable (will be much slower).
*   **FFmpeg:** Whisper requires FFmpeg to be installed on your system and available in the PATH. ([Download FFmpeg](https://ffmpeg.org/download.html))
*   **Google Cloud Project:** You need a Google Cloud project with the **Gemini API** enabled.
*   **Google Gemini API Key:** Generate an API key for your project.
*   **Source Files:**
    *   FoundryVTT chat log exports (JSON format, expected to contain a title like "Session X").
    *   Craig bot audio recordings (zipped FLAC files, like `craig-YYYYMMDD-HHMMSS.flac.zip`).

## Setup

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/karpiq24/rpgnotes
    cd rpgnotes
    ```

2.  **Install Python Dependencies:**
    Install the dependencies:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up Google Cloud & Gemini:**
    *   Go to the [Google Cloud Console](https://console.cloud.google.com/).
    *   Create a new project or select an existing one.
    *   Navigate to "APIs & Services" -> "Library".
    *   Search for "Generative Language API" (or similar, the name might evolve) and enable it for your project.
    *   Navigate to "APIs & Services" -> "Credentials".
    *   Create an API key. **Keep this key secure!**

4.  **Create Configuration File (`.env`):**
    Create a file named `.env` in the root directory of the project and populate it with the following variables, adjusting the paths and values as needed:

    ```dotenv
    # --- Directories ---
    # Directory where final Markdown summaries will be saved
    OUTPUT_DIR=./output
    # Directory for temporary files (audio extraction, intermediate transcripts)
    TEMP_DIR=./temp
    # Directory containing raw FoundryVTT chat log JSON exports
    CHAT_LOG_SOURCE_DIR=./source/chatlogs
    # Directory containing raw Craig audio recording zip files (*.flac.zip)
    AUDIO_SOURCE_DIR=./source/audio
    # Directory containing context files (plain text .txt) for the AI
    CONTEXT_DIR=./context
    # Directory where Whisper models will be downloaded (optional, defaults to ./models/)
    # WHISPER_MODEL_DIR=./models/

    # --- File Paths ---
    # JSON file mapping Discord User IDs (from audio filenames) to Character/Player names
    # Example: {"123456789012345678": "Character One", "987654321098765432": "Game Master"}
    DISCORD_MAPPING_FILE=./config/discord_mapping.json
    # Text file containing the initial prompt for Whisper transcription
    WHISPER_PROMPT_FILE=./config/whisper_prompt.txt
    # Text file containing the system prompt/instructions for Gemini summary generation
    SUMMARY_PROMPT_FILE=./config/summary_prompt.txt
    # Text file containing the system prompt/instructions for Gemini structured detail extraction
    DETAILS_PROMPT_FILE=./config/details_prompt.txt
    # Markdown template file for the final session notes output
    TEMPLATE_FILE=./config/template.md

    # --- API Keys & Models ---
    # Your Google Gemini API Key
    GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
    # The specific Gemini model to use (e.g., gemini-2.5-pro-exp-03-25)
    GEMINI_MODEL_NAME=gemini-2.5-pro-exp-03-25

    # --- Settings ---
    # Set to "true" to delete the TEMP_DIR after successful execution, "false" to keep it
    DELETE_TEMP_FILES=true
    ```

5.  **Prepare Configuration Files:**
    *   Create the directories specified in `.env` (`source/chatlogs`, `source/audio`, `config`, `context`, etc.).
    *   Create the `discord_mapping.json` file with your Discord User ID to Name mappings. Find user IDs in the extracted FLAC filenames (e.g., `1698087471-discord_123456789012345678.flac` -> ID is `123456789012345678`).
    *   Create the prompt files (`whisper_prompt.txt`, `summary_prompt.txt`, `details_prompt.txt`) with your desired instructions for Whisper and Gemini. Good prompts are key to good results!
    *   Create the `template.md` file. See the `save_summary_file` function in the script for the available formatting variables (`{number}`, `{title}`, `{date}`, `{summary}`, `{events}`, `{npcs}`, `{locations}`, `{items}`, `{images}`).
    *   (Optional) Add any relevant background information, character sheets, world lore, etc., as `.txt` files into the `CONTEXT_DIR`.

## Usage

1.  **Place Source Files:**
    *   Put your latest FoundryVTT chat log JSON export into the `CHAT_LOG_SOURCE_DIR`.
    *   Put your latest Craig `.flac.zip` audio recording into the `AUDIO_SOURCE_DIR`.

2.  **Run the Script:**
    Open a terminal or command prompt, navigate to the project directory, and run:
    ```bash
    python main.py
    ```

3.  **Monitor Progress:**
    The script will print status messages for each step:
    *   Processing chat log
    *   Unzipping audio
    *   Transcribing audio (with a progress bar showing ETA)
    *   Combining transcriptions
    *   Generating summary and details (may take some time depending on API response)
    *   Saving the final file
    *   Cleaning up temporary files (if enabled)

4.  **Check Output:**
    *   The final Markdown session notes will be saved in the `OUTPUT_DIR`.
    *   Intermediate files (prettified chat log, combined transcripts) will be in `OUTPUT_DIR/_chat_log` and `OUTPUT_DIR/_transcripts`.
    *   Temporary files (extracted audio, individual transcripts) will be in `TEMP_DIR` (and deleted if `DELETE_TEMP_FILES=true`).

## Notes

*   **Whisper Model:** The script uses the `large` Whisper model by default. Transcription quality is generally high but can vary. Model files will be downloaded on the first run to the directory specified by `WHISPER_MODEL_DIR` or the default location if not set.
*   **API Costs:** Using the Google Gemini API incurs costs based on usage (input/output tokens). Be mindful of the length of your transcripts and the frequency of running the script.
*   **Rate Limits:** AI APIs often have rate limits. The script includes a 10-second pause between the summary and details generation calls, but you might need to adjust this or implement more robust backoff strategies if you encounter rate limit errors.
*   **Prompt Engineering:** The quality of the generated summary and extracted details heavily depends on the prompts provided in `summary_prompt.txt` and `details_prompt.txt`. Experiment with different instructions to get the desired output style and detail level.
*   **Error Handling:** The script includes basic error handling, but complex issues (e.g., malformed input files, API errors) might require debugging.
