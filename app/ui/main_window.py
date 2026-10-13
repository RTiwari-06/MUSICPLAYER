from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict

import customtkinter as ctk
from tkinter import filedialog

from app.core.config import ConfigManager
from app.core.spotdl_wrapper import SpotDLManager
from app.utils import system_check


# Glassmorphism color palette (using CTK-compatible tuple colors for light/dark modes)
# These create a frosted glass effect - semi-transparent through CTK's rendering

# Glass frame backgrounds - frosted semi-transparent look
GLASS_FRAME_BG = ("#e8f0fe", "#1e293b")  # Light frosted / dark slate
GLASS_FRAME_BORDER = ("#c5cae1", "#334155")  # Subtle borders

# Glass button backgrounds
GLASS_BTN_BG = ("#f8f9ff", "#2d3749")  # Frosted effect
GLASS_BTN_HOVER = ("#e8f0fe", "#475569")

# Accent colors
ACCENT_BLUE = "#4a90d9"
CTA_HOVER = "#3a7bc0"
ACCENT_RED = "#e74c3c"
ACCENT_GREEN = "#2ecc71"
ACCENT_ORANGE = "#f39c12"

# Glassmorphism font colors
TEXT_PRIMARY_LIGHT = "#1a1a1a"
TEXT_SECONDARY_LIGHT = "#555555"
TEXT_PRIMARY_DARK = "#e8e8e8"
TEXT_SECONDARY_DARK = "#aaaaaa"

# Log colors
LOG_TEXT_NORMAL = "#d4d4d4"
LOG_TEXT_ERROR = "#ff6b6b"
LOG_TEXT_WARNING = "#f39c12"
LOG_TEXT_SUCCESS = "#2ecc71"
LOG_TEXT_FALLBACK = "#ff4757"
LOG_TEXT_INFO = "#4fc3f7"


class GlassFrame(ctk.CTkFrame):
    """A frame with glassmorphism styling."""

    def __init__(self, master: Any, corner_radius: int = 15, border_width: int = 1, **kwargs: Any) -> None:
        super().__init__(
            master,
            corner_radius=corner_radius,
            border_width=border_width,
            fg_color=GLASS_FRAME_BG,
            border_color=GLASS_FRAME_BORDER,
            **kwargs
        )


class GlassButton(ctk.CTkButton):
    """A button with glassmorphism styling."""

    def __init__(self, master: Any, **kwargs: Any) -> None:
        # Default glass styles
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", GLASS_FRAME_BORDER)
        kwargs.setdefault("height", 36)
        # Remove text_color from kwargs if provided, we'll set our own
        kwargs.setdefault("fg_color", GLASS_BTN_BG)
        kwargs.setdefault("hover_color", GLASS_BTN_HOVER)
        text_color = kwargs.pop("text_color", TEXT_PRIMARY_DARK)
        super().__init__(master, text_color=text_color, **kwargs)


class GlassEntry(ctk.CTkEntry):
    """An entry widget with glassmorphism styling."""

    def __init__(self, master: Any, **kwargs: Any) -> None:
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("height", 36)
        kwargs.setdefault("fg_color", GLASS_FRAME_BG)
        kwargs.setdefault("border_color", GLASS_FRAME_BORDER)
        kwargs.setdefault("text_color", TEXT_PRIMARY_DARK)
        kwargs.setdefault("placeholder_text_color", TEXT_SECONDARY_DARK)
        super().__init__(master, **kwargs)


