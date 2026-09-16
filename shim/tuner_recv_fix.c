/* LD_PRELOAD shim for Civ5XP (32-bit): make the FireTuner listener notice client disconnects.
 *
 * cvTunerListener::OnUpdate polls the tuner connection with recv(fd, NULL, 0, 0) and treats a
 * return of -1 as "client gone" (Windows semantics).  On Linux a zero-length recv returns 0 even
 * when the peer has closed or reset the connection, so the game never re-accepts a new tuner
 * client.  Here a zero-length recv is turned into a 1-byte MSG_PEEK|MSG_DONTWAIT probe:
 *   - data available   -> return 0 (nothing consumed, same as before)
 *   - would block      -> return 0
 *   - EOF (peer FIN)   -> return -1, errno=ECONNRESET
 *   - error            -> return -1 (errno preserved)
 * Everything else is passed straight through.
 *
 * Build: gcc -m32 -O2 -shared -fPIC -o libtuner_recv_fix.so tuner_recv_fix.c -ldl
 * Use:   LD_PRELOAD=/abs/path/libtuner_recv_fix.so ./Civ5XP
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stddef.h>
#include <sys/socket.h>
#include <sys/types.h>

typedef ssize_t (*recv_fn)(int, void *, size_t, int);
static recv_fn real_recv;

ssize_t recv(int fd, void *buf, size_t len, int flags)
{
    if (!real_recv)
        real_recv = (recv_fn)dlsym(RTLD_NEXT, "recv");
    if (len != 0)
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
