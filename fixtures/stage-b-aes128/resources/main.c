#include <stdint.h>
#include <stdio.h>
#include <whiteboxgrind.h>

#if defined(NVALGRIND)
#error "Valgrind client requests are disabled for this build"
#endif
#if !defined(WHITEBOX_START) || !defined(WHITEBOX_END)
#error "A real Whiteboxgrind client-request header is required"
#endif

void wbg_encrypt_block(unsigned char out[16], unsigned char in[16]);

int main(void)
{
    uint8_t in[16];
    uint8_t out[16];
    if (fread(in, 1, sizeof(in), stdin) != sizeof(in)) {
        fputs("expected exactly 16 input bytes\n", stderr);
        return 2;
    }
    if (fgetc(stdin) != EOF || ferror(stdin)) {
        fputs("trailing input bytes or input error\n", stderr);
        return 2;
    }
    WHITEBOX_START;
    wbg_encrypt_block(out, in);
    WHITEBOX_END;
    if (fwrite(out, 1, sizeof(out), stdout) != sizeof(out) || fflush(stdout) != 0) {
        fputs("could not write 16 output bytes\n", stderr);
        return 3;
    }
    return 0;
}
