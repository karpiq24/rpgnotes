# 🚀 RPG Session Notes Automator 🚀

Tired of spending hours after your TTRPG sessions meticulously writing notes, trying to remember every quote, and struggling to organize plot points? **The RPG Session Notes Automator is here to revolutionize your post-game workflow!**

This powerful Python script leverages the magic of AI to transform your raw session recordings into beautifully formatted, detailed, and insightful Markdown notes. Go from a messy folder of audio files to a comprehensive, searchable campaign chronicle with just a few commands. Spend less time on admin and more time planning your next epic adventure!

---

## ✨ Key Features

*   **🎙️ Automated Audio Transcription**: Uses OpenAI's Whisper to accurately transcribe hours of session audio into text, complete with speaker identification.
*   **🤖 AI-Powered Summarization**: Leverages the Gemini API to generate a narrative summary of the session, capturing the key events in a story-like format.
*   **📊 Structured Data Extraction**: Intelligently pulls key details from the session and organizes them into structured lists:
    *   **Major Events**: A bulleted list of the most important plot points.
    *   **Key NPCs & Locations**: Keep track of who and where the party encountered.
    *   **Important Items**: A log of significant loot or plot-relevant items.
    *   **Memorable Quotes**: Never forget that hilarious one-liner or dramatic declaration again.
    *   **Plot Hooks**: AI-generated suggestions and intriguing questions for the Game Master to use in future sessions.
*   **🎨 AI Art & Video Prompts**: Automatically generates a list of creative, detailed prompts (in English) for AI image and video generators, perfect for creating visual aids for your campaign.
*   **📖 Campaign Chronicle**: Automatically compiles all your session notes into a single, massive `_campaign.md` file, creating a continuous, easy-to-read history of your entire adventure.
*   **👤 Speaker Identification**: Maps Discord user IDs to character names for clear, readable transcripts.
*   **⚙️ Interactive Menu**: An easy-to-use command-line menu to run the full workflow, generate transcripts only, or just update the campaign chronicle.
*   **🛠️ Smart & Resumable Workflow**: The script is designed to be efficient. It skips steps that have already been completed, remembers your progress, and manages temporary files.

---

## ⚙️ Getting Started

Follow these steps to get the automator up and running on your system.

### Prerequisites

Before you begin, ensure you have the following installed:

