"""Input validation shared by SDK camera actions and live-stream paths.

SDK channel numbers also appear in /data/hls and snapshot filenames; accepting
untrusted path separators can escape those directories during cleanup.
"""


def normalize_sdk_channel(value):
    """Return a safe decimal channel or empty string when not specified."""
    if value is None or value == "":
        return ""
    text = str(value).strip()
    if not text or len(text) > 4 or not text.isascii() or not text.isdecimal():
        raise ValueError("Недопустимый номер канала камеры")
    channel = int(text)
    if not 1 <= channel <= 2048:
        raise ValueError("Номер канала камеры должен быть от 1 до 2048")
    return str(channel)
