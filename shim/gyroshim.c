/* Rotate the Deck's sensor axes into the frame a PS4 game expects.
 *
 * THE BUG THIS WORKS AROUND. shadPS4 copies SDL's gamepad sensor axes straight
 * into the emulated DualShock without converting them, but SDL's convention is
 * not Sony's. SDL reports a DualShock's face normal as +Y -- a gamepad's
 * neutral pose is face-up -- while it reports the Deck's top-edge direction as
 * +Y and its screen normal as +Z, because a handheld's neutral pose is
 * screen-toward-you. Those are different physical axes, 90 degrees apart about
 * X. X is left-right on both, so pitch works; Y and Z are swapped, so yaw and
 * roll land on each other and horizontal aiming does nothing.
 *
 * shadPS4 gets away with it for a real DualSense only by accident: SDL's PS5
 * driver passes that controller's raw values through unremapped, so they are
 * already in Sony's frame. Every controller SDL normalises is wrong.
 *
 * Measured on a Deck rather than reasoned about: a real 90 degree yaw arrives
 * as -89.1 deg on z[2] and +23.5 deg on y[1]. Vita3K converts correctly and has
 * done for years -- `vita3k/motion/src/motion.cpp`, the `from_gamepad` branch,
 * is this same rotation.
 *
 * WHY A SHIM RATHER THAN A PATCHED EMULATOR. shadPS4 links libSDL3 dynamically
 * and reads sensors through SDL_WaitEvent, so LD_PRELOAD can sit between them
 * and rotate the three floats in flight. The flatpak stays stock and keeps
 * updating; nothing is forked, pinned, or rebuilt.
 *
 * DELETE ALL OF THIS when shadPS4 converts the sensor frame itself. Asked for
 * upstream as shadps4-emu/shadPS4#3871. When it lands, drop this file, the
 * LD_PRELOAD line in the shadPS4 catalog entry, and the build steps in
 * `scripts/deploy.sh` and CI -- the rest of that entry stays.
 *
 * Built for the Deck, by `scripts/deploy.sh` and by CI, with the flatpak SDK so
 * the glibc it targets matches the runtime shadPS4 runs in.
 *
 * The rotation is settable so it never has to be guessed at again:
 *   GYROSHIM_MODE   three terms saying where the new x, y and z come from.
 *                   Defaults to the verified `x,-z,y`. `x,y,z` disables it.
 *   GYROSHIM_LOG    print the first twenty sensor events, in and out.
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SDL_EVENT_GAMEPAD_SENSOR_UPDATE 0x659
#define SDL_SENSOR_ACCEL 1
#define SDL_SENSOR_GYRO  2

/* Declared rather than included, so no SDL headers are needed. Field order is
 * from SDL3's SDL_events.h; letting the compiler lay it out avoids hand
 * arithmetic on the offsets. */
typedef struct {
    uint32_t type;
    uint32_t reserved;
    uint64_t timestamp;
    uint32_t which;
    int32_t sensor;
    float data[3];
    uint64_t sensor_timestamp;
} GamepadSensorEvent;

/* Source index per output slot and the sign to apply, defaulting to the
 * rotation verified on a Deck in Gravity Rush Remastered: (x, y, z) ->
 * (x, -z, y). `(x, z, -y)` is the same rotation the other way and comes out
 * inverted; `(x, -z, -y)` is a reflection, determinant -1, which would fix
 * yaw and silently leave roll backwards. */
static int g_src[3] = {0, 2, 1};
static float g_sign[3] = {1.0f, -1.0f, 1.0f};
static int g_ready = 0;
static int g_do_gyro = 1, g_do_accel = 1;
static int g_log = 0, g_logged = 0;

static void parse_term(const char *term, int slot) {
    float sign = 1.0f;
    while (*term == ' ') term++;
    if (*term == '-') { sign = -1.0f; term++; }
    else if (*term == '+') { term++; }
    if (*term >= 'x' && *term <= 'z') {
        g_src[slot] = *term - 'x';
        g_sign[slot] = sign;
    } else if (*term >= 'X' && *term <= 'Z') {
        g_src[slot] = *term - 'X';
        g_sign[slot] = sign;
    }
}

