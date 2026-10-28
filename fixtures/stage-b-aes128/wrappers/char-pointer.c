/* ABI bridge for the actual WhibOx #47 char-pointer prototype. */
void AES_128_encrypt(char *out, char *in);

void wbg_encrypt_block(unsigned char out[16], unsigned char in[16])
{
    AES_128_encrypt((char *)out, (char *)in);
}
