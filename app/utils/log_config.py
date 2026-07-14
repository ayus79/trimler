import inspect
import logging
import os
from datetime import datetime


def log_message(
    message: str,
    file_name: str = "log",
    *,
    critical: bool = False,
    error: bool = False,
    warning: bool = False,
    info: bool = False,
    monthly: bool = False,
):
    """
    Logs a message to a specified file inside the 'logs/' directory.

    Args:
        message (str): The log message.
        file_name (str): Name of the log file (without extension), Default is log.
        critical (bool): Log as an CRITICAL if True.
        error (bool): Log as an ERROR if True.
        warning (bool): Log as a WARNING if True.
        info (bool): Log as INFO if True.
        monthly (bool): If True, writes to a monthly log file (mm-yyyy) instead of a daily one.
    """
    os.makedirs("logs", exist_ok=True)
    now = datetime.now()
    date_suffix = now.strftime("%m-%Y") if monthly else now.strftime("%d-%m-%Y")
    log_path = os.path.join("logs", f"{file_name}_{date_suffix}.log")

    try:
        frame = inspect.currentframe().f_back
        module_name = frame.f_globals.get("__name__", "Unknown")
        function_name = frame.f_code.co_name if frame else "Unknown"
        # line_number = frame.f_lineno
    except Exception:
        module_name, function_name = "Unknown", "Unknown"

    # Use distinct logger keys so monthly and daily loggers for the same file_name don't share handlers
    logger_key = f"{file_name}_monthly" if monthly else file_name
    logger = logging.getLogger(logger_key)

    if not logger.handlers:
        handler = logging.FileHandler(log_path)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    log_msg = f"[{module_name}.{function_name}] {message}"
    if critical:
        logger.critical(log_msg)
    elif error:
        logger.error(log_msg)
    elif warning:
        logger.warning(log_msg)
    elif info:
        logger.info(log_msg)
    else:
        logger.debug(log_msg)
