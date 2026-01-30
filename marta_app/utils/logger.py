"""
Logging utilities for MARTA GUI.

Provides structured logging with file and console handlers.
"""

import logging
import os
from datetime import datetime
from typing import Optional


def setup_logger(
    name: str = 'marta_gui',
    log_dir: Optional[str] = None,
    log_level: int = logging.DEBUG
) -> logging.Logger:
    """
    Set up structured logger with file and console handlers.
    
    Args:
        name: Logger name
        log_dir: Directory for log files (None = logs to console only)
        log_level: Logging level (default: DEBUG)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger
    
    logger.setLevel(log_level)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler (INFO level)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (DEBUG level) - if log_dir provided
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(
                log_dir,
                f'marta_gui_{datetime.now():%Y%m%d}.log'
            )
            
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            
            logger.info(f"Logging to file: {log_file}")
        except Exception as e:
            logger.warning(f"Could not create log file: {e}")
    
    return logger


def get_logger(name: str = 'marta_gui') -> logging.Logger:
    """
    Get existing logger instance.
    
    Args:
        name: Logger name
    
    Returns:
        Logger instance
    """
    return logging.getLogger(name)
