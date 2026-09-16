/* LD_PRELOAD shim for Civ5XP (32-bit, Aspyr Linux build 1.0.3.279).  Two fixes for the FireTuner:
 *
 * 1. recv(fd, NULL, 0, 0) disconnect probe.
 *    cvTunerListener::OnUpdate polls the tuner connection with a zero-length recv and treats -1 as
 *    "client gone" (Windows semantics).  On Linux a zero-length recv returns 0 even after the peer
 *    closed, so the game never re-accepts a tuner client.  We turn len==0 into a 1-byte MSG_PEEK.
 *
 * 2. Keep the tuner alive in multiplayer.
 *    cvTunerListener::OnMultiplayerGameLaunched() calls cvTunerListener::Disable() when a hotseat /
 *    LAN / internet game launches (anti-cheat).  The LLM harness *is* a multiplayer client, so at
 *    load time we NOP that one `call Disable` after verifying the bytes and the call target.
 *
 * 3. Port / address remap on bind() (LAN mode: two game instances on one machine).
 *    The tuner port 4318 is an immediate in the binary; a second instance would abort at init
 *    because the first one holds it.  Env:
 *      CIV5_TUNER_PORT=4319          rebind TCP 4318 -> 4319
 *      CIV5_TUNER_BIND=127.0.0.1     bind the tuner to one interface instead of 0.0.0.0
 *      CIV5_PORT_MAP=62056=62057,... generic IPv4 port remap for any bind() (TCP or UDP)
 *
 * Build: gcc -m32 -O2 -shared -fPIC -o libtuner_recv_fix.so tuner_recv_fix.c -ldl
 * Use:   LD_PRELOAD=/abs/path/libtuner_recv_fix.so ./Civ5XP
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

static void note(const char *msg) { fprintf(stderr, "[tuner_fix] %s\n", msg); }

typedef ssize_t (*recv_fn)(int, void *, size_t, int);
static recv_fn real_recv;

ssize_t recv(int fd, void *buf, size_t len, int flags)
{
    if (!real_recv)
        real_recv = (recv_fn)dlsym(RTLD_NEXT, "recv");
    /* Only the tuner's liveness probe calls recv(fd, NULL, 0); leave every other recv alone. */
    if (len != 0 || buf != NULL || getenv("TUNER_FIX_NO_RECV"))
        return real_recv(fd, buf, len, flags);

    char probe;
    ssize_t r = real_recv(fd, &probe, 1, MSG_PEEK | MSG_DONTWAIT);
    if (r > 0)
        return 0;                       /* still connected, data pending */
    if (r == 0) {                       /* orderly shutdown by peer */
        errno = ECONNRESET;
        return -1;
    }
    if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
        return 0;                       /* connected, idle */
    return -1;                          /* real error: propagate */
}

/* ---------------------------------------------------------------- bind() remap */
#define TUNER_PORT 4318
typedef int (*bind_fn)(int, const struct sockaddr *, socklen_t);
static bind_fn real_bind;

static int mapped_port(int port)
{
    const char *tp = getenv("CIV5_TUNER_PORT");
    if (tp && port == TUNER_PORT) return atoi(tp);
    const char *map = getenv("CIV5_PORT_MAP");     /* "from=to,from=to" */
    while (map && *map) {
        int from = atoi(map);
        const char *eq = strchr(map, '=');
        if (!eq) break;
        int to = atoi(eq + 1);
        if (from == port && to > 0) return to;
        const char *comma = strchr(map, ',');
        if (!comma) break;
        map = comma + 1;
    }
    return port;
}

int bind(int fd, const struct sockaddr *addr, socklen_t len)
{
    if (!real_bind)
        real_bind = (bind_fn)dlsym(RTLD_NEXT, "bind");
    if (!addr || addr->sa_family != AF_INET || len < sizeof(struct sockaddr_in))
        return real_bind(fd, addr, len);

    struct sockaddr_in in;
    memcpy(&in, addr, sizeof in);
    int port = ntohs(in.sin_port), to = mapped_port(port);
    const char *bind_ip = (port == TUNER_PORT) ? getenv("CIV5_TUNER_BIND") : NULL;
    if (to == port && !bind_ip)
        return real_bind(fd, addr, len);

    in.sin_port = htons((uint16_t)to);
    if (bind_ip && inet_pton(AF_INET, bind_ip, &in.sin_addr) != 1)
        note("CIV5_TUNER_BIND is not an IPv4 address; ignored");
    char buf[128];
    snprintf(buf, sizeof buf, "bind: port %d -> %s:%d", port, inet_ntoa(in.sin_addr), to);
    note(buf);
    return real_bind(fd, (struct sockaddr *)&in, sizeof in);
}

