import os
import re


def is_production():
    # Existing Render services need the production protections on their first push,
    # even before an operator adds the optional ENVIRONMENT variable.
    return os.getenv('ENVIRONMENT', '').lower() == 'production' or os.getenv('RENDER', '').lower() == 'true'


def deployment_revision():
    revision = os.getenv('RENDER_GIT_COMMIT', '')
    return revision[:12] if re.fullmatch(r'[0-9a-fA-F]{7,40}', revision) else 'unknown'
