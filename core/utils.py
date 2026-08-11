def format_bytes(bytes_num: int) -> str:
    """Format bytes to human-readable string (KB, MB, GB)."""
    if bytes_num is None:
        return "Unknown size"
    
    for x in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if bytes_num < 1024.0:
            return "%3.1f %s" % (bytes_num, x)
        bytes_num /= 1024.0
    
    return "%3.1f %s" % (bytes_num, 'PB')

def sanitize_filename(filename: str) -> str:
    """Basic sanitize string to be used as filename."""
    keepcharacters = (' ', '.', '_', '-')
    return "".join(c for c in filename if c.isalnum() or c in keepcharacters).rstrip()