/* ---------------------------------------------------------------- code patches */
#define SYM_DISABLE  "_ZN15cvTunerListener7DisableEv"
#define SYM_ENTER_STAGING "_ZN15cvTunerListener30EnteringMultiplayerStagingRoomEv"
#define SYM_EXIT_STAGING  "_ZN15cvTunerListener29ExitingMultiplayerStagingRoomEv"
#define SYM_LAUNCHED "_ZN15cvTunerListener25OnMultiplayerGameLaunchedER13EventTemplateI14Event_Int2TypeILi139EE" \
                     "14NullEventClass21LinearEventDispatcher21LocalMachineContainerS3_9BaseEventI33cvEventSystem" \
                     "LocalMachineAccessor23cvSubscriptionValidatorES3_E"

static int make_writable(uint8_t *at, size_t n)
{
    uintptr_t page = (uintptr_t)at & ~(uintptr_t)(sysconf(_SC_PAGESIZE) - 1);
    return mprotect((void *)page, ((uintptr_t)(at + n) - page) + 1, PROT_READ | PROT_WRITE | PROT_EXEC);
}

/* Turn a function into an immediate `ret`.  Only if it starts with the expected PIC prologue
 * `call next; pop %eax` (e8 00 00 00 00 58) so we never stomp on a different build. */
static void patch_ret(const char *sym, const char *label)
{
    uint8_t *fn = (uint8_t *)dlsym(RTLD_DEFAULT, sym);
    char buf[160];
    if (!fn) { snprintf(buf, sizeof buf, "%s: symbol not found; NOT patched", label); note(buf); return; }
    static const uint8_t prologue[6] = {0xE8, 0x00, 0x00, 0x00, 0x00, 0x58};
    if (memcmp(fn, prologue, 6) != 0) { snprintf(buf, sizeof buf, "%s: unexpected prologue; NOT patched", label); note(buf); return; }
    if (make_writable(fn, 1) != 0) { note("mprotect failed"); return; }
    fn[0] = 0xC3;
    snprintf(buf, sizeof buf, "%s at %p -> ret", label, (void *)fn); note(buf);
}

__attribute__((constructor)) static void patch_mp_disable(void)
{
    /* EnteringMultiplayerStagingRoom tail-jumps to Disable(); ExitingMultiplayerStagingRoom re-arms the
     * listener (dropping the current client).  Neither is wanted for the harness. */
    if (!getenv("TUNER_FIX_NO_PATCH") && dlsym(RTLD_DEFAULT, SYM_DISABLE)) {
        patch_ret(SYM_ENTER_STAGING, "EnteringMultiplayerStagingRoom");
        patch_ret(SYM_EXIT_STAGING, "ExitingMultiplayerStagingRoom");
    }
    if (getenv("TUNER_FIX_NO_PATCH")) { note("TUNER_FIX_NO_PATCH set; MP tuner-disable NOT patched"); return; }
    uint8_t *disable = (uint8_t *)dlsym(RTLD_DEFAULT, SYM_DISABLE);
    uint8_t *fn      = (uint8_t *)dlsym(RTLD_DEFAULT, SYM_LAUNCHED);
    if (!disable || !fn) { note("symbols not found; MP tuner-disable NOT patched"); return; }

    /* scan the handler for `e8 rel32` whose target is Disable(); patch the first one only */
    for (size_t i = 0; i < 0x120; i++) {
        if (fn[i] != 0xE8) continue;
        int32_t rel; memcpy(&rel, fn + i + 1, 4);
        uint8_t *target = fn + i + 5 + rel;
        if (target != disable) continue;

        if (make_writable(fn + i, 5) != 0) { note("mprotect failed"); return; }
        memset(fn + i, 0x90, 5);                       /* call Disable -> 5x nop */
        char buf[128];
        snprintf(buf, sizeof buf, "patched call Disable() at %p (OnMultiplayerGameLaunched+0x%zx)", (void *)(fn + i), i);
        note(buf);
        return;
    }
    note("call to Disable() not found in OnMultiplayerGameLaunched; NOT patched");
}
