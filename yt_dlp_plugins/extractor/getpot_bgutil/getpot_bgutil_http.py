from __future__ import annotations
import functools, json, time
from yt_dlp.extractor.youtube.pot.provider import (
    PoTokenProviderError, PoTokenProviderRejectedRequest, PoTokenRequest,
    PoTokenResponse, register_preference, register_provider,
)
from yt_dlp.extractor.youtube.pot.utils import get_webpo_content_binding
from yt_dlp.networking.common import Request
from yt_dlp.networking.exceptions import HTTPError, TransportError
from yt_dlp_plugins.extractor.getpot_bgutil import BgUtilPTPBase

@register_provider
class BgUtilHTTPPTP(BgUtilPTPBase):
    PROVIDER_NAME = "bgutil:http"
    DEFAULT_BASE_URL = "http://127.0.0.1:4416"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_server_check = 0
        self._server_available = True
    @functools.cached_property
    def _base_url(self):
        base_url = self._configuration_arg("base_url", default=[None])[0]
        if base_url:
            return base_url
        self.logger.debug(f"No base_url provided, defaulting to {self.DEFAULT_BASE_URL}")
        return self.DEFAULT_BASE_URL
    def _check_server_availability(self, ctx: PoTokenRequest):
        if self._last_server_check + 60 > time.time():
            return self._server_available
        self._server_available = False
        try:
            self.logger.trace(f"Checking server at {self._base_url}/ping")
            response = json.load(self._request_webpage(Request(
                f"{self._base_url}/ping",
                extensions={"timeout": self._GET_SERVER_VSN_TIMEOUT},
                proxies={"all": None}
            ), note=False))
        except TransportError as e:
            self._warn_and_raise(
                f"Error reaching {self._base_url}/ping (caused by {e.__class__.__name__}). "
                f"Please make sure server is reachable.")
            return
        except HTTPError as e:
            self.logger.warning(f"HTTP Error reaching /ping (caused by {e!r})", once=True)
            return
        except json.JSONDecodeError as e:
            self._warn_and_raise(f"Error parsing ping response JSON (caused by {e!r})")
            return
        except Exception as e:
            self._warn_and_raise(f"Unknown error reaching GET /ping (caused by {e!r})", raise_from=e)
            return
        else:
            version = response.get("version", "unknown")
            self.logger.debug(f"HTTP server version: {version}")
            self._server_available = True
            return True
        finally:
            self._last_server_check = time.time()
    def is_available(self):
        return (self._server_available or self._last_server_check + 60 < int(time.time()))
    def _real_request_pot(self, request: PoTokenRequest) -> PoTokenResponse:
        if not self._check_server_availability(request):
            raise PoTokenProviderRejectedRequest(f"{self.PROVIDER_NAME} server not available")
        self.logger.trace("Generating POT via HTTP server")
        disable_innertube = bool(self._configuration_arg("disable_innertube", default=[None])[0])
        challenge = self._get_attestation(None if disable_innertube else request.video_webpage)
        if not challenge and request.internal_client_name == "web_music":
            if not disable_innertube:
                self.logger.warning("BotGuard challenges missing, overriding disable_innertube=True")
            disable_innertube = True
        try:
            response = self._request_webpage(
                request=Request(
                    f"{self._base_url}/get_pot", data=json.dumps({
                        "bypass_cache": request.bypass_cache,
                        "challenge": challenge,
                        "content_binding": get_webpo_content_binding(request)[0],
                        "disable_innertube": disable_innertube,
                        "disable_tls_verification": not request.request_verify_tls,
                        "proxy": request.request_proxy,
                        "innertube_context": request.innertube_context,
                        "source_address": request.request_source_address,
                    }).encode(), headers={"Content-Type": "application/json"},
                    extensions={"timeout": self._GETPOT_TIMEOUT},
                    proxies={"all": None}
                ),
                note=f"Generating PO Token for {request.internal_client_name} client via bgutil HTTP server",
            )
        except Exception as e:
            raise PoTokenProviderError(f"Error reaching POST /get_pot (caused by {e!r})") from e
        try:
            response_json = json.load(response)
        except Exception as e:
            response_data = response.read().decode()
            raise PoTokenProviderError(
                f"Error parsing response JSON (caused by {e!r}). response = {response_data}"
            ) from e
        if error_msg := response_json.get("error"):
            raise PoTokenProviderError(error_msg)
        if "poToken" not in response_json:
            raise PoTokenProviderError(f"Server did not respond with a poToken. Received: {response}")
        po_token = response_json["poToken"]
        self.logger.trace(f"Generated POT: {po_token}")
        return PoTokenResponse(po_token=po_token)

@register_preference(BgUtilHTTPPTP)
def bgutil_HTTP_getpot_preference(provider, request):
    return 130

__all__ = [BgUtilHTTPPTP.__name__, bgutil_HTTP_getpot_preference.__name__]
