from __future__ import annotations

import secrets
from dataclasses import dataclass

from .errors import ActivationCodeError
from .profile import EsimProfile


@dataclass(slots=True)
class DownloadResult:
    profile: EsimProfile


class ISmdpClient:
    """Interface for SM-DP+ client implementations."""
    
    def download_profile(
        self,
        *,
        smdp_address: str,
        activation_code: str,
        eid: str,
        imei: str,
        confirmation_code: str | None = None,
    ) -> DownloadResult:
        """
        Download profile from SM-DP+ server.
        
        Args:
            smdp_address: SM-DP+ server address/URL
            activation_code: One-time activation code (LPA activation code)
            eid: Device EID
            imei: Device IMEI
            confirmation_code: Optional confirmation code from operator
            
        Returns:
            DownloadResult with profile
            
        Raises:
            ActivationCodeError: If activation code is invalid or already used
        """
        raise NotImplementedError


class MockSmdpClient(ISmdpClient):
    """Mock SM-DP+ client for testing (offline, generates fake profiles)."""

    def __init__(self, *, default_operator: str = "MockOperator"):
        self._default_operator = default_operator

    def download_profile(
        self,
        *,
        smdp_address: str,
        activation_code: str,
        eid: str,
        imei: str,
        confirmation_code: str | None = None,
    ) -> DownloadResult:
        """
        Mock profile download - generates a fake profile.
        In real implementation, this would make HTTPS request to SM-DP+ server.
        """
        # Generate random ICCID (ITU-T E.118 format: 89 + 18 digits)
        iccid = "89" + "".join(str(secrets.randbelow(10)) for _ in range(18))
        profile_id = f"p-{secrets.token_hex(4)}"
        
        profile = EsimProfile(
            id=profile_id,
            iccid=iccid,
            operator_name=self._default_operator,
            smdp_address=smdp_address,
            activation_code=activation_code,
            msisdn=None,  # Will be set later if provided
        )
        return DownloadResult(profile=profile)

