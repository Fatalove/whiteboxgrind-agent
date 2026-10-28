/* ABI bridge; the target's function body and symbol remain unchanged. */
void AES_128_encrypt(unsigned char out[16], unsigned char in[16]);

void wbg_encrypt_block(unsigned char out[16], unsigned char in[16])
{
    AES_128_encrypt(out, in);
}
