import os


def is_production():
    # Existing Render services need the production protections on their first push,
    # even before an operator adds the optional ENVIRONMENT variable.
    return os.getenv('ENVIRONMENT', '').lower() == 'production' or os.getenv('RENDER', '').lower() == 'true'
