# This resource directory is consumed by the pinned upstream tracer.
# WBG_AES_SOURCE_DIR points to the unchanged tiny-AES-c source in Linux.
ifndef WBG_AES_SOURCE_DIR
$(error WBG_AES_SOURCE_DIR must name the pinned tiny-AES-c source directory)
endif
ifeq ($(strip $(MORE_INCDIR)),)
$(error MORE_INCDIR must name the installed Whiteboxgrind header directory)
endif

CFLAGS = -O2 -g -fno-pie $(MORE_CFLAGS)
CPPFLAGS = -I"$(MORE_INCDIR)" -I"$(WBG_AES_SOURCE_DIR)" -DCBC=0 -DCTR=0 -DECB=1

target: main.o adapter.o aes.o
	$(CC) -no-pie -o $@ $^
ifneq ($(strip $(WBG_TARGET_ARTIFACT_DIR)),)
	install -m755 $@ "$(WBG_TARGET_ARTIFACT_DIR)/target"
endif

main.o: main.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

adapter.o: adapter.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

aes.o:
	$(CC) $(CPPFLAGS) $(CFLAGS) -c "$(WBG_AES_SOURCE_DIR)/aes.c" -o $@
