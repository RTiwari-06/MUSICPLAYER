# Music SpotDL

A desktop GUI for downloading music from Spotify track, album, and playlist links with [spotDL](https://github.com/spotDL/spotify-downloader). Paste a link, choose where files go, and follow download progress in the app.

<p align="center">
  <a href="https://github.com/RTiwari-06/music_spotdl">
    <img src="https://img.shields.io/github/stars/RTiwari-06/music_spotdl?style=for-the-badge&logo=github&label=Stars" alt="GitHub stars">
  </a>
  <a href="https://github.com/RTiwari-06/music_spotdl/network/members">
    <img src="https://img.shields.io/github/forks/RTiwari-06/music_spotdl?style=for-the-badge&logo=github&label=Forks" alt="GitHub forks">
  </a>
  <a href="https://github.com/RTiwari-06/music_spotdl/commits/main">
    <img src="https://img.shields.io/github/last-commit/RTiwari-06/music_spotdl?style=for-the-badge&logo=git&label=Last%20commit" alt="Latest commit">
  </a>
  <a href="https://github.com/RTiwari-06/music_spotdl">
    <img src="https://img.shields.io/github/languages/top/RTiwari-06/music_spotdl?style=for-the-badge&logo=python&label=Python" alt="Top language">
  </a>
</p>

## Features

- Download from Spotify track, album, or playlist URLs.
- Choose an output folder and organize files with a configurable naming template.
- Configure audio format, bitrate, provider, overwrite behavior, and album fetching.
- View live download logs and progress, and cancel an active download.
- Automatically retry with the YouTube audio provider when enabled.
- Check for FFmpeg and Deno dependencies and launch spotDL's installers.
- Use a dark-themed desktop interface with download settings saved between runs.

## Requirements

- Python 3.10 or newer
- Tkinter (usually included with Python; on some Linux distributions install the system `python3-tk` package)
- [spotDL](https://github.com/spotDL/spotify-downloader)
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
- FFmpeg and Deno for spotDL audio processing and extraction

## Install and run

Clone the repository and install the Python packages:

```bash
git clone https://github.com/RTiwari-06/music_spotdl.git
cd music_spotdl
python -m pip install spotdl customtkinter
```

Start the application:

```bash
python main.py
```

The app checks for required tools at startup. If FFmpeg or Deno is missing, use the corresponding install action in the app or install it separately. The app uses spotDL's system requirements and supported platforms; see the [spotDL documentation](https://spotdl.readthedocs.io/) for details.

## Usage

1. Launch the app and paste a Spotify track, album, or playlist URL.
2. Select a download location, or use the configured default.
3. Open settings to adjust format, bitrate, audio provider, and other options.
4. Click **Download** to start. Follow progress in the log or cancel the current operation.

By default, downloads are saved under `~/Music/spotDL`, with folders organized by artist and album. The location and download preferences can be changed in settings.

## Important

This project uses Spotify links as metadata input; audio retrieval is handled by spotDL using its configured audio sources. You are responsible for ensuring your use complies with applicable laws, Spotify's terms, and the rights of artists and copyright holders. This project is not affiliated with Spotify.

## Built with

- [Python](https://www.python.org/)
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
- [spotDL](https://github.com/spotDL/spotify-downloader)
