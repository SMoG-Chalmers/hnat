import os, sys, ctypes

def GetBackwardsCompatiblePath(path):
    if not sys.platform.startswith('win'):
        return path
    buf = ctypes.create_unicode_buffer(260)  # Allocate buffer for the short path name (max length 260)
    ctypes.windll.kernel32.GetShortPathNameW(os.path.normpath(path), buf, len(buf))  # Call Windows API
    return buf.value