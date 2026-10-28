ifndef WBG_ORIGINAL_SOURCE
$(error WBG_ORIGINAL_SOURCE must name the copied target source)
endif
ifndef WBG_AES_SOURCE_DIR
$(error WBG_AES_SOURCE_DIR must name the pinned tiny-AES-c source)
endif
ifeq ($(strip $(MORE_INCDIR)),)
$(error MORE_INCDIR must name the installed Whiteboxgrind header directory)
endif

CC ?= cc
CPPFLAGS = -I"$(MORE_INCDIR)" -I"$(WBG_AES_SOURCE_DIR)" -DCBC=0 -DCTR=0 -DECB=1
CFLAGS = -O2 -g -fno-pie $(MORE_CFLAGS)
OBJECTS = main.o wrapper.o original.o
ifeq ($(WBG_EXTRA_AES),1)
OBJECTS += aes.o
endif

target: $(OBJECTS)
	$(CC) -no-pie -o $@ $^
ifneq ($(strip $(WBG_TARGET_ARTIFACT_DIR)),)
	install -m755 $@ "$(WBG_TARGET_ARTIFACT_DIR)/target"
endif

main.o: main.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

wrapper.o: wrapper.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

original.o: $(WBG_ORIGINAL_SOURCE)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c "$(WBG_ORIGINAL_SOURCE)" -o $@

aes.o:
	$(CC) $(CPPFLAGS) $(CFLAGS) -c "$(WBG_AES_SOURCE_DIR)/aes.c" -o $@
