/* Controlled teaching fixture; key is never an input to candidate extraction. */
#include <stdint.h>
#include <string.h>
#include "aes.h"

void AES_128_encrypt(unsigned char out[16], unsigned char in[16])
{
    static const uint8_t teaching_key[16] = {
        0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
        0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f
    };
    struct AES_ctx ctx;
    memcpy(out, in, 16);
    AES_init_ctx(&ctx, teaching_key);
    AES_ECB_encrypt(&ctx, out);
}
