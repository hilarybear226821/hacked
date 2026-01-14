import logging
import os
import functools
import json
from datetime import datetime
from typing import Any, Callable

class AttackLogger:
    """
    Centralized logger for all attack modules.
    Logs to both console (brief) and file (detailed).
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AttackLogger, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        self.logger = logging.getLogger("AttackLogger")
        self.logger.setLevel(logging.DEBUG)
        
        # Ensure log directory exists
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_dir = os.path.join(base_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        # File Handler (Detailed JSON-like)
        file_handler = logging.FileHandler(os.path.join(log_dir, "attacks.log"))
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - [%(levelname)s] - %(name)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        
        # Console Handler (Brief)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '[Attack] %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        
        if not self.logger.handlers:
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)
            
    def log(self, level: int, msg: str, extra: dict = None):
        if extra:
            msg = f"{msg} | Data: {json.dumps(extra, default=str)}"
        self.logger.log(level, msg)

def log_attack_step(func: Callable) -> Callable:
    """
    Decorator to log attack steps automatically.
    Logs entry, exit, and any exceptions.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = AttackLogger()
        func_name = func.__name__
        module_name = func.__module__
        
        # Sanitize args for logging (avoid huge objects)
        safe_kwargs = {k: str(v)[:100] for k, v in kwargs.items()}
        
        logger.log(logging.INFO, f"Starting {func_name}...", extra={'module': module_name, 'args': safe_kwargs})
        
        start_time = datetime.now()
        try:
            result = func(*args, **kwargs)
            duration = (datetime.now() - start_time).total_seconds()
            logger.log(logging.INFO, f"Completed {func_name}", extra={'duration': duration, 'status': 'success'})
            return result
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.log(logging.ERROR, f"Failed {func_name}: {e}", extra={'duration': duration, 'status': 'error', 'error': str(e)})
            raise e
            
    return wrapper
