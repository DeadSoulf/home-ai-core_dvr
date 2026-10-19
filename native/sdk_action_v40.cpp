// HCNetSDK 6.1.11.40 Linux64 action bridge. Build only with matching headers.
// Never prints camera passwords or writes archive files.
#include "HCNetSDK.h"
#include <cerrno>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <chrono>

static_assert(sizeof(NET_DVR_USER_LOGIN_INFO) == 416, "HCNetSDK V40 ABI mismatch");
static_assert(offsetof(NET_DVR_USER_LOGIN_INFO, cbLoginResultV40) == 296, "HCNetSDK callback mismatch");
static_assert(sizeof(NET_DVR_DEVICEINFO_V40) == 344, "HCNetSDK device mismatch");

namespace {
void wipe(char* value, size_t length) {
    volatile char* p = value;
    while (length--) *p++ = 0;
}
bool copy_field(char* dst, size_t capacity, const char* value) {
    if (!value) return false;
    const size_t length = strnlen(value, capacity);
    if (!length || length >= capacity) return false;
    memcpy(dst, value, length);
    dst[length] = 0;
    return true;
}
bool int_value(const char* input, int min, int max, int& out) {
    if (!input || !*input || strspn(input, "0123456789") != strlen(input)) return false;
    errno = 0;
    char* end = nullptr;
    const long n = strtol(input, &end, 10);
    if (errno || !end || *end || n < min || n > max) return false;
    out = static_cast<int>(n);
    return true;
}
int run(int argc, char** argv) {
    if (argc < 3 || !argv[1] || !argv[2]) return 64;
    const std::string mode = argv[1];
    if (mode != "snapshot" && mode != "ptz" && mode != "preset") return 64;

    NET_DVR_LOCAL_SDK_PATH cfg{};
    const char* sdkPath = getenv("HCNETSDK_PATH");
    if (!sdkPath) sdkPath = "/opt/hikvision/lib";
    if (!copy_field(cfg.sPath, sizeof(cfg.sPath), sdkPath) ||
        !NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_SDK_PATH, &cfg) || !NET_DVR_Init()) {
        fprintf(stderr, "HCNetSDK initialization failed\n");
        return 70;
    }
    const DWORD version = NET_DVR_GetSDKBuildVersion();
    if (version != 0x06010b28) {
        fprintf(stderr, "Incorrect HCNetSDK version: %08x\n", version);
        NET_DVR_Cleanup();
        return 78;
    }
    NET_DVR_USER_LOGIN_INFO login{};
    NET_DVR_DEVICEINFO_V40 info{};
    bool good = copy_field(login.sDeviceAddress, sizeof(login.sDeviceAddress), getenv("HCNET_IP")) &&
                copy_field(login.sUserName, sizeof(login.sUserName), getenv("HCNET_USER")) &&
                copy_field(login.sPassword, sizeof(login.sPassword), getenv("HCNET_PASSWORD"));
    int port = 0, channel = 1;
    const char* envChannel = getenv("HCNET_CHANNEL");
    good = good && int_value(getenv("HCNET_PORT") ? getenv("HCNET_PORT") : "8000", 1, 65535, port) &&
           int_value(envChannel && *envChannel ? envChannel : "1", 1, 2048, channel);
    if (!good) {
        wipe(login.sPassword, sizeof(login.sPassword));
        NET_DVR_Cleanup();
        return 64;
    }
    login.wPort = static_cast<WORD>(port);
    login.bUseAsynLogin = FALSE;
    NET_DVR_SetConnectTime(3000, 2);
    const LONG user = NET_DVR_Login_V40(&login, &info);
    wipe(login.sPassword, sizeof(login.sPassword));
    if (user < 0) {
        fprintf(stderr, "Camera authentication failed (%u)\n", NET_DVR_GetLastError());
        NET_DVR_Cleanup();
        return 69;
    }
    bool ok = false;
    if (mode == "snapshot") {
        if (argc != 3) {
            fprintf(stderr, "Invalid snapshot arguments\n");
        } else {
            const std::string target(argv[2]);
            const char* rootEnv = getenv("NVR_DATA_ROOT");
            const std::string root = rootEnv && *rootEnv ? rootEnv : "/data";
            const std::string base = "snapshot_ch";
            const std::string prefix = root + "/" + base;
            if (target.compare(0, prefix.size(), prefix) == 0 && target.size() < prefix.size() + 13 &&
                target.size() > prefix.size() + 4 && target.substr(target.size()-4) == ".jpg" &&
                target.find('/', prefix.size()) == std::string::npos) {
                NET_DVR_JPEGPARA jpeg{};
                jpeg.wPicSize = 0xff;
                jpeg.wPicQuality = 0;
                ok = NET_DVR_CaptureJPEGPicture(user, channel, &jpeg, const_cast<char*>(target.c_str())) != FALSE;
            } else {
                fprintf(stderr, "Snapshot target is outside allowed NVR data directory\n");
            }
        }
    } else if (mode == "ptz") {
        if (argc == 5) {
            const std::string action(argv[2]);
            const struct { const char* name; DWORD code; } directions[] = {
                {"up", TILT_UP}, {"down", TILT_DOWN},
                {"left", PAN_LEFT}, {"right", PAN_RIGHT},
                {"up_left", UP_LEFT}, {"up_right", UP_RIGHT},
                {"down_left", DOWN_LEFT}, {"down_right", DOWN_RIGHT},
                {"zoom_in", ZOOM_IN}, {"zoom_out", ZOOM_OUT},
                {"focus_near", FOCUS_NEAR}, {"focus_far", FOCUS_FAR},
                {"iris_open", IRIS_OPEN}, {"iris_close", IRIS_CLOSE},
            };
            int speed = 0, duration = 0;
            if (int_value(argv[3], 1, 7, speed) && int_value(argv[4], 50, 2000, duration)) {
                for (const auto& command : directions) {
                    if (action != command.name) continue;
                    const bool started = NET_DVR_PTZControlWithSpeed_Other(user, channel, command.code, 0, static_cast<DWORD>(speed)) != FALSE;
                    if (started) std::this_thread::sleep_for(std::chrono::milliseconds(duration));
                    const bool stopped = NET_DVR_PTZControlWithSpeed_Other(user, channel, command.code, 1, static_cast<DWORD>(speed)) != FALSE;
                    ok = started && stopped;
                    break;
                }
            }
        }
    } else if (mode == "preset") {
        if (argc == 4) {
            const std::string action(argv[2]);
            int index = 0;
            if (int_value(argv[3], 1, 300, index)) {
                if (action == "set") ok = NET_DVR_PTZPreset_Other(user, channel, SET_PRESET, static_cast<DWORD>(index)) != FALSE;
                else if (action == "goto") ok = NET_DVR_PTZPreset_Other(user, channel, GOTO_PRESET, static_cast<DWORD>(index)) != FALSE;
            }
        }
    }
    if (!ok) fprintf(stderr, "HCNetSDK %s operation failed (%u)\n", mode.c_str(), NET_DVR_GetLastError());
    NET_DVR_Logout(user);
    NET_DVR_Cleanup();
    if (ok) printf("HCNetSDK %s OK\n", mode.c_str());
    return ok ? 0 : 69;
}
}
int main(int argc, char** argv) { return run(argc, argv); }
