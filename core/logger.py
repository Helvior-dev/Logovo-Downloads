"""Centralized logging setup for Logovo Downloads."""
import logging
import os
from pathlib import Path
from core.settings import get_app_data_dir

_logger_initialized = False


def get_logger(name: str = "logovo") -> logging.Logger:
    """Return a configured logger. Call this from any module."""
    global _logger_initialized
    logger = logging.getLogger(name)
    
    if not _logger_initialized:
        _setup_logging()
        _logger_initialized = True
    
    return logger


def _setup_logging() -> None:
    """Configure root logger to write to app_logs.txt with rotation-safe appending."""
    root = logging.getLogger("logovo")
    root.setLevel(logging.DEBUG)
    
    if root.handlers:
        return
    
    try:
        log_path = get_app_data_dir() / "app_logs.txt"
        fh = logging.FileHandler(str(log_path), encoding="utf-8", mode="a")
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)
    except Exception:
        # Fall back to stderr if file logging fails
        sh = logging.StreamHandler()
        sh.setLevel(logging.WARNING)
        root.addHandler(sh)
    
    root.info("=" * 60)
    root.info("Logovo Downloads session started")
    root.info("=" * 60)
