from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def _get_default_download_dir() -> Path:
    """
    Return default download directory for spotDL files.
    
    Defaults to ~/Music/spotDL if available, otherwise falls back to
    platform-appropriate Music directory or ./Downloads.
    
    Returns:
        Path: Default download directory path.
    """
    try:
        home = Path.home()
        music_dir = home / "Music" / "spotDL"
        try:
            music_dir.mkdir(parents=True, exist_ok=True)
            return music_dir
        except Exception:
            pass
        music_dir_fallback = home / "Music"
        try:
            music_dir_fallback.mkdir(parents=True, exist_ok=True)
            return music_dir_fallback
        except Exception:
            pass
    except Exception:
        pass
    
    fallback = Path.cwd() / "Downloads"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return fallback


def _get_config_file_path() -> Path:
    """
    Return path to config.json file.
    
    Uses user config directory with project name, with fallback to project root.
    
    Returns:
        Path: Path to config.json.
    """
    try:
        home = Path.home()
        if os.name == "nt":
            config_base = home / "AppData" / "Local" / "MusicPlayer"
        else:
            config_base = home / ".config" / "musicplayer"
        config_base.mkdir(parents=True, exist_ok=True)
        return config_base / "config.json"
    except Exception:
        return Path.cwd() / "config.json"


class ConfigManager:
    """
    Manages loading, updating, persisting, and resetting user preferences.
    """
    
    DEFAULT_SETTINGS: Dict[str, Any] = {
        "download_directory": str(_get_default_download_dir()),
        "output_template": "{title}.{output-ext}",
        "audio_provider": "youtube-music",
        "auto_fallback": True,
        "overwrite_mode": "skip",
        "bitrate": "320k",
        "format": "mp3",
        "fetch_albums": True,
    }
    
    VALID_AUDIO_PROVIDERS = {"youtube-music", "youtube"}
    VALID_OVERWRITE_MODES = {"skip", "force", "metadata"}
    VALID_BITRATES = {"320k", "256k", "192k", "128k"}
    VALID_FORMATS = {"mp3", "m4a", "flac", "ogg"}
    
    def __init__(self, config_path: Optional[Path] = None) -> None:
        """
        Initialize ConfigManager and load settings.
        
        Args:
            config_path: Optional custom path for config.json.
        """
        self._config_path = config_path or _get_config_file_path()
        self._settings: Dict[str, Any] = {}
        self.load()
    
    @property
    def config_path(self) -> Path:
        """Return current config file path."""
        return self._config_path
    
    def _merge_defaults(self) -> None:
        """Merge defaults into current settings."""
        for key, value in self.DEFAULT_SETTINGS.items():
            if key not in self._settings:
                self._settings[key] = value
    
    def load(self) -> Dict[str, Any]:
        """
        Load settings from config file.
        
        Returns:
            Dict[str, Any]: Loaded settings (merged with defaults).
        """
        self._settings = {}
        try:
            if self._config_path.exists():
                with self._config_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._settings = data
        except Exception:
            self._settings = {}
        if self._settings.get("output_template") in {
            "{artist}/{album}/{title}.{ext}",
            "{artist}/{album}/{title}.{output-ext}",
        }:
            self._settings["output_template"] = self.DEFAULT_SETTINGS["output_template"]
        self._merge_defaults()
        try:
            self._ensure_download_dir()
        except Exception:
            pass
        return self._settings.copy()
    
    def save(self) -> bool:
        """
        Save current settings to config file.
        
        Returns:
            bool: True if saved successfully, False otherwise.
        """
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with self._config_path.open("w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
            return True
        except Exception:
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get setting value by key.
        
        Args:
            key: Setting key.
            default: Default value if key not found.
        
        Returns:
            Any: Setting value.
        """
        return self._settings.get(key, default)
    
    def set(self, key: str, value: Any) -> bool:
        """
        Set setting value with validation.
        
        Args:
            key: Setting key.
            value: New value.
        
        Returns:
            bool: True if set and valid, False otherwise.
        """
        if key == "download_directory":
            try:
                path = Path(value) if not isinstance(value, Path) else value
                path.mkdir(parents=True, exist_ok=True)
                self._settings[key] = str(path)
                return True
            except Exception:
                return False
        elif key == "output_template":
            if isinstance(value, str) and value:
                self._settings[key] = value
                return True
            return False
        elif key == "audio_provider":
            if isinstance(value, str) and value in self.VALID_AUDIO_PROVIDERS:
                self._settings[key] = value
                return True
            return False
        elif key == "auto_fallback":
            if isinstance(value, bool):
                self._settings[key] = value
                return True
            return False
        elif key == "overwrite_mode":
            if isinstance(value, str) and value in self.VALID_OVERWRITE_MODES:
                self._settings[key] = value
                return True
            return False
        elif key == "bitrate":
            if isinstance(value, str) and value in self.VALID_BITRATES:
                self._settings[key] = value
                return True
            return False
        elif key == "format":
            if isinstance(value, str) and value in self.VALID_FORMATS:
                self._settings[key] = value
                return True
            return False
        elif key == "fetch_albums":
            if isinstance(value, bool):
                self._settings[key] = value
                return True
            return False
        return False
    
    def update(self, settings: Dict[str, Any]) -> Dict[str, bool]:
        """
        Update multiple settings.
        
        Args:
            settings: Dictionary of key-value pairs to update.
        
        Returns:
            Dict[str, bool]: Results per key (True if updated).
        """
        results = {}
        for key, value in settings.items():
            results[key] = self.set(key, value)
        return results
    
    def reset(self) -> None:
        """
        Reset settings to defaults.
        """
        self._settings = self.DEFAULT_SETTINGS.copy()
        try:
            self._ensure_download_dir()
        except Exception:
            pass
    
    def _ensure_download_dir(self) -> Path:
        """
        Ensure download directory exists.
        
        Returns:
            Path: Download directory path.
        """
        path_str = self._settings.get("download_directory", self.DEFAULT_SETTINGS["download_directory"])
        path = Path(path_str)
        try:
            path.mkdir(parents=True, exist_ok=True)
            self._settings["download_directory"] = str(path)
        except Exception:
            pass
        return path
    
    @property
    def download_directory(self) -> Path:
        """Return download directory as Path."""
        return self._ensure_download_dir()
    
    @property
    def output_template(self) -> str:
        """Return output template string."""
        return self.get("output_template", self.DEFAULT_SETTINGS["output_template"])
    
    @property
    def audio_provider(self) -> str:
        """Return audio provider."""
        return self.get("audio_provider", self.DEFAULT_SETTINGS["audio_provider"])
    
    @property
    def auto_fallback(self) -> bool:
        """Return auto_fallback flag."""
        return bool(self.get("auto_fallback", self.DEFAULT_SETTINGS["auto_fallback"]))
    
    @property
    def overwrite_mode(self) -> str:
        """Return overwrite mode."""
        return self.get("overwrite_mode", self.DEFAULT_SETTINGS["overwrite_mode"])
    
    @property
    def bitrate(self) -> str:
        """Return bitrate setting."""
        return self.get("bitrate", self.DEFAULT_SETTINGS["bitrate"])
    
    @property
    def format(self) -> str:
        """Return audio format setting."""
        return self.get("format", self.DEFAULT_SETTINGS["format"])
    
    @property
    def fetch_albums(self) -> bool:
        """Return fetch_albums flag."""
        return bool(self.get("fetch_albums", self.DEFAULT_SETTINGS["fetch_albums"]))