static void parse_mode(const char *spec) {
    char buf[64];
    char *save = NULL, *token;
    int slot = 0;
    snprintf(buf, sizeof buf, "%s", spec);
    for (token = strtok_r(buf, ",", &save); token && slot < 3;
         token = strtok_r(NULL, ",", &save)) {
        parse_term(token, slot++);
    }
}

static void init_once(void) {
    const char *spec = getenv("GYROSHIM_MODE");
    if (spec && *spec) parse_mode(spec);

    const char *which = getenv("GYROSHIM_SENSORS");
    if (which) {
        g_do_gyro = (strstr(which, "gyro") != NULL) || (strcmp(which, "both") == 0);
        g_do_accel = (strstr(which, "accel") != NULL) || (strcmp(which, "both") == 0);
    }

    const char *log = getenv("GYROSHIM_LOG");
    g_log = (log && *log && strcmp(log, "0") != 0);

    fprintf(stderr, "[gyroshim] mode: x<=%c%c y<=%c%c z<=%c%c  gyro=%d accel=%d\n",
            g_sign[0] < 0 ? '-' : '+', 'x' + g_src[0],
            g_sign[1] < 0 ? '-' : '+', 'x' + g_src[1],
            g_sign[2] < 0 ? '-' : '+', 'x' + g_src[2],
            g_do_gyro, g_do_accel);
    fflush(stderr);
    g_ready = 1;
}

static void maybe_permute(void *event) {
    GamepadSensorEvent *e = (GamepadSensorEvent *)event;
    float in[3];
    int i;

    if (!event) return;
    if (!g_ready) init_once();
    if (e->type != SDL_EVENT_GAMEPAD_SENSOR_UPDATE) return;
    if (e->sensor == SDL_SENSOR_GYRO && !g_do_gyro) return;
    if (e->sensor == SDL_SENSOR_ACCEL && !g_do_accel) return;
    if (e->sensor != SDL_SENSOR_GYRO && e->sensor != SDL_SENSOR_ACCEL) return;

    in[0] = e->data[0];
    in[1] = e->data[1];
    in[2] = e->data[2];
    for (i = 0; i < 3; i++) e->data[i] = g_sign[i] * in[g_src[i]];

    /* Proof that interception is really happening, rather than an assumption
     * that it is. Twenty lines, then quiet. */
    if (g_log && g_logged < 20) {
        g_logged++;
        fprintf(stderr, "[gyroshim] sensor %d  in %+7.3f %+7.3f %+7.3f"
                        "  out %+7.3f %+7.3f %+7.3f\n",
                e->sensor, in[0], in[1], in[2],
                e->data[0], e->data[1], e->data[2]);
        fflush(stderr);
    }
}

typedef _Bool (*wait_fn)(void *);
typedef _Bool (*wait_timeout_fn)(void *, int32_t);

_Bool SDL_WaitEvent(void *event) {
    static wait_fn real = NULL;
    _Bool got;
    if (!real) real = (wait_fn)dlsym(RTLD_NEXT, "SDL_WaitEvent");
    got = real(event);
    if (got) maybe_permute(event);
    return got;
}

_Bool SDL_PollEvent(void *event) {
    static wait_fn real = NULL;
    _Bool got;
    if (!real) real = (wait_fn)dlsym(RTLD_NEXT, "SDL_PollEvent");
    got = real(event);
    if (got) maybe_permute(event);
    return got;
}

_Bool SDL_WaitEventTimeout(void *event, int32_t timeout) {
    static wait_timeout_fn real = NULL;
    _Bool got;
    if (!real) real = (wait_timeout_fn)dlsym(RTLD_NEXT, "SDL_WaitEventTimeout");
    got = real(event, timeout);
    if (got) maybe_permute(event);
    return got;
}
