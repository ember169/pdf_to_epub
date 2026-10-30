/* Test-only shim for Wine < 9: Rust's std (used by cryptography) imports ProcessPrng from bcryptprimitives.dll,
   which old Wine lacks. Real Windows has it. Never shipped; installed only into the Wine test prefix. */
#include <windows.h>
#include <bcrypt.h>
BOOL WINAPI ProcessPrng(PBYTE data, SIZE_T len) {
    return BCryptGenRandom(NULL, data, (ULONG)len, BCRYPT_USE_SYSTEM_PREFERRED_RNG) == 0;
}
