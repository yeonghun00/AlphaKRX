"""
Simple configuration loader for KRX stock data system.
Loads configuration from config.json file with environment variable overrides.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any

def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """
    Load configuration from JSON file with environment variable overrides.
    
    Environment variables take precedence over config.json values.
    Supported env vars:
        - KRX_AUTH_KEY: API authentication key
        - KIWOOM_APP_KEY: Kiwoom API app key
        - KIWOOM_APP_SECRET: Kiwoom API secret
        - KIWOOM_ACCOUNT: Kiwoom account number
        - KIWOOM_MOCK: Use mock trading (true/false)
        - DATABASE_PATH: Path to SQLite database
        
    Args:
        config_path (str): Path to configuration file
        
    Returns:
        Dict[str, Any]: Configuration dictionary
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file has invalid JSON
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in configuration file: {e}")

    config = _apply_env_overrides(config)
    logging.info(f"Loaded configuration from {config_path}")
    return config


def _apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to config."""
    
    if "KRX_AUTH_KEY" in os.environ:
        if "api" not in config:
            config["api"] = {}
        config["api"]["auth_key"] = os.environ["KRX_AUTH_KEY"]
    
    if "KIWOOM_APP_KEY" in os.environ:
        if "kiwoom" not in config:
            config["kiwoom"] = {}
        config["kiwoom"]["app_key"] = os.environ["KIWOOM_APP_KEY"]
    
    if "KIWOOM_APP_SECRET" in os.environ:
        if "kiwoom" not in config:
            config["kiwoom"] = {}
        config["kiwoom"]["app_secret"] = os.environ["KIWOOM_APP_SECRET"]
    
    if "KIWOOM_ACCOUNT" in os.environ:
        if "kiwoom" not in config:
            config["kiwoom"] = {}
        config["kiwoom"]["account"] = os.environ["KIWOOM_ACCOUNT"]
    
    if "KIWOOM_MOCK" in os.environ:
        if "kiwoom" not in config:
            config["kiwoom"] = {}
        config["kiwoom"]["mock"] = os.environ["KIWOOM_MOCK"].lower() == "true"
    
    if "DATABASE_PATH" in os.environ:
        if "database" not in config:
            config["database"] = {}
        config["database"]["path"] = os.environ["DATABASE_PATH"]
    
    return config

def get_api_key(config: Dict[str, Any]) -> str:
    """
    Get API key from configuration.
    
    Args:
        config (Dict[str, Any]): Configuration dictionary
        
    Returns:
        str: API key
    """
    return config.get('api', {}).get('auth_key', '')

def get_database_path(config: Dict[str, Any]) -> str:
    """
    Get database path from configuration.
    
    Args:
        config (Dict[str, Any]): Configuration dictionary
        
    Returns:
        str: Database path
    """
    return config.get('database', {}).get('path', 'data/krx_stock_data.db')

def get_request_delay(config: Dict[str, Any]) -> float:
    """
    Get request delay from configuration.
    
    Args:
        config (Dict[str, Any]): Configuration dictionary
        
    Returns:
        float: Request delay in seconds
    """
    return config.get('api', {}).get('request_delay', 1.0)