class MainWindow(ctk.CTk):
    """
    Main application window for the MusicPlayer (spotDL) GUI.

    Provides URL input, output directory selection, download control,
    progress display, cancellation, live log streaming, settings modal,
    and system repair quick-fixes.
    """

    def __init__(self) -> None:
        super().__init__()
        self.title("MusicPlayer - spotDL Downloader")
        self.geometry("1000x720")
        self.minsize(900, 650)

        # Apply Modern Theme with glassmorphism
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Set custom background
        self.configure(background="#0f172a")

        self.config_manager = ConfigManager()
        self.spotdl_manager = SpotDLManager(self.config_manager)

        self.system_status = system_check.check_all()
        self._is_downloading = False
        self._current_url = ""
        self._fallback_active = False
        self._session_start = time.time()
        self._session_files = 0
        self._session_bytes = 0

        # Configure grid weights for responsive layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Main container with padding
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(3, weight=1)

        self._build_header()
        self._build_download_section()
        self._build_progress_section()
        self._build_log_section()
        self._build_status_bar()

        self._update_system_status()

    def _build_header(self) -> None:
        """Build the header section with title and system controls."""
        self.header_frame = GlassFrame(self.main_container, corner_radius=20)
        self.header_frame.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        self.header_frame.grid_columnconfigure(1, weight=1)

        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="MusicPlayer",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=TEXT_PRIMARY_DARK,
        )
        self.title_label.grid(row=0, column=0, padx=15, pady=(12, 0), sticky="sw")

        self.subtitle_label = ctk.CTkLabel(
            self.header_frame,
            text="Spotify Downloader",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY_DARK,
        )
        self.subtitle_label.grid(row=1, column=0, padx=15, pady=(0, 12), sticky="nw")

        self.status_label = ctk.CTkLabel(
            self.header_frame,
            text="",
            font=ctk.CTkFont(size=10),
            anchor="w",
            text_color=TEXT_SECONDARY_DARK,
        )
        self.status_label.grid(row=0, column=1, rowspan=2, padx=15, pady=8, sticky="ew")

        self.ffmpeg_fix_btn = GlassButton(
            self.header_frame,
            text="Install FFmpeg",
            width=100,
            height=28,
            font=ctk.CTkFont(size=10),
            command=self._install_ffmpeg,
        )
        self.ffmpeg_fix_btn.grid(row=0, column=2, rowspan=2, padx=5, pady=8, sticky="ns")

        self.deno_fix_btn = GlassButton(
            self.header_frame,
            text="Install Deno",
            width=100,
            height=28,
            font=ctk.CTkFont(size=10),
            command=self._install_deno,
        )
        self.deno_fix_btn.grid(row=0, column=3, rowspan=2, padx=5, pady=8, sticky="ns")

        self.settings_button = GlassButton(
            self.header_frame,
            text="Settings",
            width=110,
            height=28,
            font=ctk.CTkFont(size=10),
            command=self._open_settings,
        )
        self.settings_button.grid(row=0, column=4, rowspan=2, padx=(5, 15), pady=8, sticky="ns")

    def _build_download_section(self) -> None:
        """Build the URL input, download control, and output directory section."""
        self.download_frame = GlassFrame(self.main_container, corner_radius=20)
        self.download_frame.grid(row=1, column=0, pady=(0, 10), sticky="ew")
        self.download_frame.grid_columnconfigure(0, weight=1)

        self.url_label = ctk.CTkLabel(
            self.download_frame,
            text="Spotify URL or Track Link",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
            text_color=TEXT_PRIMARY_DARK,
        )
        self.url_label.grid(row=0, column=0, padx=15, pady=(10, 2), sticky="w")

        self.url_entry = GlassEntry(
            self.download_frame,
            placeholder_text="Enter Spotify track, album, or playlist URL...",
            height=40,
            font=ctk.CTkFont(size=12),
        )
        self.url_entry.grid(row=1, column=0, padx=15, pady=(0, 8), sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self._start_download())

        self.download_button = ctk.CTkButton(
            self.download_frame,
            text="Download",
            width=140,
            height=40,
            corner_radius=12,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=ACCENT_BLUE,
            hover_color=CTA_HOVER,
            command=self._start_download,
        )
        self.download_button.grid(row=1, column=1, padx=(0, 15), pady=(0, 8), sticky="e")

        self.output_label = ctk.CTkLabel(
            self.download_frame,
            text=f"Output Directory: {self.config_manager.download_directory}",
            anchor="w",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_SECONDARY_DARK,
        )
        self.output_label.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="ew")

        self.browse_button = GlassButton(
            self.download_frame,
            text="Change Folder",
            width=140,
            height=28,
            font=ctk.CTkFont(size=10),
            command=self._browse_folder,
        )
        self.browse_button.grid(row=2, column=1, padx=(0, 15), pady=(0, 10), sticky="e")

    def _build_progress_section(self) -> None:
        """Build the progress bar, song counter, and cancel control section."""
        self.progress_frame = GlassFrame(self.main_container, corner_radius=20)
        self.progress_frame.grid(row=2, column=0, pady=(0, 10), sticky="ew")
        self.progress_frame.grid_columnconfigure(1, weight=1)

        self.track_label = ctk.CTkLabel(
            self.progress_frame,
            text="Ready to download",
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY_DARK,
        )
        self.track_label.grid(row=0, column=0, columnspan=3, padx=15, pady=(10, 5), sticky="ew")

        self.song_counter_label = ctk.CTkLabel(
            self.progress_frame,
            text="Ready",
            width=90,
            anchor="e",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_SECONDARY_DARK,
        )
        self.song_counter_label.grid(row=1, column=0, padx=15, pady=(0, 10), sticky="e")

        # Progress bar container with percentage
        self.progress_container = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        self.progress_container.grid(row=1, column=1, padx=(10, 10), pady=(0, 10), sticky="ew")
        self.progress_container.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_container, mode="determinate", height=12
        )
        self.progress_bar.grid(row=0, column=0, padx=(0, 12), sticky="ew")
        self.progress_bar.set(0)

        self.progress_percent_label = ctk.CTkLabel(
            self.progress_container,
            text="0%",
            width=55,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_PRIMARY_DARK,
        )
        self.progress_percent_label.grid(row=0, column=1, sticky="e")

        # Fallback badge with glass styling
        self.fallback_badge = ctk.CTkLabel(
            self.progress_frame,
            text="FALLBACK MODE",
            font=ctk.CTkFont(size=9, weight="bold"),
            fg_color=ACCENT_RED,
            text_color="white",
            corner_radius=8,
            width=110,
            height=22,
        )
        self.fallback_badge.grid(row=1, column=2, padx=(0, 8), pady=(0, 10))
        self.fallback_badge.grid_remove()

        # Action buttons
        self.cancel_button = GlassButton(
            self.progress_frame,
            text="Cancel",
            width=110,
            height=36,
            font=ctk.CTkFont(size=10),
            command=self._cancel_download,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=3, rowspan=2, padx=(5, 15), pady=8, sticky="e")

    def _build_log_section(self) -> None:
        """Build the log display section."""
        self.log_frame = GlassFrame(self.main_container, corner_radius=20)
        self.log_frame.grid(row=3, column=0, pady=(0, 10), sticky="nsew")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)

        self.log_header = ctk.CTkLabel(
            self.log_frame,
            text="Download Log",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
            text_color=TEXT_PRIMARY_DARK,
        )
        self.log_header.grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")

        self.clear_log_button = GlassButton(
            self.log_frame,
            text="Clear Log",
            width=90,
            height=26,
            font=ctk.CTkFont(size=10),
            command=self._clear_log,
        )
        self.clear_log_button.grid(row=0, column=1, padx=(0, 15), pady=(10, 5), sticky="e")

        self.log_textbox = ctk.CTkTextbox(
            self.log_frame,
            wrap="word",
            font=ctk.CTkFont(size=10, family="Consolas"),
            fg_color=GLASS_FRAME_BG,
            border_width=0,
        )
        self.log_textbox.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="nsew")
        self.log_textbox.configure(state="disabled", text_color=TEXT_PRIMARY_DARK)
        self._setup_log_tags()  # Initialize log tag colors

        # Add scrollbar to log textbox
        self.log_scrollbar = ctk.CTkScrollbar(
            self.log_frame,
            command=self.log_textbox.yview,
            width=12,
        )
        self.log_scrollbar.grid(row=1, column=1, padx=(0, 8), pady=(0, 15), sticky="ns")
        self.log_textbox.configure(yscrollcommand=self.log_scrollbar.set)

    def _build_status_bar(self) -> None:
        """Build the bottom status bar with session statistics."""
        self.status_frame = GlassFrame(self.main_container, corner_radius=12)
        self.status_frame.grid(row=4, column=0, pady=(0, 0), sticky="ew")
        self.status_frame.grid_columnconfigure(0, weight=1)

        self.status_bar = ctk.CTkLabel(
            self.status_frame,
            text="Ready",
            font=ctk.CTkFont(size=10),
            anchor="w",
            text_color=TEXT_PRIMARY_DARK,
        )
        self.status_bar.grid(row=0, column=0, padx=12, pady=6, sticky="w")

        self.session_stats_label = ctk.CTkLabel(
            self.status_frame,
            text="Session: 0 files | 0.0 MB",
            font=ctk.CTkFont(size=10),
            anchor="e",
            text_color=TEXT_SECONDARY_DARK,
        )
        self.session_stats_label.grid(row=0, column=1, padx=12, pady=6, sticky="e")

    def _update_system_status(self) -> None:
        self.system_status = system_check.check_all()
        ffmpeg_ok = self.system_status.get("ffmpeg", {}).get("available", False)
        deno_ok = self.system_status.get("deno", {}).get("available", False)
        self.status_label.configure(
            text=f"FFmpeg: {'OK' if ffmpeg_ok else 'MISSING'} | Deno: {'OK' if deno_ok else 'MISSING'}",
            text_color=TEXT_SECONDARY_DARK,
        )
        if hasattr(self, "ffmpeg_fix_btn"):
            if ffmpeg_ok:
                self.ffmpeg_fix_btn.grid_remove()
            else:
                self.ffmpeg_fix_btn.configure(state="normal")
                self.ffmpeg_fix_btn.grid(row=0, column=2, rowspan=2, padx=5, pady=8, sticky="ns")
        if hasattr(self, "deno_fix_btn"):
            if deno_ok:
                self.deno_fix_btn.grid_remove()
            else:
                self.deno_fix_btn.configure(state="normal")
                self.deno_fix_btn.grid(row=0, column=3, rowspan=2, padx=5, pady=8, sticky="ns")

    def _run_install_thread(self, installer_func: Callable[[], subprocess.Popen[bytes]], name: str) -> None:
        def _run():
            try:
                proc = installer_func()
                try:
                    proc.communicate(timeout=600)
                except Exception:
                    pass
            except Exception:
                pass
            self.after(0, self._update_system_status)
            self.after(0, lambda: self._log(f"{name} installation check completed", status="success"))
        threading.Thread(target=_run, daemon=True).start()

    def _install_ffmpeg(self) -> None:
        self._log("Installing FFmpeg via spotdl...", status="info")
        self._run_install_thread(system_check.install_ffmpeg, "FFmpeg")

    def _install_deno(self) -> None:
        self._log("Installing Deno via spotdl...", status="info")
        self._run_install_thread(system_check.install_deno, "Deno")

    def _open_settings(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("620x480")
        dialog.minsize(560, 420)
        dialog.transient(self)
        dialog.configure(background="#0f172a")
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(0, weight=1)

        # Glassmorphism dialog background
        dialog_bg = GlassFrame(dialog, corner_radius=0)
        dialog_bg.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        dialog_bg.grid_columnconfigure(0, weight=1)
        dialog_bg.grid_rowconfigure(0, weight=1)

        tabview = ctk.CTkTabview(dialog_bg, corner_radius=12)
        tabview.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")
        tabview.grid_columnconfigure(0, weight=1)
        tabview.add("Quality")
        tabview.add("Provider")
        tabview.add("Save Location")

        # Quality tab
        quality_tab = tabview.tab("Quality")
        quality_tab.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(quality_tab, text="Audio Quality", font=ctk.CTkFont(weight="bold"), text_color=TEXT_PRIMARY_DARK).grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 2), sticky="w")
        ctk.CTkLabel(quality_tab, text="Bitrate:", text_color=TEXT_SECONDARY_DARK).grid(row=1, column=0, padx=12, pady=5, sticky="w")
        bitrate_var = ctk.StringVar(value=self.config_manager.bitrate)
        bitrate_menu = ctk.CTkOptionMenu(quality_tab, variable=bitrate_var, values=["320k", "256k", "192k", "128k"])
        bitrate_menu.grid(row=1, column=1, padx=12, pady=5, sticky="ew")
        ctk.CTkLabel(quality_tab, text="Audio Format:", text_color=TEXT_SECONDARY_DARK).grid(row=2, column=0, padx=12, pady=5, sticky="w")
        format_var = ctk.StringVar(value=self.config_manager.format)
        format_menu = ctk.CTkOptionMenu(quality_tab, variable=format_var, values=["mp3", "m4a", "flac", "ogg"])
        format_menu.grid(row=2, column=1, padx=12, pady=5, sticky="ew")
        fetch_albums_var = ctk.BooleanVar(value=self.config_manager.fetch_albums)
        ctk.CTkSwitch(quality_tab, text="Fetch full albums for songs in the query", variable=fetch_albums_var, progress_color=ACCENT_BLUE).grid(row=3, column=0, columnspan=2, padx=12, pady=5, sticky="w")

        # Provider tab
        provider_tab = tabview.tab("Provider")
        provider_tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(provider_tab, text="Audio Provider & Fallback", font=ctk.CTkFont(weight="bold"), text_color=TEXT_PRIMARY_DARK).grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")
        ctk.CTkLabel(provider_tab, text="Primary Provider:", text_color=TEXT_SECONDARY_DARK).grid(row=1, column=0, padx=12, pady=(5, 2), sticky="w")
        provider_var = ctk.StringVar(value=self.config_manager.audio_provider)
        provider_segment = ctk.CTkSegmentedButton(provider_tab, variable=provider_var, values=["youtube-music", "youtube"])
        provider_segment.grid(row=2, column=0, padx=12, pady=(2, 5), sticky="ew")
        ctk.CTkLabel(provider_tab, text="Overwrite Mode:", text_color=TEXT_SECONDARY_DARK).grid(row=3, column=0, padx=12, pady=(5, 2), sticky="w")
        overwrite_var = ctk.StringVar(value=self.config_manager.overwrite_mode)
        overwrite_segment = ctk.CTkSegmentedButton(provider_tab, variable=overwrite_var, values=["skip", "force", "metadata"])
        overwrite_segment.grid(row=4, column=0, padx=12, pady=(2, 5), sticky="ew")
        ctk.CTkLabel(provider_tab, text="How to handle existing files", text_color=TEXT_SECONDARY_DARK).grid(row=5, column=0, padx=12, pady=(0, 5), sticky="w")
        fallback_var = ctk.BooleanVar(value=self.config_manager.auto_fallback)
        ctk.CTkSwitch(provider_tab, text="Auto-fallback on failure", variable=fallback_var, progress_color=ACCENT_BLUE).grid(row=6, column=0, padx=12, pady=5, sticky="w")

        # Save Location tab
        location_tab = tabview.tab("Save Location")
        location_tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(location_tab, text="Download Directory:", text_color=TEXT_SECONDARY_DARK).grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")
        dir_entry = GlassEntry(location_tab, height=30)
        dir_entry.insert(0, str(self.config_manager.download_directory))
        dir_entry.grid(row=1, column=0, padx=12, pady=(2, 5), sticky="ew")
        browse_dir_btn = GlassButton(location_tab, text="Browse", width=90, height=26, command=lambda: self._browse_dir_dialog(dialog, dir_entry))
        browse_dir_btn.grid(row=2, column=0, padx=12, pady=(0, 5), sticky="w")
        ctk.CTkLabel(location_tab, text="Output Template:", text_color=TEXT_SECONDARY_DARK).grid(row=3, column=0, padx=12, pady=(5, 2), sticky="w")
        template_entry = GlassEntry(location_tab, height=30)
        template_entry.insert(0, self.config_manager.output_template)
        template_entry.grid(row=4, column=0, padx=12, pady=(2, 5), sticky="ew")
        ctk.CTkLabel(location_tab, text="Template variables: {artists}, {artist}, {album}, {title}, {year}, {ext}", text_color=TEXT_SECONDARY_DARK).grid(row=5, column=0, padx=12, pady=(0, 5), sticky="w")

        # Buttons Section
        btn_frame = GlassFrame(dialog_bg, corner_radius=12)
        btn_frame.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)
        feedback_label = ctk.CTkLabel(btn_frame, text="", text_color=TEXT_SECONDARY_DARK)
        feedback_label.grid(row=0, column=0, columnspan=3, padx=12, pady=(8, 5), sticky="ew")

        def save_and_apply() -> None:
            updates = {
                "bitrate": bitrate_var.get(),
                "format": format_var.get(),
                "fetch_albums": fetch_albums_var.get(),
                "audio_provider": provider_var.get(),
                "auto_fallback": fallback_var.get(),
                "download_directory": dir_entry.get(),
                "output_template": template_entry.get(),
                "overwrite_mode": overwrite_var.get(),
            }
            results = self.config_manager.update(updates)
            if all(results.values()):
                self.config_manager.save()
                feedback_label.configure(text="Settings saved successfully", text_color=ACCENT_GREEN)
                self.output_label.configure(text=f"Output Directory: {self.config_manager.download_directory}")
                self.spotdl_manager.set_config_manager(self.config_manager)
            else:
                failed = [k for k, v in results.items() if not v]
                feedback_label.configure(text=f"Failed to save: {', '.join(failed)}", text_color=ACCENT_RED)

        save_btn = ctk.CTkButton(btn_frame, text="Save & Apply", width=130, height=30, corner_radius=12, font=ctk.CTkFont(size=11, weight="bold"), fg_color=ACCENT_BLUE, hover_color=CTA_HOVER, command=save_and_apply)
        save_btn.grid(row=1, column=1, padx=8, pady=8)
        close_btn = GlassButton(btn_frame, text="Close", width=90, height=30, command=dialog.destroy)
        close_btn.grid(row=1, column=2, padx=(0, 12), pady=8)

        # Grab focus only after the dialog is fully built
        dialog.grab_set()
        dialog.after(150, dialog.focus_set)

    def _browse_dir_dialog(self, parent: ctk.CTkToplevel, entry_widget: ctk.CTkEntry) -> None:
        folder = filedialog.askdirectory(
            title="Select Download Directory",
            initialdir=entry_widget.get() or str(self.config_manager.download_directory),
            parent=parent,
        )
        if folder:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, folder)

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(
            title="Select Download Directory",
            initialdir=str(self.config_manager.download_directory),
        )
        if folder:
            path = Path(folder)
            if self.config_manager.set("download_directory", path):
                self.config_manager.save()
                self.output_label.configure(text=f"Output Directory: {self.config_manager.download_directory}")
                self.spotdl_manager.set_config_manager(self.config_manager)
                self._log(f"Output directory set to: {path}", status="success")
            else:
                self._log("Error: Could not set output directory", status="error")

    def _log(self, message: str, status: str = "info") -> None:
        def _append() -> None:
            self.log_textbox.configure(state="normal")
            # Add status prefix and color coding for visibility
            prefix = ""
            tag = "normal"
            if status == "error":
                prefix = "[ERROR] "
                tag = "error"
            elif status == "warning":
                prefix = "[WARN]  "
                tag = "warning"
            elif status == "success":
                prefix = "[OK]    "
                tag = "success"
            elif status == "fallback":
                prefix = "[FBACK] "
                tag = "fallback"
            elif status == "info":
                prefix = "[INFO]  "
                tag = "info"

            self.log_textbox.insert("end", f"{prefix}{message}\n")
            self.log_textbox.tag_add(tag, "end-2l", "end-1c")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        self.after(0, _append)

    def _setup_log_tags(self) -> None:
        """Set up color tags for different log message types."""
        self.log_textbox.tag_config("normal", foreground=LOG_TEXT_NORMAL)
        self.log_textbox.tag_config("error", foreground=LOG_TEXT_ERROR)
        self.log_textbox.tag_config("warning", foreground=LOG_TEXT_WARNING)
        self.log_textbox.tag_config("success", foreground=LOG_TEXT_SUCCESS)
        self.log_textbox.tag_config("fallback", foreground=LOG_TEXT_FALLBACK, underline=True)
        self.log_textbox.tag_config("info", foreground=LOG_TEXT_INFO)

    def _clear_log(self) -> None:
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
        self.status_bar.configure(text="Log cleared")

    def _refresh_session_stats(self) -> None:
        """Recompute bytes downloaded since the session started."""
        try:
            total_bytes = 0
            for dirpath, _dirnames, filenames in os.walk(self.config_manager.download_directory):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    try:
                        if os.path.getmtime(file_path) >= self._session_start:
                            total_bytes += os.path.getsize(file_path)
                    except OSError:
                        continue
            self._session_bytes = total_bytes
            self.session_stats_label.configure(
                text=f"Session: {self._session_files} files | {self._session_bytes / 1048576:.1f} MB"
            )
        except Exception:
            pass

    def _callback(self, status: Dict[str, Any]) -> None:
        def _update() -> None:
            msg = status.get("message", "")
            stat = status.get("status", "downloading")
            percent = status.get("percent", None)
            is_fallback = status.get("fallback", False)

            # Show fallback badge
            if is_fallback or "[FALLBACK]" in msg:
                self._fallback_active = True
                self.fallback_badge.grid()
                self._log(msg, status="fallback")
            elif msg and stat == "downloading":
                if status.get("success"):
                    self._log(msg, status="success")
                    self._session_files += 1
                    self._refresh_session_stats()
                elif status.get("warning"):
                    self._log(msg, status="warning")
                else:
                    self._log(msg, status="info")
                display = msg if len(msg) <= 70 else msg[:67] + "..."
                self.track_label.configure(text=f"Downloading: {display}")

            # Live song counter from "N/M complete" progress lines
            songs_total = status.get("songs_total")
            if songs_total is not None:
                self.song_counter_label.configure(
                    text=f"Song {status.get('songs_done', 0)} of {songs_total}"
                )

            # Update progress bar and percentage
            if percent is not None:
                try:
                    progress_value = percent / 100.0
                    self.progress_bar.set(progress_value)
                    self.progress_percent_label.configure(text=f"{percent:.1f}%")
                except Exception:
                    pass

            if stat == "completed":
                self.track_label.configure(text="Download Completed")
                self._set_downloading_state(False)
                self.progress_bar.set(1.0)
                self.progress_percent_label.configure(text="100%")
                self.status_bar.configure(text="Download completed successfully")
                self._log(msg or "Download completed", status="success")
                self._refresh_session_stats()
            elif stat == "error":
                err_type = status.get("type", "")
                self.track_label.configure(text=f"Download Failed ({err_type})" if err_type else "Download Failed")
                self._set_downloading_state(False)
                self.status_bar.configure(text="Download failed - see log for details")
                self._log(msg or "Download failed", status="error")
        self.after(0, _update)

    def _set_downloading_state(self, downloading: bool) -> None:
        self._is_downloading = downloading
        if downloading:
            self.download_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self.browse_button.configure(state="disabled")
            self.url_entry.configure(state="disabled")
            self.status_bar.configure(text="Downloading...")
        else:
            self.download_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.browse_button.configure(state="normal")
            self.url_entry.configure(state="normal")
            self.progress_bar.set(0)
            self.progress_percent_label.configure(text="0%")
            self.song_counter_label.configure(text="Ready")
            # Hide fallback badge when download ends
            self.fallback_badge.grid_remove()
            self._fallback_active = False
            self.status_bar.configure(text="Ready")

    def _start_download(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self._log("Error: Please enter a URL", status="error")
            return
        if self.spotdl_manager.is_running():
            self._log("Error: Download already in progress", status="error")
            return
        output_path = self.config_manager.download_directory
        self._current_url = url
        # Truncate URL for display if too long
        display_url = url if len(url) <= 60 else url[:57] + "..."
        self.track_label.configure(text=f"Downloading: {display_url}")
        self._log(f"Starting download: {url}", status="info")
        self._log(f"Output: {output_path}", status="info")
        self._set_downloading_state(True)
        self.spotdl_manager.set_config_manager(self.config_manager)
        self.spotdl_manager.download_track_or_playlist(
            url=url,
            output_path=Path(output_path),
            extra_args=None,
            callback=self._callback,
        )

    def _cancel_download(self) -> None:
        self.spotdl_manager.cancel_download()
        self._log("Download cancelled by user", status="warning")
        self.track_label.configure(text="Download Cancelled")
        self._set_downloading_state(False)
        self.status_bar.configure(text="Download cancelled")
