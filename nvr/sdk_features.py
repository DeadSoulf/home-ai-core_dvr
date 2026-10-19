"""Operation support advertised by the exact local HCNetSDK profile.

The SDK611 opt-in image replaces legacy native binaries with verified V40
adapters. Unported proprietary APIs must fail explicitly, not be attempted.
"""

SDK611_UNSUPPORTED_POST = frozenset({
    "/api/device-status", "/api/events/start", "/api/ability",
    "/api/net-usage", "/api/alarm-test", "/api/voice-test",
    "/api/archive-search", "/api/archive-prepare",
})


def capabilities(profile):
    advanced = profile != "hcnet611-local"
    return {
        "login": True,
        "record": True,
        "live": True,
        "snapshot": True,
        "ptz": True,
        "preset": True,
        "device_status": advanced,
        "events": advanced,
        "network_usage": advanced,
        "ability": advanced,
        "voice": advanced,
        "remote_archive": advanced,
    }


def unsupported_sdk_post(profile, path):
    return profile == "hcnet611-local" and path in SDK611_UNSUPPORTED_POST
