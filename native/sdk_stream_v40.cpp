// Native stream adapter targeting the exact HCNetSDK 6.1.11.40 Linux64 ABI.
// Vendor headers/libraries must be staged together; never mix SDK releases.
// PS stream bytes go to stdout; all diagnostics go to stderr.
#include "HCNetSDK.h"
#include <atomic>
#include <chrono>
#include <cerrno>
#include <cstddef>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <mutex>
#include <string>
#include <thread>
#include <unistd.h>

static_assert(sizeof(NET_DVR_USER_LOGIN_INFO) == 416, "V40 login ABI changed");
static_assert(offsetof(NET_DVR_USER_LOGIN_INFO, cbLoginResultV40) == 296, "callback ABI changed");
static_assert(sizeof(NET_DVR_DEVICEINFO_V40) == 344, "V40 device info ABI changed");
static_assert(sizeof(NET_DVR_PREVIEWINFO) == 280, "preview ABI changed");

namespace {
std::atomic<bool> stopping{false};
std::atomic<time_t> last_data{0};
std::mutex write_mutex;
void on_signal(int) { stopping.store(true); }

bool copy_input(char* target, size_t cap, const char* source) {
    if (!source) return false;
    size_t len = strnlen(source, cap);
    if (!len || len >= cap) return false;
    memcpy(target, source, len);
    target[len] = 0;
    return true;
}
void wipe_secret(char* s, size_t n) {
    volatile char* p = s;
    while (n--) *p++ = 0;
}
bool number(const char* text, int initial, int minimum, int maximum, int& result) {
    if (!text || !*text) { result = initial; return true; }
    if (strspn(text, "0123456789") != strlen(text)) return false;
    errno = 0;
    char* end = nullptr;
    long value = strtol(text, &end, 10);
    if (errno || !end || *end || value < minimum || value > maximum) return false;
    result = static_cast<int>(value);
    return true;
}
void CALLBACK on_stream(LONG, DWORD kind, BYTE* buffer, DWORD length, void*) {
    if (stopping.load() || !buffer || !length) return;
    if (kind != NET_DVR_SYSHEAD && kind != NET_DVR_STREAMDATA) return;
    std::lock_guard<std::mutex> guard(write_mutex);
    const BYTE* pos = buffer;
    size_t remaining = length;
    while (remaining && !stopping.load()) {
        ssize_t count = write(STDOUT_FILENO, pos, remaining);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) { stopping.store(true); return; }
        pos += count;
        remaining -= static_cast<size_t>(count);
    }
    last_data.store(time(nullptr));
}
int run(int argc, char** argv) {
    const DWORD ver = NET_DVR_GetSDKBuildVersion();
    if (ver != 0x06010b28) {
        fprintf(stderr, "Incompatible HCNetSDK build: %08x (expected 06010b28)\n", ver);
        return 78;
    }
    const std::string executable(argv[0] ? argv[0] : "");
    const bool smoke = executable.find("sdk-smoke") != std::string::npos ||
                       (argc > 1 && std::string(argv[1]) == "--version");
    const bool login_test = executable.find("sdk-login-test") != std::string::npos ||
                            (argc > 1 && std::string(argv[1]) == "--login-check");
    NET_DVR_LOCAL_SDK_PATH cfg{};
    const char* sdk_root = getenv("HCNETSDK_PATH");
    if (!sdk_root) sdk_root = "/opt/hikvision/lib";
    if (!copy_input(cfg.sPath, sizeof(cfg.sPath), sdk_root)) return 64;
    if (!NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_SDK_PATH, &cfg) || !NET_DVR_Init()) {
        fprintf(stderr, "HCNetSDK initialization failed: %u\n", NET_DVR_GetLastError());
        return 70;
    }
    NET_DVR_SetConnectTime(3000, 2);
    NET_DVR_SetReconnect(10000, true);
    if (smoke) {
        printf("HCNetSDK 6.1.11.40 Linux64; V40 ABI verified\n");
        NET_DVR_Cleanup();
        return 0;
    }
    NET_DVR_USER_LOGIN_INFO login{};
    NET_DVR_DEVICEINFO_V40 device{};
    if (!copy_input(login.sDeviceAddress, sizeof(login.sDeviceAddress), getenv("HCNET_IP")) ||
        !copy_input(login.sUserName, sizeof(login.sUserName), getenv("HCNET_USER")) ||
        !copy_input(login.sPassword, sizeof(login.sPassword), getenv("HCNET_PASSWORD"))) {
        wipe_secret(login.sPassword, sizeof(login.sPassword));
        NET_DVR_Cleanup();
        fprintf(stderr, "Missing or oversized camera credentials\n");
        return 64;
    }
    int port = 0;
    if (!number(getenv("HCNET_PORT"), 8000, 1, 65535, port)) {
        wipe_secret(login.sPassword, sizeof(login.sPassword));
        NET_DVR_Cleanup();
        return 64;
    }
    login.wPort = static_cast<WORD>(port);
    login.bUseAsynLogin = FALSE;
    const LONG user = NET_DVR_Login_V40(&login, &device);
    wipe_secret(login.sPassword, sizeof(login.sPassword));
    if (user < 0) {
        fprintf(stderr, "Camera login error: %u\n", NET_DVR_GetLastError());
        NET_DVR_Cleanup();
        return 69;
    }
    if (login_test) {
        printf("SDK login OK; analog_channels=%u start_channel=%u ip_channels=%u\n",
               device.struDeviceV30.byChanNum, device.struDeviceV30.byStartChan,
               device.struDeviceV30.byIPChanNum);
        NET_DVR_Logout(user);
        NET_DVR_Cleanup();
        return 0;
    }
    int channel = 0, stream_type = 0;
    if (!number(getenv("HCNET_CHANNEL"), 1, 1, 2048, channel) ||
        !number(getenv("HCNET_STREAM_TYPE"), 0, 0, 3, stream_type)) {
        fprintf(stderr, "Invalid camera channel/stream selection\n");
        NET_DVR_Logout(user);
        NET_DVR_Cleanup();
        return 64;
    }
    NET_DVR_PREVIEWINFO preview{};
    preview.lChannel = channel;
    preview.dwStreamType = static_cast<DWORD>(stream_type);
    preview.dwLinkMode = 0;  // TCP, no multicast
    preview.hPlayWnd = nullptr; // compressed stream only, no local rendering
    preview.bBlocked = 1;
    preview.dwDisplayBufNum = 1;
    preview.byReconnect = 1;
    const LONG handle = NET_DVR_RealPlay_V40(user, &preview, on_stream, nullptr);
    if (handle < 0) {
        fprintf(stderr, "Camera preview error: %u\n", NET_DVR_GetLastError());
        NET_DVR_Logout(user);
        NET_DVR_Cleanup();
        return 69;
    }
    last_data.store(time(nullptr));
    while (!stopping.load()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
        if (time(nullptr) - last_data.load() > 90) {
            fprintf(stderr, "HCNetSDK stream stalled for 90 seconds\n");
            stopping.store(true);
        }
    }
    NET_DVR_StopRealPlay(handle);
    NET_DVR_Logout(user);
    NET_DVR_Cleanup();
    return 0;
}
} // namespace

int main(int argc, char** argv) {
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);
    return run(argc, argv);
}
