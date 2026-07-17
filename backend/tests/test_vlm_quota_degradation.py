"""Regression tests for VLM quota/auth error classification.

History: when the VLM provider's free-tier quota was exhausted, every video
frame description failed and ``process_video_document`` raised a bare
``ValueError("...所有帧的VLM描述均失败...")``, surfacing the upstream 403
verbatim and hard-failing the document task (then retrying pointlessly).
The classifier ``_is_vlm_quota_or_auth_error`` drives the new fallback /
skip-on-quota degradation paths.
"""

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.media_processing import (
    _is_vlm_quota_or_auth_error,
)

pytestmark = pytest.mark.unit


def test_classifies_user_reported_quota_error():
    """The exact 403 AllocationQuota.FreeTierOnly error from the bug report must classify as quota/auth."""
    exc = Exception(
        "Error code: 403 - {'error': {'message': 'The free quota has been exhausted. "
        "To continue accessing the model on a paid basis, please complete your payment "
        "information (or disable the \"use free tier only\" mode in the management console "
        "if already completed).', 'type': 'AllocationQuota.FreeTierOnly', 'code': "
        "'AllocationQuota.FreeTierOnly'}}"
    )
    assert _is_vlm_quota_or_auth_error(exc) is True


def test_classifies_auth_errors():
    assert _is_vlm_quota_or_auth_error(Exception("Unauthorized: invalid api key")) is True
    assert _is_vlm_quota_or_auth_error(Exception("401 Authentication required")) is True
    assert _is_vlm_quota_or_auth_error(Exception("Permission denied")) is True


def test_does_not_classify_unrelated_errors():
    assert _is_vlm_quota_or_auth_error(Exception("Connection timed out")) is False
    assert _is_vlm_quota_or_auth_error(Exception("invalid image format")) is False
    assert _is_vlm_quota_or_auth_error(Exception("model returned empty response")) is False