1.  **Python 3.12+**: Make sure Python is installed and added to your system's PATH.
2.  **FFmpeg**: Whisper requires FFmpeg for audio processing. You can download it from the [official FFmpeg website](https://ffmpeg.org/download.html). Ensure the `ffmpeg` executable is in your system's PATH.
3.  **NVIDIA GPU (Recommended)**: For significantly faster transcriptions, a CUDA-enabled NVIDIA GPU is recommended. The script will fall back to using the CPU if one is not available.
4.  **Git**: For cloning the repository.

### 1. Clone the Repository


### 2. Install Dependencies

Install all the required Python packages using pip:

```bash
pip install -r requirements.txt
```
*(Note: You will need to create a `requirements.txt` file containing all the necessary libraries like `openai-whisper`, `google-generativeai`, `pydantic`, `python-dotenv`, `tqdm`, `instructor`)*

### 3. Obtain API Keys

The script requires an API key for Google's Gemini to generate summaries and structured data.

*   **Google Gemini API Key**:
    *   Go to the [Google AI Studio](https://aistudio.google.com/).
    *   Sign in and click on "**Get API key**" -> "**Create API key**".
    *   Copy the generated key.

### 4. Configure Your Environment

The script is configured using a `.env` file and several configuration files in the `config` directory.

1.  **Create the `.env` file**: Rename the `example.env` file to `.env`.

2.  **Edit the `.env` file**: Open `.env` and fill in the required values.

    ```dotenv
    # --- REQUIRED ---
    # The API key for the Gemini model
    GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE"

    # --- PATHS (modify if you want a different folder structure) ---
    # Directory where final markdown notes will be saved
    OUTPUT_DIR="output"
    # Directory where your raw audio and chat logs are downloaded
    DOWNLOADS_DIR="C:/Users/YourUser/Downloads"
    # Directory for temporary files (transcripts, audio chunks)
    TEMP_DIR="temp"

    # --- CONFIGURATION FILES ---
    DISCORD_MAPPING_FILE="config/discord_mapping.json"
    WHISPER_PROMPT_FILE="config/whisper_prompt.txt"
    SUMMARY_PROMPT_FILE="config/summary_prompt.txt"
    DETAILS_PROMPT_FILE="config/details_prompt.txt"
    TEMPLATE_FILE="config/template.md"
    CONTEXT_DIR="context" # Directory for supplemental campaign context

    # --- MODEL SETTINGS ---
    GEMINI_MODEL_NAME="gemini-1.5-pro-latest"
    ```

### 5. Set Up Configuration Files

Customize the `config` and `context` directories to match your campaign's specifics.

*   `config/discord_mapping.json`: This is crucial for speaker identification. Map the Discord usernames found in the audio filenames to your players' character names.
    ```json
    {
      "DiscordUser123": "Arevon the Brave",
      "AnotherPlayer#4567": "Elara Nightshade",
      "GameMaster": "Game Master"
    }
    ```

*   `config/whisper_prompt.txt`: Add a list of unique names, places, and jargon from your campaign. This gives Whisper context and dramatically improves the accuracy of the transcription.

*   `config/summary_prompt.txt` & `config/details_prompt.txt`: These are the master prompts for the Gemini AI. You can tweak them to change the tone, style, or focus of the generated notes.

*   `config/template.md`: This is the Markdown template for the final notes. Customize it to change the layout, add or remove sections, and make it your own.

*   `context/`: Place any `.txt` or `.md` files in this directory that contain general world lore, campaign background, or character backstories. The AI will use this information for added context when generating summaries.

---

## ▶️ Usage

Once everything is set up, running the script is simple.

1.  **Place Your Files**:
    *   Move your latest session's chat log (e.g., `session53.json`) into your `DOWNLOADS_DIR`.
    *   Move your session's audio recording (the `craig-*.flac.zip` file) into your `DOWNLOADS_DIR`.

2.  **Run the Script**:
    ```bash
    python main.py
    ```

3.  **Choose an Option from the Menu**:

    ```
    ==================================================
    🚀 D&D Session Processing Workflow 🚀
    ==================================================
    Please choose an option:
      [1] Start Full Workflow (Transcribe -> Generate AI Notes -> Update Chronicle)
      [2] Run Workflow until Transcribing (Generate transcript file only)
      [3] Regenerate Campaign Chronicle (from existing session notes)
      [4] Exit
    ==================================================
    Enter your choice [1-4]:
    ```

---

## 🗺️ The Workflow Explained

Here's what happens when you run the **Full Workflow**:

1.  **Initialization**: The script checks for an existing `temp` directory and asks if you want to clear it to ensure a fresh start.
2.  **Chat Log Processing**: It finds the newest `sessionXX.json` file, extracts the session number and date, and formats it.
3.  **Audio Preparation**: The `craig-*.flac.zip` archive is located and unzipped into the `temp/audio` directory.
4.  **Transcription**: Each audio file is processed by Whisper. This is the most time-consuming step. The script shows a real-time progress bar with an ETA.
5.  **Transcript Combination**: The individual transcripts are combined into a single, chronologically sorted text file, with speaker names added from your mapping file.
6.  **AI Note Generation**:
    *   The complete transcript and context files are sent to the Gemini API to generate a detailed summary.
    *   The summary and transcript are then sent again to extract the structured data (NPCs, locations, quotes, etc.).
7.  **File Creation**: The AI-generated content is formatted using the `template.md` file and saved as `Sesja XX - Title.md` in your `output` directory.
8.  **Chronicle Update**: Finally, the script gathers all session notes in the `output` directory and compiles them into the `_campaign.md` file.

You're left with a perfect set of notes and an updated campaign history, all with minimal effort
