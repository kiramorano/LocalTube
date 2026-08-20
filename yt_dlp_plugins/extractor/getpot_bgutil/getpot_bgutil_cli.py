from __future__ import annotations
import functools, json, os.path, shutil, subprocess
from yt_dlp.extractor.youtube.pot.provider import (
    PoTokenProviderError, PoTokenRequest, PoTokenResponse,
    register_preference, register_provider,
)
from yt_dlp.extractor.youtube.pot.utils import get_webpo_content_binding
from yt_dlp.utils import Popen
from yt_dlp_plugins.extractor.getpot_bgutil import BgUtilPTPBase

@register_provider
class BgUtilCliPTP(BgUtilPTPBase):
    PROVIDER_NAME = "bgutil:cli"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._check_cli = functools.cache(self._check_cli_impl)
    @functools.cached_property
    def _cli_path(self):
        cli_path = self._configuration_arg("cli_path", casesense=True, default=[None])[0]
        if cli_path:
            return os.path.expandvars(cli_path)
        if self._get_executable_path("bgutil-pot"):
            self.logger.debug("Found bgutil-pot in PATH")
            return "bgutil-pot"
        file_paths = [
            os.path.join(os.getcwd(), "target", "debug", "bgutil-pot"),
            os.path.join(os.getcwd(), "target", "release", "bgutil-pot"),
            os.path.expanduser("~/bgutil-ytdlp-pot-provider/target/debug/bgutil-pot"),
            os.path.expanduser("~/bgutil-ytdlp-pot-provider/target/release/bgutil-pot"),
        ]
        for path in file_paths:
            if self._get_executable_path(path):
                self.logger.debug(f"Found bgutil-pot at: {path}")
                return path
        self.logger.debug("No CLI path found, defaulting to bgutil-pot")
        return "bgutil-pot"
    def is_available(self):
        return self._check_cli(self._cli_path)
    def _get_executable_path(self, cli_path):
        if os.path.sep not in cli_path:
            executable_path = shutil.which(cli_path)
            if executable_path:
                return executable_path
        if os.path.isfile(cli_path):
            return cli_path
        return None
    def _check_cli_impl(self, cli_path):
        executable_path = self._get_executable_path(cli_path)
        if not executable_path:
            self.logger.debug(f"Executable path doesn't exist: {cli_path}")
            return False
        stdout, stderr, returncode = Popen.run(
            [executable_path, "--version"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=self._GET_SERVER_VSN_TIMEOUT
        )
        if returncode:
            self.logger.warning(
                f"Failed to check executable version. Returncode {returncode}", once=True)
            return False
        else:
            self.logger.debug(f"bgutil-pot version: {stdout.strip()}")
            return True
    def _real_request_pot(self, request: PoTokenRequest) -> PoTokenResponse:
        self.logger.trace(f"Generating POT via Rust executable: {self._cli_path}")
        executable_path = self._get_executable_path(self._cli_path)
        if not executable_path:
            raise PoTokenProviderError(f"Executable not found: {self._cli_path}")
        command_args = [executable_path]
        if proxy := request.request_proxy:
            command_args.extend(["-p", proxy])
        command_args.extend(["-c", get_webpo_content_binding(request)[0]])
        if request.bypass_cache:
            command_args.append("--bypass-cache")
        if request.request_source_address:
            command_args.extend(["--source-address", request.request_source_address])
        if request.request_verify_tls is False:
            command_args.append("--disable-tls-verification")
        self.logger.info(
            f"Generating {request.context.value} PO Token for {request.internal_client_name} client via bgutil CLI")
        self.logger.debug(f"Command: {" ".join(command_args)}")
        try:
            stdout, stderr, returncode = Popen.run(
                command_args,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=self._GETPOT_TIMEOUT
            )
        except subprocess.TimeoutExpired as e:
            raise PoTokenProviderError(f"_get_pot_via_cli timeout (caused by {e!r})")
        except Exception as e:
            raise PoTokenProviderError(f"_get_pot_via_cli failed (caused by {e!r})") from e
        msg = ""
        if stdout_extra := stdout.strip().splitlines()[:-1]:
            msg = f"stdout:\\n{stdout_extra}\\n"
        if stderr_stripped := stderr.strip():
            msg += f"stderr:\\n{stderr_stripped}\\n"
        if msg:
            self.logger.trace(msg)
        if returncode:
            raise PoTokenProviderError(f"_get_pot_via_cli failed with returncode {returncode}")
        try:
            json_resp = stdout.splitlines()[-1]
            self.logger.trace(f"JSON response:\\n{json_resp}")
            cli_data_resp = json.loads(json_resp)
        except json.JSONDecodeError as e:
            raise PoTokenProviderError(f"Error parsing JSON (caused by {e!r})") from e
        if "poToken" not in cli_data_resp:
            raise PoTokenProviderError("Executable did not respond with a po_token")
        return PoTokenResponse(po_token=cli_data_resp["poToken"])

@register_preference(BgUtilCliPTP)
def bgutil_cli_getpot_preference(provider, request):
    return 1

__all__ = [BgUtilCliPTP.__name__, bgutil_cli_getpot_preference.__name__]
