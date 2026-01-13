"""Common utilities for dialogs."""


def get_form_value(data: dict, key: str, default: str = "") -> str:
    """Get value from dialog data, handling None and empty strings.
    
    Args:
        data: Dialog data dictionary.
        key: Key to get value for.
        default: Default value to return if key is None or empty.
        
    Returns:
        Value from data or default if None/empty.
    """
    value = data.get(key)
    return default if value is None or value == "" else value

